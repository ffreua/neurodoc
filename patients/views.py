from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.http import Http404, HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views import View

from audit.services import record_audit_event
from integrations.cep import lookup_cep

from . import selectors
from .contacts import create_contact
from .coverage import add_coverage, set_patient_coverage
from .forms import PatientContactForm, PatientCoverageForm, PatientForm
from .models import Patient, PatientStatus
from .observations import compute_bmi, age_at


class TenantScopedView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if request.access_context is None:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class PatientListView(TenantScopedView):
    def get(self, request):
        query = request.GET.get('q', '')
        page = request.GET.get('page', 1)
        patients = selectors.list_patients(request.access_context, query=query, page=page)
        return render(request, 'patients/list.html', {'patients': patients, 'query': query})


class PatientAutocompleteView(TenantScopedView):
    def get(self, request):
        query = request.GET.get('q', '')
        results = selectors.autocomplete_patients(request.access_context, query)
        return JsonResponse({'results': [
            {'id': str(p.id), 'full_name': p.full_name} for p in results
        ]})


class PatientCreateView(TenantScopedView):
    def get(self, request):
        form = PatientForm(tenant_id=request.access_context.tenant_id)
        return render(request, 'patients/form.html', {'form': form, 'duplicates': []})

    def post(self, request):
        form = PatientForm(request.POST, tenant_id=request.access_context.tenant_id)
        duplicates = []
        if form.is_valid():
            duplicates = selectors.find_possible_duplicates(
                request.access_context, form.cleaned_data['full_name'], form.cleaned_data.get('birth_date'),
            )
            if duplicates and not request.POST.get('confirm_duplicate'):
                return render(request, 'patients/form.html', {'form': form, 'duplicates': duplicates})
            coverage_data = form.coverage_data
            # Paciente e carteirinha entram juntos: um cadastro "por plano"
            # sem cobertura faria a cobrança cair em particular.
            with transaction.atomic():
                patient = form.save(commit=False)
                patient.tenant_id = request.access_context.tenant_id
                patient.full_clean()
                patient.save()
                if coverage_data:
                    set_patient_coverage(request.access_context, patient, **coverage_data)
            record_audit_event(
                request.user, request.access_context.tenant_id, 'patients.patient_created', object_type='patient',
                object_id=patient.id, outcome='success',
            )
            return redirect('patients:detail', patient_id=patient.id)
        return render(request, 'patients/form.html', {'form': form, 'duplicates': duplicates})


def _detail_context(request, patient, **overrides):
    """Contexto da tela do paciente, num lugar só.

    Três views renderizam `patients/detail.html` (abrir, adicionar contato,
    adicionar cobertura); montar o contexto em cada uma já tinha deixado
    duas delas sem o formulário da outra.
    """
    context = {
        'patient': patient,
        'bmi': compute_bmi(patient),
        'age': age_at(patient.birth_date),
        'contact_form': PatientContactForm(),
        'coverage_form': PatientCoverageForm(tenant_id=request.access_context.tenant_id),
        'recent_encounters': (
            patient.encounters
            .select_related('physician_membership__user')
            .order_by('-occurred_at')[:5]
        ),
    }
    context.update(overrides)
    return context


class PatientDetailView(TenantScopedView):
    def get(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)
        return render(request, 'patients/detail.html', _detail_context(request, patient))


class PatientUpdateView(TenantScopedView):
    def get(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)
        form = PatientForm(instance=patient, tenant_id=request.access_context.tenant_id)
        return render(request, 'patients/form.html', {'form': form, 'patient': patient, 'duplicates': []})

    def post(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)
        submitted_version = request.POST.get('row_version')
        if submitted_version and str(patient.row_version) != submitted_version:
            return HttpResponse('Conflict: this record changed since you opened it.', status=409)
        form = PatientForm(request.POST, instance=patient, tenant_id=request.access_context.tenant_id)
        if form.is_valid():
            updated = form.save(commit=False)
            updated.row_version += 1
            coverage_data = form.coverage_data
            with transaction.atomic():
                updated.full_clean()
                updated.save()
                if coverage_data:
                    set_patient_coverage(request.access_context, updated, **coverage_data)
            record_audit_event(
                request.user, request.access_context.tenant_id, 'patients.patient_updated', object_type='patient',
                object_id=updated.id, outcome='success',
            )
            return redirect('patients:detail', patient_id=updated.id)
        return render(request, 'patients/form.html', {'form': form, 'patient': patient, 'duplicates': []})


