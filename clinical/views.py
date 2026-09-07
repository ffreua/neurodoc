from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.forms import modelform_factory
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from audit.services import record_audit_event
from patients.models import Patient
from tenancy.selectors import scope_to_tenant

from . import carry_forward as cf
from . import finalization, selectors
from .cranial_nerves import upsert_cranial_nerve_finding
from exams.models import ExamScale
from exams.recording import (
    mark_group_normal, record_scale, save_axis, undo_group_normal,
)
from exams.selectors import build_tree, resolve_template

from .examination import group_findings_by_domain, upsert_finding
from .forms import (
    AmendmentForm, DiagnosisForm, EncounterForm, ExamResultForm, FindingForm, LabValueForm,
    MedicationForm,
)
from .models import (
    Encounter, EncounterDiagnosis, EncounterStatus, ExaminationDomain, ExaminationFinding,
    ExamResult, ExtractionStatus, LabValue, Medication,
)


def _first_error(form):
    """Primeira mensagem de erro do formulário, em texto corrido."""
    for field, errors in form.errors.items():
        if not errors:
            continue
        label = form.fields[field].label if field in form.fields else ''
        return f'{label}: {errors[0]}' if label else errors[0]
    return 'Não foi possível salvar.'


def _blocked(request, encounter, message, anchor=''):
    """Recusa uma ação sem tirar quem usa o sistema de dentro dele.

    Antes cada recusa devolvia uma página de texto cru — "3", o dict de
    erros do formulário, uma frase em inglês. Agora volta para o
    atendimento com a mensagem na tela, na aba de onde a ação partiu.
    """
    messages.error(request, message)
    url = reverse('clinical:detail', args=[encounter.id])
    return redirect(f'{url}#{anchor}' if anchor else url)

class TenantScopedView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if request.access_context is None:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


def _doctor_membership(request):
    from tenancy.models import Membership, MembershipStatus, Role

    return Membership.objects.filter(
        tenant_id=request.access_context.tenant_id, user_id=request.access_context.user_id,
        status=MembershipStatus.ACTIVE, roles__contains=[Role.DOCTOR],
    ).first()


class DiagnosisLookupView(TenantScopedView):
    """Autocomplete do CID-10, por código ou por descrição.

    O catálogo é global (não é dado do inquilino), mas o endpoint continua
    exigindo sessão autenticada: quem não tem vínculo ativo não enumera
    catálogo nem qualquer outra coisa daqui.
    """

    def get(self, request):
        from catalogs.selectors import search_diagnosis_codes

        term = request.GET.get('q', '')
        return JsonResponse({'results': search_diagnosis_codes(term)})


class TimelineView(TenantScopedView):
    def get(self, request, patient_id):
        patient = get_object_or_404(scope_to_tenant(Patient.objects.all(), request.access_context), id=patient_id)
        encounters = selectors.patient_timeline(request.access_context, patient)
        return render(request, 'clinical/timeline.html', {'patient': patient, 'encounters': encounters})


class EncounterCreateView(TenantScopedView):
    def post(self, request, patient_id):
        patient = get_object_or_404(scope_to_tenant(Patient.objects.all(), request.access_context), id=patient_id)
        membership = _doctor_membership(request)
        if membership is None:
            raise Http404
        encounter = Encounter.objects.create(
            tenant_id=request.access_context.tenant_id, patient=patient, physician_membership=membership,
            occurred_at=timezone.now(), status=EncounterStatus.DRAFT,
        )
        source = cf.default_source_encounter(encounter)
        if source is not None:
            cf.carry_forward(request.access_context, encounter, source)
        return redirect('clinical:detail', encounter_id=encounter.id)


