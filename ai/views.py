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
        # O relatório do paciente vai para a tela dele. Esta só desenha resumo
        # e apoio diagnóstico, e com um relatório mostrava "Resumo" e
        # "Hipóteses" em branco. O redirecionamento cobre os avisos que já
        # estão no sino apontando para cá, e qualquer link antigo.
        if job.kind == AIJobKind.PATIENT_REPORT:
            return redirect('ai:relatorio-detalhe', job_id=job.id)
        artifacts = job.artifacts.order_by('-created_at')
        return render(request, 'ai/job_detail.html', {'job': job, 'artifacts': artifacts})


class ArtifactAcceptView(TenantScopedView):
    def post(self, request, artifact_id):
        from tenancy.models import Membership

        artifact = get_object_or_404(scope_to_tenant(AIArtifact.objects.all(), request.access_context), id=artifact_id)
        if artifact.job.kind == AIJobKind.PATIENT_REPORT:
            # Aprovar o relatório é a ponte que cria o rascunho do documento
            # com o texto editado (`ai:relatorio-aprovar`). Aceitá-lo por aqui
            # marcaria o artefato como aprovado sem documento nenhum.
            return redirect('ai:relatorio-detalhe', job_id=artifact.job_id)
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
        if artifact.job.kind == AIJobKind.PATIENT_REPORT:
            # O relatório se descarta pela tela dele (`ai:relatorio-descartar`),
            # que apaga o texto e deixa a trilha.
            return redirect('ai:relatorio-detalhe', job_id=artifact.job_id)
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
        """O paciente, reautorizado pelo inquilino.

        O `patient_id` nem sempre vem da URL -- o descarte o recebe do
        formulario, porque precisa saber para onde voltar depois de o
        artefato deixar de existir. Valor ausente ou mal formado e 404 e
        nao 500: `get_object_or_404` com um id que nao e UUID levanta
        `ValidationError`, que o Django nao transforma em pagina de erro
        tratada.
        """
        import uuid as _uuid

        from patients.models import Patient

        try:
            _uuid.UUID(str(patient_id))
        except (ValueError, TypeError, AttributeError):
            raise Http404
        return get_object_or_404(
            scope_to_tenant(Patient.objects.all(), request.access_context), id=patient_id,
        )

    def _membership(self, request):
        from tenancy.models import Membership

        return Membership.objects.filter(id=request.access_context.membership_id).first()

    @staticmethod
    def _pedido_do_portal(request, patient, pedido_id):
        """O pedido de relatório do portal que este relatório atende, ou `None`.

        Chega pela URL (o botão da tela do pedido) e depois por um campo
        escondido; nos dois casos é conferido por inteiro — da clínica, do
        paciente, de relatório e ainda aberto. Um id que não confere não é
        erro: o relatório segue, só sem responder a pedido nenhum.
        """
        if not pedido_id:
            return None
        from documents import pedidos_do_portal
        from documents.models import DocumentRequestKind

        return pedidos_do_portal.pedido_aberto(
            request.access_context.tenant_id, patient.id, pedido_id,
            kind=DocumentRequestKind.REPORT,
        )

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
        extra = {}
        pedido_portal = self._pedido_do_portal(request, patient, request.GET.get('pedido_portal'))
        if pedido_portal is not None:
            # A tela abre com o que o paciente pediu no portal, na caixa
            # aberta: quem pede o relatório ao modelo é o médico.
            from documents import pedidos_do_portal

            codigo, texto = pedidos_do_portal.instrucao_para_ia(pedido_portal)
            extra = {'pedido_portal': pedido_portal, 'finalidade_escolhida': codigo, 'pedido': texto}
        return render(request, 'ai/relatorio_form.html', self._tela(request, patient, **extra))

    def post(self, request, patient_id):
        patient = self._paciente(request, patient_id)
        pedido = (request.POST.get('pedido') or '').strip()
        escolhida = request.POST.get('finalidade', '')
        pedido_portal = self._pedido_do_portal(request, patient, request.POST.get('pedido_portal'))
        if not pedido:
            return render(request, 'ai/relatorio_form.html', self._tela(
                request, patient,
                erro='Diga o que o relatório precisa conter.',
                finalidade_escolhida=escolhida, pedido_portal=pedido_portal,
            ), status=400)
        try:
            job = services.request_patient_report(
                request.access_context, patient, escolhida, pedido,
                # A confirmação só vale vinda da tela de bloqueio, que é a
                # única que manda este campo — e ela só aparece depois de a
                # recusa ter dito qual marcador foi encontrado.
                risco_confirmado=request.POST.get('risco_confirmado') == '1',
                pedido_portal=pedido_portal.id if pedido_portal else None,
            )
        except AIAuthorizationDenied as exc:
            return HttpResponseForbidden(str(exc))
        if pedido_portal is not None:
            from documents import pedidos_do_portal

            pedidos_do_portal.marcar_em_revisao(pedido_portal, request.access_context.user_id)
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
        # O pedido do portal que este relatório atende, aberto ou não: a
        # tela mostra de onde o relatório veio mesmo depois de respondido.
        pedido_portal = None
        if (job.target_ref or {}).get('pedido_portal'):
            from documents.models import DocumentRequest

            pedido_portal = DocumentRequest.objects.filter(
                tenant_id=job.tenant_id, patient_id=job.patient_id,
                id=job.target_ref['pedido_portal'],
            ).first()
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
            'pedido_portal': pedido_portal,
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

        # Só o relatório do paciente (auditoria de 2026-11-11): buscado só
        # pela clínica, o POST com o id de um resumo transformava o resumo
        # num documento de relatório e sobrescrevia o resultado dele.
        artifact = get_object_or_404(
            scope_to_tenant(AIArtifact.objects.all(), request.access_context), id=artifact_id,
            job__kind=AIJobKind.PATIENT_REPORT,
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
                # O relatório pedido pelo portal responde ao pedido ao virar
                # documento — a mesma marca do rascunho escrito à mão na tela
                # do pedido. O médico revisou o texto da IA para chegar aqui.
                pedido_id = (artifact.job.target_ref or {}).get('pedido_portal')
                if pedido_id:
                    from documents import pedidos_do_portal

                    pedido_portal = pedidos_do_portal.pedido_aberto(
                        artifact.tenant_id, artifact.job.patient_id, pedido_id,
                    )
                    if pedido_portal is not None:
                        pedidos_do_portal.marcar_atendido(
                            pedido_portal, documento, reviewer,
                            request.access_context.user_id, alterado=True, via_ia=True,
                        )
        except AlreadyReviewed as exc:
            # Duplo clique, ou o botao de voltar: o documento ja existe, e
            # mostra-lo e a resposta util. Repetir "ja foi revisado" numa
            # pagina em branco deixa o medico sem saber se deu certo.
            from documents.models import MedicalDocument

            pronto = MedicalDocument.objects.filter(
                tenant_id=artifact.tenant_id,
                content_snapshot__ai_artifact_id=str(artifact.id),
            ).first()
            if pronto is not None:
                return redirect('documents:medical-detail', document_id=pronto.id)
            return HttpResponseForbidden(str(exc))
        except (ArtifactStale, relatorio.RelatorioNaoAprovado) as exc:
            return HttpResponseForbidden(str(exc))
        except MissingPhysicianProfile:
            return HttpResponseForbidden(
                'Para emitir documento é preciso ter o CRM registrado no seu perfil.'
            )
        return redirect('documents:medical-detail', document_id=documento.id)


class RelatorioRejeitarView(RelatorioView):
    """Descarta o rascunho e volta ao prontuário.

    Três coisas que a primeira versão errava, e as três apareceram no
    primeiro uso real:

    - ela marcava o artefato como rejeitado e **redirecionava de volta
      para a mesma tela**, que continuava mostrando o rascunho inteiro sob
      um crachá vermelho. Descartar algo e continuar olhando para ele não
      é descartar;
    - o segundo clique levantava `AlreadyReviewed` e devolvia a mensagem
      crua numa página em branco — e, naquela altura, em inglês;
    - nada era apagado. "Rejeitado" é um estado, e o que se quer é que o
      texto suma.

    O `patient_id` vem do formulário, e não do artefato, justamente porque
    o artefato deixa de existir: sem ele, o segundo clique não teria para
    onde voltar. Vindo do POST, ele é reautorizado pelo inquilino como
    qualquer outro — a view não confia no campo, confere.
    """

    def post(self, request, artifact_id):
        from . import relatorio

        patient = self._paciente(request, request.POST.get('patient_id'))
        # Só o relatório, e só deste paciente (auditoria de 2026-11-11). O POST
        # com o id de um resumo aprovado — ou de outro médico — apagava o job
        # e o artefato, e com eles a evidência da revisão.
        artifact = AIArtifact.objects.filter(
            tenant_id=request.access_context.tenant_id, id=artifact_id,
            job__kind=AIJobKind.PATIENT_REPORT, job__patient_id=patient.id,
        ).select_related('job').first()
        if artifact is None:
            # Já foi apagado: o segundo clique, ou o botão de voltar do
            # navegador. O resultado pedido já aconteceu, e dizer "não
            # encontrado" seria relatar como erro um pedido atendido.
            return redirect('clinical:timeline', patient_id=patient.id)
        try:
            relatorio.descartar_rascunho(
                artifact.job, request.access_context.user_id,
                motivo=request.POST.get('reason', ''),
            )
        except relatorio.RascunhoJaVirouDocumento as exc:
            return HttpResponseForbidden(str(exc))
        return redirect('clinical:timeline', patient_id=patient.id)