class PatientArchiveView(TenantScopedView):
    """Arquivar exige justificativa escrita e confirmação explícita.

    Arquivar tira o paciente da carteira ativa e dos indicadores; sem
    justificativa não há como saber depois por que aquele prontuário saiu
    de circulação, e sem confirmação o botão fica a um clique acidental de
    distância numa tela cheia de outros botões.
    """

    MIN_REASON = 5

    def post(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)
        if patient.status == PatientStatus.ARCHIVED:
            messages.warning(request, 'Este paciente já está arquivado.')
            return redirect('patients:detail', patient_id=patient.id)

        reason = (request.POST.get('reason') or '').strip()
        if request.POST.get('confirm') != 'archive':
            messages.error(request, 'Arquivamento não confirmado — nada foi alterado.')
            return redirect('patients:detail', patient_id=patient.id)
        if len(reason) < self.MIN_REASON:
            messages.error(
                request,
                'Informe o motivo do arquivamento (pelo menos '
                f'{self.MIN_REASON} caracteres) — nada foi alterado.',
            )
            return redirect('patients:detail', patient_id=patient.id)

        patient.status = PatientStatus.ARCHIVED
        patient.archived_at = timezone.now()
        patient.archived_reason = reason[:255]
        patient.row_version += 1
        patient.save(update_fields=['status', 'archived_at', 'archived_reason', 'row_version', 'updated_at'])
        record_audit_event(
            request.user, request.access_context.tenant_id, 'patients.patient_archived', object_type='patient',
            object_id=patient.id, outcome='success',
        )
        messages.success(request, f'{patient.full_name} foi arquivado.')
        return redirect('patients:detail', patient_id=patient.id)


class PatientContactCreateView(TenantScopedView):
    def post(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)
        form = PatientContactForm(request.POST)
        if form.is_valid():
            try:
                create_contact(request.access_context, patient, **form.cleaned_data)
            except Exception as exc:
                form.add_error(None, str(exc))
            else:
                record_audit_event(
                    request.user, request.access_context.tenant_id, 'patients.contact_added',
                    object_type='patient', object_id=patient.id, outcome='success',
                )
                return redirect('patients:detail', patient_id=patient.id)
        return render(request, 'patients/detail.html', _detail_context(request, patient, contact_form=form))


class PatientCoverageCreateView(TenantScopedView):
    def post(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)
        form = PatientCoverageForm(request.POST, tenant_id=request.access_context.tenant_id)
        if form.is_valid():
            try:
                add_coverage(
                    request.access_context, patient, form.cleaned_data['plan'].id,
                    member_number=form.cleaned_data['member_number'],
                    starts_on=form.cleaned_data['starts_on'], ends_on=form.cleaned_data.get('ends_on'),
                )
            except Exception as exc:
                form.add_error(None, str(exc))
            else:
                record_audit_event(
                    request.user, request.access_context.tenant_id, 'patients.coverage_added',
                    object_type='patient', object_id=patient.id, outcome='success',
                )
                return redirect('patients:detail', patient_id=patient.id)
        return render(request, 'patients/detail.html', _detail_context(request, patient, coverage_form=form))


class CepLookupView(TenantScopedView):
    def get(self, request):
        cep = request.GET.get('cep', '')
        address = lookup_cep(cep)
        if address is None:
            return JsonResponse({'found': False})
        return JsonResponse({'found': True, 'address': address})