class EncounterDetailView(TenantScopedView):
    def get(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        pending_items = list(
            encounter.carry_forward_items.filter(review_action='pending')
            .select_related('source_encounter')
        )
        # Rótulo e valor legíveis: a tela mostrava `plan_text` com o dicionário
        # cru ao lado, e a hipótese como `diagnosis:<uuid>`.
        for item in pending_items:
            item.described = cf.describe_item(item)
        findings = list(
            encounter.examination_findings.select_related('template_node')
            .order_by('domain', 'item_code', 'side')
        )
        template = resolve_template(
            request.access_context.tenant_id, request.access_context.membership_id,
        )
        scales = list(
            ExamScale.objects
            .filter(tenant_id=request.access_context.tenant_id, active=True)
            .prefetch_related('items')
        )
        # Escalas já aplicadas neste atendimento, para o formulário reabrir
        # preenchido em vez de exigir digitar tudo de novo.
        scale_values = {
            finding.item_code.split('.', 1)[1]: finding
            for finding in findings
            if finding.item_code.startswith('escala.')
        }
        return render(request, 'clinical/detail.html', {
            'encounter': encounter, 'form': EncounterForm(instance=encounter),
            'finding_form': FindingForm(), 'diagnosis_form': DiagnosisForm(),
            'amendment_form': AmendmentForm(), 'pending_carry_forward': pending_items,
            'findings': findings,
            'findings_by_domain': group_findings_by_domain(findings),
            'exam_template': template,
            'exam_tree': build_tree(template, findings),
            # Atendimento finalizado continua legível, mas os controles do
            # roteiro saem desabilitados — o servidor já recusa a gravação,
            # e a tela não deve sugerir que ainda dá para editar.
            'exam_readonly': not encounter.is_editable(),
            'scales': scales,
            'scale_values': scale_values,
            'diagnoses': encounter.diagnoses.all().order_by('rank'),
            'amendments': encounter.amendments.all().order_by('authored_at'),
            # O que falta para finalizar, tudo de uma vez: a tela mostra a
            # lista antes do clique em vez de recusar um requisito por vez.
            'finalize_pending': finalization.missing_requirements(encounter),
            **self._extra_tabs(request, encounter),
        })

    def _extra_tabs(self, request, encounter):
        """Medicações, resultados de exame e o painel de apoio da IA.

        Os rascunhos da IA vêm junto do resultado a que pertencem: o médico
        revisa o rascunho olhando o exame, não numa fila de artefatos
        separada do prontuário.
        """
        from ai.extraction import latest_draft
        from ai.services import latest_diagnostic_support

        medications = list(encounter.medications.all())
        exam_results = list(
            encounter.exam_results.select_related('attachment').prefetch_related('lab_values')
        )
        for result in exam_results:
            values = list(result.lab_values.all())
            result.values_out = [v for v in values if v.flag in ('low', 'high', 'abnormal')]
            result.values_in = [v for v in values if v.flag == 'normal']
            result.values_unknown = [v for v in values if v.flag == 'no_reference']
            result.draft = (
                latest_draft(result)
                if result.extraction_status in (ExtractionStatus.READY, ExtractionStatus.ACCEPTED,
                                                ExtractionStatus.REJECTED)
                else None
            )

        support_job, support_artifact = latest_diagnostic_support(encounter)
        support_hypotheses, support_steps = [], []
        if support_artifact is not None:
            from ai.schemas import PRIORITY_LABELS, PRIORITY_TONES, STEP_CATEGORY_LABELS

            result = support_artifact.result or {}
            for item in result.get('hypotheses') or []:
                priority = item.get('priority', 'insufficient_evidence')
                support_hypotheses.append({
                    **item,
                    'priority_label': PRIORITY_LABELS.get(priority, priority),
                    'priority_tone': PRIORITY_TONES.get(priority, 'dark'),
                })
            for step in result.get('suggested_next_steps') or []:
                category = step.get('category', 'other')
                support_steps.append({
                    **step,
                    'category_label': STEP_CATEGORY_LABELS.get(category, category),
                })

        return {
            'medications': medications,
            'medication_form': MedicationForm(),
            'exam_results': exam_results,
            'exam_result_form': ExamResultForm(),
            'lab_value_form': LabValueForm(),
            'support_job': support_job,
            'support_artifact': support_artifact,
            'support_hypotheses': support_hypotheses,
            'support_steps': support_steps,
            'support_result': (support_artifact.result if support_artifact else {}) or {},
        }


class EncounterAutosaveView(TenantScopedView):
    """Grava a parte do prontuário que veio no envio.

    Duas coisas importam aqui:

    - **grava só os campos enviados.** A tela divide história e conduta em
      abas; validar o formulário inteiro faria salvar a história apagar a
      conduta, porque os campos da outra aba chegam ausentes e o ModelForm
      os gravaria em branco.
    - **responde conforme quem perguntou.** Chamada por `fetch` (o autosave)
      devolve JSON com a versão nova; envio normal de formulário volta para
      a tela com mensagem, em vez de deixar o navegador numa página escrita
      "3".
    """

    #: Campos que a tela pode enviar; qualquer outro é ignorado.
    EDITABLE = tuple(EncounterForm.Meta.fields)

    def _wants_json(self, request):
        return (
            request.headers.get('X-Requested-With') == 'XMLHttpRequest'
            or 'application/json' in request.headers.get('Accept', '')
        )

    def _fail(self, request, encounter, message, status):
        if self._wants_json(request):
            return JsonResponse({'ok': False, 'error': message}, status=status)
        messages.error(request, message)
        return redirect('clinical:detail', encounter_id=encounter.id)

    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return self._fail(
                request, encounter,
                'Atendimento finalizado: o registro não pode mais ser alterado. '
                'Use um adendo.', 409,
            )
        submitted_version = request.POST.get('row_version')
        if submitted_version and str(encounter.row_version) != submitted_version:
            return self._fail(
                request, encounter,
                'Este atendimento foi alterado em outra aba desde que você o abriu. '
                'Recarregue a página para não sobrescrever o que já foi gravado.', 409,
            )

        submitted = [name for name in self.EDITABLE if name in request.POST]
        if not submitted:
            return self._fail(request, encounter, 'Nada para salvar.', 400)

        PartialForm = modelform_factory(Encounter, form=EncounterForm, fields=submitted)
        form = PartialForm(request.POST, instance=encounter)
        if not form.is_valid():
            first = next(iter(form.errors.values()))[0]
            return self._fail(request, encounter, first, 400)

        updated = form.save(commit=False)
        if updated.status == EncounterStatus.DRAFT:
            updated.status = EncounterStatus.IN_PROGRESS
        updated.row_version += 1
        updated.full_clean()
        updated.save()

        if self._wants_json(request):
            return JsonResponse({'ok': True, 'row_version': updated.row_version})
        messages.success(request, 'Prontuário salvo.')
        return redirect('clinical:detail', encounter_id=updated.id)


class FindingUpsertView(TenantScopedView):
    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.')
        form = FindingForm(request.POST)
        if not form.is_valid():
            return _blocked(request, encounter, _first_error(form), anchor='tab-exame')
        data = form.cleaned_data
        try:
            if data['domain'] == ExaminationDomain.CRANIAL_NERVE:
                upsert_cranial_nerve_finding(
                    request.access_context, encounter, data['item_code'], data['side'] or 'not_applicable',
                    data['body_site'], data['state'], data['qualifier'], data['note'],
                )
            else:
                upsert_finding(
                    request.access_context, encounter, data['domain'], data['item_code'],
                    data['side'] or 'not_applicable', data['body_site'], data['state'],
                    data['numeric_value'], data['qualifier'], data['note'],
                )
        except Exception as exc:
            return _blocked(request, encounter, str(exc), anchor='tab-exame')
        messages.success(request, 'Achado registrado.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exame')


class ExamAxisSaveView(TenantScopedView):
    """Grava um eixo inteiro do roteiro de exame.

    O roteiro tem quase 400 itens; enviar tudo de uma vez a cada salvamento
    obrigaria o médico a esperar a página inteira. Um eixo por vez mantém o
    formulário pequeno e o que ele acabou de preencher é o que é gravado.
    """

    def post(self, request, encounter_id, axis):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-exame')
        template = resolve_template(
            request.access_context.tenant_id, request.access_context.membership_id,
        )
        if template is None:
            return _blocked(
                request, encounter,
                'Nenhum roteiro de exame publicado nesta organização.', anchor='tab-exame',
            )
        saved, removed = save_axis(request.access_context, encounter, template, axis, request.POST)
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.exam_axis_saved',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'axis': axis, 'saved': saved, 'removed': removed},
        )
        messages.success(request, f'Exame salvo: {saved} item(ns) registrado(s) neste eixo.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exame')


