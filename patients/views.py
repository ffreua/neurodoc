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


class PatientDetailView(TenantScopedView):
    def get(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)
        bmi = compute_bmi(patient)
        age = age_at(patient.birth_date)
        return render(request, 'patients/detail.html', {
            'patient': patient, 'bmi': bmi, 'age': age,
            'contact_form': PatientContactForm(),
            'coverage_form': PatientCoverageForm(tenant_id=request.access_context.tenant_id),
        })


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
    def post(self, request, patient_id):
        patient = selectors.get_patient_or_404(request.access_context, patient_id)
        patient.status = PatientStatus.ARCHIVED
        patient.archived_at = timezone.now()
        patient.archived_reason = request.POST.get('reason', '')[:255]
        patient.row_version += 1
        patient.save(update_fields=['status', 'archived_at', 'archived_reason', 'row_version', 'updated_at'])
        record_audit_event(
            request.user, request.access_context.tenant_id, 'patients.patient_archived', object_type='patient',
            object_id=patient.id, outcome='success',
        )
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
        bmi = compute_bmi(patient)
        age = age_at(patient.birth_date)
        return render(request, 'patients/detail.html', {
            'patient': patient, 'bmi': bmi, 'age': age, 'contact_form': form,
            'coverage_form': PatientCoverageForm(tenant_id=request.access_context.tenant_id),
        })


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
        bmi = compute_bmi(patient)
        age = age_at(patient.birth_date)
        return render(request, 'patients/detail.html', {
            'patient': patient, 'bmi': bmi, 'age': age, 'coverage_form': form,
            'contact_form': PatientContactForm(),
        })


class CepLookupView(TenantScopedView):
    def get(self, request):
        cep = request.GET.get('cep', '')
        address = lookup_cep(cep)
        if address is None:
            return JsonResponse({'found': False})
        return JsonResponse({'found': True, 'address': address})
