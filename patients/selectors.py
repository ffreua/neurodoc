from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404

from tenancy.selectors import scope_to_tenant

from .models import Patient, PatientStatus

AUTOCOMPLETE_MIN_CHARS = 2
AUTOCOMPLETE_LIMIT = 20
PAGE_SIZE = 25


def _base_queryset(context):
    return scope_to_tenant(Patient.objects.all(), context)


def list_patients(context, query='', page=1, include_archived=False):
    queryset = _base_queryset(context)
    if not include_archived:
        queryset = queryset.filter(status=PatientStatus.ACTIVE)
    query = (query or '').strip()
    if query:
        queryset = queryset.filter(
            Q(full_name__icontains=query)
            | Q(cpf=query)
            | Q(contacts__phone=query)
            | Q(contacts__email__iexact=query)
        ).distinct()
    queryset = queryset.order_by('full_name', 'id')
    return Paginator(queryset, PAGE_SIZE).get_page(page)


def get_patient_or_404(context, patient_id):
    patient = _base_queryset(context).filter(id=patient_id).first()
    if patient is None:
        raise Http404
    return patient


def autocomplete_patients(context, query):
    query = (query or '').strip()
    if len(query) < AUTOCOMPLETE_MIN_CHARS:
        return Patient.objects.none()
    return (
        _base_queryset(context)
        .filter(status=PatientStatus.ACTIVE, full_name__icontains=query)
        .order_by('full_name')[:AUTOCOMPLETE_LIMIT]
    )


def find_possible_duplicates(context, full_name, birth_date=None):
    queryset = _base_queryset(context).filter(full_name__iexact=(full_name or '').strip())
    if birth_date:
        queryset = queryset.filter(birth_date=birth_date)
    return queryset