class ExamGroupNormalView(TenantScopedView):
    """Marca (ou desfaz) "tudo normal" num grupo do roteiro.

    Ação deliberada, exigida explicitamente pelo PRD (11.1): nunca é
    pré-selecionada, diz quantos itens foram marcados e quantos foram
    ignorados por já terem registro manual, e pode ser desfeita enquanto o
    atendimento não estiver finalizado.
    """

    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-exame')
        template = resolve_template(
            request.access_context.tenant_id, request.access_context.membership_id,
        )
        if template is None:
            return _blocked(
                request, encounter,
                'Nenhum roteiro de exame publicado nesta organização.', anchor='tab-exame',
            )

        path = (request.POST.get('path') or '').strip()
        if not path:
            return _blocked(request, encounter, 'Grupo não informado.', anchor='tab-exame')
        undo = request.POST.get('undo') == '1'

        if undo:
            removed = undo_group_normal(request.access_context, encounter, template, path)
            outcome = {'removed': removed}
            messages.success(request, f'Marcação em bloco desfeita: {removed} item(ns) removido(s).')
        else:
            marked, skipped = mark_group_normal(
                request.access_context, encounter, template, path,
            )
            outcome = {'marked': marked, 'skipped': skipped}
            text = f'{marked} item(ns) marcado(s) como normal.'
            if skipped:
                text += f' {skipped} preservado(s) por já terem registro próprio.'
            messages.success(request, text)

        record_audit_event(
            request.user, request.access_context.tenant_id,
            'clinical.exam_group_normal_undone' if undo else 'clinical.exam_group_normal',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'path': path, **outcome},
        )
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exame')


