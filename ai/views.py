from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from documents.issuance import MissingPhysicianProfile
from tenancy.permissions import Capability, CapabilityRequiredView
from tenancy.selectors import scope_to_tenant

from . import services
from .context import AIAuthorizationDenied
from .models import AIArtifact, AIJob, AIJobKind
from .review import AlreadyReviewed, ArtifactStale, accept_artifact, reject_artifact


class TenantScopedView(CapabilityRequiredView):
    """IA sobre atendimento: lê o prontuário, então segue o prontuário.

    Resumir um atendimento é ler o atendimento — o resultado carrega
    queixa, história e conduta. Deixar a tela aberta a quem não pode ler o
    prontuário entregaria por resumo exatamente o que a matriz nega por
    leitura direta, que é a forma mais silenciosa de furar a regra.
    """

    required_capability = Capability.CLINICAL_AI


class EncounterSummaryRequestView(TenantScopedView):
    """Manual trigger for RF-11.01/02 -- a physician explicitly asks for an
    AI-drafted summary of one encounter. Runs the same authorization/
    privacy-policy path as the automatic post-finalization job.
    """

    def post(self, request, encounter_id):
        from clinical.models import Encounter
        from .tasks import run_ai_job

        encounter = get_object_or_404(
            scope_to_tenant(Encounter.objects.all(), request.access_context), id=encounter_id,
        )
        try:
            job = services.create_job(
                request.access_context, AIJobKind.ENCOUNTER_SUMMARY,
                purpose='Resumo solicitado manualmente', patient_id=encounter.patient_id, encounter_id=encounter.id,
            )
        except AIAuthorizationDenied as exc:
            return HttpResponseForbidden(str(exc))
        if job.status == 'queued':
            run_ai_job.delay(str(job.id))
        return redirect('ai:job-detail', job_id=job.id)


class AIJobDetailView(TenantScopedView):
    def get(self, request, job_id):
        job = get_object_or_404(scope_to_tenant(AIJob.objects.all(), request.access_context), id=job_id)
        artifacts = job.artifacts.order_by('-created_at')
        return render(request, 'ai/job_detail.html', {'job': job, 'artifacts': artifacts})


class ArtifactAcceptView(TenantScopedView):
    def post(self, request, artifact_id):
        from tenancy.models import Membership

        artifact = get_object_or_404(scope_to_tenant(AIArtifact.objects.all(), request.access_context), id=artifact_id)
        reviewer = Membership.objects.filter(id=request.access_context.membership_id).first()
        try:
            accept_artifact(artifact, reviewer)
        except (ArtifactStale, AlreadyReviewed) as exc:
            return HttpResponseForbidden(str(exc))
        return redirect('ai:job-detail', job_id=artifact.job_id)


class ArtifactRejectView(TenantScopedView):
    def post(self, request, artifact_id):
        from tenancy.models import Membership

        artifact = get_object_or_404(scope_to_tenant(AIArtifact.objects.all(), request.access_context), id=artifact_id)
        reviewer = Membership.objects.filter(id=request.access_context.membership_id).first()
        try:
            reject_artifact(artifact, reviewer, request.POST.get('reason', ''))
        except (ArtifactStale, AlreadyReviewed) as exc:
            return HttpResponseForbidden(str(exc))
        return redirect('ai:job-detail', job_id=artifact.job_id)


class RelatorioView(TenantScopedView):
    """Relatório do paciente: exige as duas capacidades, não uma.

    `CLINICAL_AI` porque lê o prontuário inteiro e manda o conteúdo ao
    provedor — é a mesma porta do resumo e do chat. `ISSUE_DOCUMENT`
    porque o produto disto é um documento médico que alguém vai assinar e
    entregar, e a responsabilidade por ele é de quem assina.

    A secretária, que tem a segunda e não a primeira, não entra; o gestor,
    que não tem nenhuma das duas, também não. Exigir só `CLINICAL_AI`
    abriria a geração a quem não emite documento, e o rascunho ficaria
    pendurado esperando um médico que não pediu nada.
    """

    def dispatch(self, request, *args, **kwargs):
        context = request.access_context
        if context is None or not context.can(Capability.ISSUE_DOCUMENT):
            raise Http404
        return super().dispatch(request, *args, **kwargs)

    def _paciente(self, request, patient_id):
        from patients.models import Patient

        return get_object_or_404(
            scope_to_tenant(Patient.objects.all(), request.access_context), id=patient_id,
        )

    def _membership(self, request):
        from tenancy.models import Membership

        return Membership.objects.filter(id=request.access_context.membership_id).first()

    @staticmethod
    def _total_de_atendimentos(patient):
        from clinical.models import Encounter

        return Encounter.objects.filter(tenant_id=patient.tenant_id, patient=patient).count()


