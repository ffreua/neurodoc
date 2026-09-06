from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib import messages
from django.forms import modelform_factory
from django.http import Http404, HttpResponse, JsonResponse
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
    mark_group_normal, record_scale, save_axis, scale_item_code, undo_group_normal,
)
from exams.selectors import build_tree, resolve_template

from .examination import group_findings_by_domain, upsert_finding
from .forms import AmendmentForm, DiagnosisForm, EncounterForm, FindingForm
from .models import (
    Encounter, EncounterDiagnosis, EncounterStatus, ExaminationDomain, ExaminationFinding,
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
        pending_items = encounter.carry_forward_items.filter(review_action='pending').select_related('source_encounter')
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
        })


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