class ScaleRecordView(TenantScopedView):
    """Aplica uma escala funcional ao atendimento.

    Vale para escala que não está amarrada a um ponto do roteiro — Barthel,
    Epworth, Pfeffer descrevem o paciente inteiro. Enviar sem nenhum item
    marcado remove a escala do atendimento.
    """

    def post(self, request, encounter_id, code):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-exame')
        scale = get_object_or_404(
            ExamScale, tenant_id=request.access_context.tenant_id, code=code, active=True,
        )
        finding, removed = record_scale(request.access_context, encounter, scale, request.POST)
        if finding is None:
            messages.success(request, f'{scale.name} removida do atendimento.')
            detail = {'scale': scale.code, 'removed': removed}
        else:
            summary = f'{scale.name}: {finding.qualifier}' if finding.qualifier else f'{scale.name} registrada.'
            messages.success(request, summary)
            detail = {
                'scale': scale.code,
                'total': finding.value_json.get('total'),
                'complete': finding.value_json.get('complete'),
            }
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.scale_recorded',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata=detail,
        )
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exame')


class DiagnosisCreateView(TenantScopedView):
    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.')
        form = DiagnosisForm(request.POST)
        if not form.is_valid():
            return _blocked(request, encounter, _first_error(form), anchor='tab-hipoteses')
        EncounterDiagnosis.objects.create(
            tenant_id=request.access_context.tenant_id, encounter=encounter,
            diagnosis_code_id=form.cleaned_data['diagnosis_code_id'],
            code_snapshot=form.cleaned_data['code_snapshot'],
            description_snapshot=form.cleaned_data['description_snapshot'],
            certainty=form.cleaned_data['certainty'], rank=form.cleaned_data['rank'],
            physician_note=form.cleaned_data['physician_note'],
        )
        return redirect('clinical:detail', encounter_id=encounter.id)