class RelatorioRequestView(RelatorioView):
    """Escolhe a finalidade, escreve o pedido e dispara."""

    def _tela(self, request, patient, **extra):
        from . import relatorio

        dados = {
            'patient': patient,
            'finalidades': relatorio.FINALIDADES,
            'teto': relatorio.TETO_DE_ATENDIMENTOS,
            'total_de_atendimentos': self._total_de_atendimentos(patient),
        }
        dados.update(extra)
        return dados

    def get(self, request, patient_id):
        patient = self._paciente(request, patient_id)
        return render(request, 'ai/relatorio_form.html', self._tela(request, patient))

    def post(self, request, patient_id):
        patient = self._paciente(request, patient_id)
        pedido = (request.POST.get('pedido') or '').strip()
        escolhida = request.POST.get('finalidade', '')
        if not pedido:
            return render(request, 'ai/relatorio_form.html', self._tela(
                request, patient,
                erro='Diga o que o relatório precisa conter.',
                finalidade_escolhida=escolhida,
            ), status=400)
        try:
            job = services.request_patient_report(
                request.access_context, patient, escolhida, pedido,
                # A confirmação só vale vinda da tela de bloqueio, que é a
                # única que manda este campo — e ela só aparece depois de a
                # recusa ter dito qual marcador foi encontrado.
                risco_confirmado=request.POST.get('risco_confirmado') == '1',
            )
        except AIAuthorizationDenied as exc:
            return HttpResponseForbidden(str(exc))
        return redirect('ai:relatorio-detalhe', job_id=job.id)


class RelatorioDetailView(RelatorioView):
    """Acompanha a geração e, quando pronta, abre o rascunho para revisão."""

    def get(self, request, job_id):
        from documents.models import MedicalDocument

        from . import relatorio

        job = get_object_or_404(
            scope_to_tenant(AIJob.objects.all(), request.access_context),
            id=job_id, kind=AIJobKind.PATIENT_REPORT,
        )
        artifact = job.artifacts.order_by('-created_at').first()
        documento = None
        if artifact is not None:
            documento = MedicalDocument.objects.filter(
                tenant_id=job.tenant_id, patient_id=job.patient_id,
                content_snapshot__ai_artifact_id=str(artifact.id),
            ).first()
        return render(request, 'ai/relatorio_detalhe.html', {
            'job': job, 'artifact': artifact, 'documento': documento,
            'patient': job.patient,
            'finalidade': relatorio.finalidade((job.target_ref or {}).get('finalidade')),
            'pedido': (job.target_ref or {}).get('pedido', ''),
            'texto': relatorio.texto_do_relatorio(artifact.result) if artifact else '',
        })


class RelatorioAprovarView(RelatorioView):
    """Aprova o rascunho e cria o documento, numa transação só.

    O texto vem da tela, e não do artefato: a caixa é editável de
    propósito. O médico que corrige uma frase e clica em aprovar espera
    que o documento saia com a correção — gravar o original e descartar a
    edição seria a pior das saídas possíveis, porque é silenciosa.

    Por isso o artefato é sempre marcado como `EDITED`, e não `ACCEPTED`:
    o que vale é o texto que o médico leu na tela, e é esse que fica
    gravado como a versão revisada.
    """

    def post(self, request, artifact_id):
        from django.db import transaction

        from . import relatorio
        from .review import edit_artifact

        artifact = get_object_or_404(
            scope_to_tenant(AIArtifact.objects.all(), request.access_context), id=artifact_id,
        )
        reviewer = self._membership(request)
        texto = (request.POST.get('texto') or '').strip()
        if not texto:
            return HttpResponseForbidden('O relatório não pode ficar vazio.')

        sobrou = relatorio.marcadores_residuais(texto)
        if sobrou:
            # O esquema já recusa o que vem do modelo; esta é a mesma guarda
            # do outro lado, porque o texto da tela passou por um editor
            # humano e pode ter ganhado o marcador numa colagem.
            return HttpResponseForbidden(
                'O texto ainda contém ' + ', '.join(sobrou) + '. Troque por "o paciente".'
            )
        try:
            with transaction.atomic():
                resultado = dict(artifact.result)
                resultado['secoes'] = [{'titulo': '', 'texto': texto}]
                edit_artifact(artifact, reviewer, resultado)
                documento = relatorio.criar_rascunho_de_documento(
                    artifact, reviewer, request.access_context.user_id,
                )
        except (ArtifactStale, AlreadyReviewed, relatorio.RelatorioNaoAprovado) as exc:
            return HttpResponseForbidden(str(exc))
        except MissingPhysicianProfile:
            return HttpResponseForbidden(
                'Para emitir documento é preciso ter o CRM registrado no seu perfil.'
            )
        return redirect('documents:medical-detail', document_id=documento.id)


class RelatorioRejeitarView(RelatorioView):
    def post(self, request, artifact_id):
        artifact = get_object_or_404(
            scope_to_tenant(AIArtifact.objects.all(), request.access_context), id=artifact_id,
        )
        try:
            reject_artifact(artifact, self._membership(request), request.POST.get('reason', ''))
        except (ArtifactStale, AlreadyReviewed) as exc:
            return HttpResponseForbidden(str(exc))
        return redirect('ai:relatorio-detalhe', job_id=artifact.job_id)
