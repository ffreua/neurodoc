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
        # O número do prontuário entra na busca junto com nome, CPF e
        # contato: é por ele que se procura quando o laboratório liga
        # citando o número, ou quando se tem a pasta na mão. `lstrip('0')`
        # e a comparação com zeros à esquerda aceitam tanto "123" quanto
        # "000123" — quem dita o número raramente dita os zeros.
        digits = ''.join(c for c in query if c.isdigit())
        by_record = Q()
        if digits:
            by_record = Q(record_number=digits) | Q(record_number=digits.zfill(6))
        queryset = queryset.filter(
            Q(full_name__icontains=query)
            | Q(cpf=query)
            | Q(contacts__phone=query)
            | Q(contacts__email__iexact=query)
            | by_record
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
    digits = ''.join(c for c in query if c.isdigit())
    by_record = Q()
    if digits:
        by_record = Q(record_number=digits) | Q(record_number=digits.zfill(6))
    return (
        _base_queryset(context)
        .filter(status=PatientStatus.ACTIVE)
        .filter(Q(full_name__icontains=query) | by_record)
        .order_by('full_name')[:AUTOCOMPLETE_LIMIT]
    )


def find_possible_duplicates(context, full_name, birth_date=None):
    queryset = _base_queryset(context).filter(full_name__iexact=(full_name or '').strip())
    if birth_date:
        queryset = queryset.filter(birth_date=birth_date)
    return queryset