class CarryForwardReviewView(TenantScopedView):
    def post(self, request, encounter_id, item_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        item = get_object_or_404(encounter.carry_forward_items, id=item_id)
        action = request.POST.get('action')
        if action not in ('accepted', 'edited', 'rejected'):
            raise Http404
        membership = _doctor_membership(request)
        cf.review_carry_forward_item(item, action, membership.id if membership else None)
        return redirect('clinical:detail', encounter_id=encounter.id)


class FinalizeEncounterView(TenantScopedView):
    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        membership = _doctor_membership(request)
        if membership is None:
            raise Http404
        try:
            finalization.finalize_encounter(request.access_context, encounter, membership)
        except finalization.FinalizationError as exc:
            return _blocked(request, encounter, str(exc))
        messages.success(request, 'Atendimento finalizado. O registro agora é imutável.')
        return redirect('clinical:detail', encounter_id=encounter.id)


class AmendmentCreateView(TenantScopedView):
    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        membership = _doctor_membership(request)
        if membership is None:
            raise Http404
        form = AmendmentForm(request.POST)
        if not form.is_valid():
            return _blocked(request, encounter, _first_error(form), anchor='tab-adendos')
        try:
            finalization.add_amendment(
                request.access_context, encounter, membership,
                form.cleaned_data['reason'], form.cleaned_data['text'],
            )
        except finalization.FinalizationError as exc:
            return _blocked(request, encounter, str(exc), anchor='tab-adendos')
        messages.success(request, 'Adendo registrado.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-adendos')


class EncounterSummaryView(TenantScopedView):
    """Resumo do caso em uma página, para leitura e impressão.

    Página própria e não um modal: o que se quer é levar o caso para fora da
    tela — imprimir, salvar em PDF pelo diálogo do navegador, ler ao lado do
    paciente. Sai sem menu, sem botões e sem formulário, com o cabeçalho de
    identificação que um documento impresso precisa ter.

    Não é documento assinado: é uma leitura do prontuário. Receita,
    relatório e encaminhamento continuam saindo pelo fluxo de documentos
    médicos, com assinatura digital.
    """

    def get(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        findings = list(
            encounter.examination_findings.select_related('template_node')
            .order_by('domain', 'item_code', 'side')
        )
        exam_results = list(
            encounter.exam_results.prefetch_related('lab_values').order_by('-performed_on', 'name')
        )
        for result in exam_results:
            values = list(result.lab_values.all())
            result.values_out = [v for v in values if v.flag in ('low', 'high', 'abnormal')]
            result.values_in_count = sum(1 for v in values if v.flag == 'normal')
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.encounter_summary_viewed',
            object_type='encounter', object_id=encounter.id, outcome='success',
        )
        return render(request, 'clinical/summary.html', {
            'encounter': encounter,
            'patient': encounter.patient,
            'findings_by_domain': group_findings_by_domain(findings),
            'findings_count': len(findings),
            'medications': list(encounter.medications.all()),
            'exam_results': exam_results,
            'diagnoses': encounter.diagnoses.all().order_by('rank'),
            'amendments': encounter.amendments.all().order_by('authored_at'),
            'printed_at': timezone.now(),
            'printed_by': request.user.get_full_name() or request.user.email,
        })


class MedicationCreateView(TenantScopedView):
    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-medicacoes')
        form = MedicationForm(request.POST)
        if not form.is_valid():
            return _blocked(request, encounter, _first_error(form), anchor='tab-medicacoes')
        medication = form.save(commit=False)
        medication.tenant_id = request.access_context.tenant_id
        medication.encounter = encounter
        medication.save()
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.medication_added',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'name': medication.name},
        )
        messages.success(request, f'{medication.name} incluído nas medicações em uso.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-medicacoes')


class MedicationDeleteView(TenantScopedView):
    def post(self, request, encounter_id, medication_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-medicacoes')
        medication = get_object_or_404(
            Medication, tenant_id=request.access_context.tenant_id, encounter=encounter, id=medication_id,
        )
        name = medication.name
        medication.delete()
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.medication_removed',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'name': name},
        )
        messages.success(request, f'{name} removido das medicações em uso.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-medicacoes')


class ExamResultCreateView(TenantScopedView):
    """Registra um resultado de exame e, se houver PDF, pede a leitura à IA.

    O arquivo segue o mesmo caminho de qualquer anexo — quarentena,
    verificação de malware, publicação — e a leitura pela IA só começa
    depois disso. Nada do que a IA ler entra no prontuário sem revisão.
    """

    def post(self, request, encounter_id):
        from documents.models import AttachmentClassification
        from documents.storage import QuotaExceeded, receive_upload
        from documents.tasks import scan_attachment
        from documents.validators import UploadRejected
        from tenancy.models import Tenant

        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-exames')
        form = ExamResultForm(request.POST, request.FILES)
        if not form.is_valid():
            return _blocked(request, encounter, _first_error(form), anchor='tab-exames')

        exam_result = form.save(commit=False)
        exam_result.tenant_id = request.access_context.tenant_id
        exam_result.encounter = encounter
        exam_result.patient = encounter.patient

        uploaded = form.cleaned_data.get('report_file')
        attachment = None
        if uploaded is not None:
            tenant = Tenant.objects.get(id=request.access_context.tenant_id)
            try:
                attachment = receive_upload(
                    request.access_context, tenant, encounter.patient, request.user,
                    uploaded.read(), uploaded.name, AttachmentClassification.CLINICAL,
                    encounter=encounter, document_date=form.cleaned_data.get('performed_on'),
                )
            except (UploadRejected, QuotaExceeded) as exc:
                return _blocked(request, encounter, str(exc), anchor='tab-exames')
            exam_result.attachment = attachment

        exam_result.save()
        if attachment is not None:
            scan_attachment.delay(str(attachment.id))
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.exam_result_added',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'name': exam_result.name, 'has_report': attachment is not None},
        )

        if attachment is not None and form.cleaned_data.get('run_extraction'):
            from ai.context import AIAuthorizationDenied
            from ai.extraction import ExtractionUnavailable, request_extraction

            try:
                job = request_extraction(request.access_context, exam_result)
            except (ExtractionUnavailable, AIAuthorizationDenied) as exc:
                messages.warning(request, f'Exame registrado, mas a leitura por IA não foi iniciada: {exc}')
                return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exames')
            if job.status == 'disabled':
                messages.warning(
                    request,
                    f'{exam_result.name} registrado. A leitura por IA está desligada nesta '
                    'instalação, então o laudo ficou anexado para transcrição manual.',
                )
            else:
                messages.success(
                    request,
                    f'{exam_result.name} registrado. A IA está lendo o laudo; o rascunho aparece '
                    'aqui para sua revisão em instantes.',
                )
        else:
            messages.success(request, f'{exam_result.name} registrado.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exames')


def _exam_result_or_404(request, encounter, exam_result_id):
    return get_object_or_404(
        ExamResult.objects.select_related('attachment'),
        tenant_id=request.access_context.tenant_id, encounter=encounter, id=exam_result_id,
    )


class ExamResultDeleteView(TenantScopedView):
    def post(self, request, encounter_id, exam_result_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-exames')
        exam_result = _exam_result_or_404(request, encounter, exam_result_id)
        name = exam_result.name
        # O anexo não é apagado junto: ele fica no prontuário do paciente,
        # com o histórico de retenção próprio. Remover o registro do exame
        # não é motivo para descartar o documento original.
        exam_result.delete()
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.exam_result_removed',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'name': name},
        )
        messages.success(request, f'{name} removido dos resultados de exame.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exames')


class LabValueCreateView(TenantScopedView):
    def post(self, request, encounter_id, exam_result_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-exames')
        exam_result = _exam_result_or_404(request, encounter, exam_result_id)
        form = LabValueForm(request.POST)
        if not form.is_valid():
            return _blocked(request, encounter, _first_error(form), anchor='tab-exames')
        value = form.save(commit=False)
        value.tenant_id = request.access_context.tenant_id
        value.exam_result = exam_result
        value.order = exam_result.lab_values.count()
        value.source = 'manual'
        value.save()
        messages.success(request, f'{value.analyte}: {value.get_flag_display().lower()}.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exames')


class LabValueDeleteView(TenantScopedView):
    def post(self, request, encounter_id, value_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-exames')
        value = get_object_or_404(
            LabValue, tenant_id=request.access_context.tenant_id,
            exam_result__encounter=encounter, id=value_id,
        )
        analyte = value.analyte
        value.delete()
        messages.success(request, f'{analyte} removido.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exames')


class ExamResultExtractView(TenantScopedView):
    """Pede (ou repete) a leitura do laudo pela IA."""

    def post(self, request, encounter_id, exam_result_id):
        from ai.context import AIAuthorizationDenied
        from ai.extraction import ExtractionUnavailable, request_extraction

        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-exames')
        exam_result = _exam_result_or_404(request, encounter, exam_result_id)
        try:
            job = request_extraction(request.access_context, exam_result)
        except (ExtractionUnavailable, AIAuthorizationDenied) as exc:
            return _blocked(request, encounter, str(exc), anchor='tab-exames')
        if job.status == 'disabled':
            messages.warning(request, 'A leitura por IA está desligada nesta instalação.')
        else:
            messages.success(request, 'Leitura do laudo solicitada. O rascunho aparece aqui para revisão.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exames')


class ExamResultDraftReviewView(TenantScopedView):
    """Aceita ou recusa o rascunho da IA para um resultado de exame.

    É este passo — e só ele — que transforma leitura de PDF em conteúdo do
    prontuário (RF-11-B). Enquanto ninguém aceita, o rascunho existe como
    artefato revisável e o registro segue vazio.
    """

    def post(self, request, encounter_id, exam_result_id):
        from ai.extraction import ExtractionUnavailable, accept_draft, latest_draft, reject_draft

        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-exames')
        exam_result = _exam_result_or_404(request, encounter, exam_result_id)
        artifact = latest_draft(exam_result)
        if artifact is None:
            return _blocked(request, encounter, 'Não há rascunho para revisar.', anchor='tab-exames')

        membership = _doctor_membership(request)
        if membership is None:
            return _blocked(
                request, encounter,
                'Só um médico com vínculo ativo pode revisar o rascunho da IA.', anchor='tab-exames',
            )
        action = request.POST.get('action')
        try:
            if action == 'accept':
                accept_draft(artifact, exam_result, membership, request.access_context.user_id)
                messages.success(request, 'Rascunho revisado e incorporado ao prontuário.')
            elif action == 'reject':
                reject_draft(
                    artifact, exam_result, membership, request.access_context.user_id,
                    request.POST.get('reason', ''),
                )
                messages.success(request, 'Rascunho recusado. Nada foi gravado no prontuário.')
            else:
                return _blocked(request, encounter, 'Ação inválida.', anchor='tab-exames')
        except ExtractionUnavailable as exc:
            return _blocked(request, encounter, str(exc), anchor='tab-exames')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exames')


class DiagnosticSupportRequestView(TenantScopedView):
    def post(self, request, encounter_id):
        from ai.context import AIAuthorizationDenied
        from ai.services import request_diagnostic_support

        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        try:
            job = request_diagnostic_support(request.access_context, encounter)
        except AIAuthorizationDenied as exc:
            return _blocked(request, encounter, str(exc), anchor='tab-hipoteses')
        if job.status == 'disabled':
            messages.warning(request, 'O apoio por IA está desligado nesta instalação.')
        elif job.status == 'succeeded':
            messages.info(request, 'O caso não mudou desde a última análise; o resultado abaixo é dela.')
        else:
            messages.success(
                request,
                'Análise solicitada. As hipóteses aparecem aqui por nível de prioridade, '
                'para sua avaliação.',
            )
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-hipoteses')


class DiagnosisFromSupportView(TenantScopedView):
    """Leva uma hipótese sugerida para a lista do prontuário.

    Entra sempre como `suspected` e com a nota dizendo que a sugestão veio
    da IA e foi aceita por quem clicou: a hipótese registrada é do médico, e
    o prontuário guarda de onde ela partiu.
    """

    def post(self, request, encounter_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(request, encounter, 'Atendimento finalizado.', anchor='tab-hipoteses')
        label = (request.POST.get('label') or '').strip()
        if not label:
            return _blocked(request, encounter, 'Hipótese não informada.', anchor='tab-hipoteses')
        rank = encounter.diagnoses.count() + 1
        EncounterDiagnosis.objects.create(
            tenant_id=request.access_context.tenant_id, encounter=encounter,
            code_snapshot='', description_snapshot=label[:4000],
            certainty='suspected', rank=rank,
            physician_note='Sugestão da IA revisada e aceita pelo médico.',
        )
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.diagnosis_from_ai',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'label': label[:255]},
        )
        messages.success(request, f'“{label}” registrada como hipótese.')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-hipoteses')


class FindingDeleteView(TenantScopedView):
    """Remove um item registrado no exame, a partir do grid.

    Existe porque desmarcar no roteiro só funciona para item que ainda está
    no roteiro em vigor: achado do catálogo avulso, escala aplicada e item de
    uma versão anterior do roteiro não têm onde ser desmarcados. O grid é o
    lugar em que todos aparecem, então é dele que se apaga.
    """

    def post(self, request, encounter_id, finding_id):
        encounter = selectors.get_encounter_or_404(request.access_context, encounter_id)
        if not encounter.is_editable():
            return _blocked(
                request, encounter,
                'Atendimento finalizado: o exame não pode mais ser alterado.',
                anchor='tab-exame',
            )
        finding = get_object_or_404(
            ExaminationFinding,
            tenant_id=request.access_context.tenant_id,
            encounter=encounter, id=finding_id,
        )
        label = finding.qualifier or finding.get_state_display()
        item = finding.item_code
        finding.delete()
        record_audit_event(
            request.user, request.access_context.tenant_id, 'clinical.exam_finding_deleted',
            object_type='encounter', object_id=encounter.id, outcome='success',
            integrity_metadata={'item_code': item},
        )
        messages.success(request, f'Item removido do exame ({label}).')
        return redirect(f'{reverse("clinical:detail", args=[encounter.id])}#tab-exame')
