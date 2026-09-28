from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404

from tenancy.selectors import scope_to_tenant

from .models import Patient, PatientStatus, RegistrationStage

AUTOCOMPLETE_MIN_CHARS = 2
AUTOCOMPLETE_LIMIT = 20
PAGE_SIZE = 25

#: Quantos pacientes a busca rápida do topo mostra. Seis cabem na tela sem
#: rolagem e sem esconder o rodapé com as teclas; mais que isso vira lista,
#: e para lista existe a tela de pacientes.
BUSCA_RAPIDA_LIMITE = 6


def _base_queryset(context):
    return scope_to_tenant(Patient.objects.all(), context)


def _filtro_de_busca(query):
    """O que "procurar por isto" significa, num lugar só.

    Nome, CPF, telefone, e-mail e número do prontuário. O número entra
    junto porque é por ele que se procura quando o laboratório liga
    citando o número, ou quando se tem a pasta na mão; `zfill` aceita
    tanto "123" quanto "000123", já que quem dita o número raramente dita
    os zeros.

    Existe como função porque a lista de pacientes e a busca rápida do
    topo fazem a **mesma** pergunta. Duas cópias divergiriam no primeiro
    ajuste — e a divergência apareceria como "achei pela lista e não achei
    pela busca", que é o tipo de defeito que ninguém reporta e todo mundo
    contorna.
    """
    query = (query or '').strip()
    if not query:
        return Q()
    digits = ''.join(c for c in query if c.isdigit())
    by_record = Q()
    if digits:
        by_record = Q(record_number=digits) | Q(record_number=digits.zfill(6))
    return (
        Q(full_name__icontains=query)
        | Q(cpf=query)
        | Q(cpf=digits)
        | Q(contacts__phone=query)
        | Q(contacts__phone=digits)
        | Q(contacts__email__iexact=query)
        | by_record
    )


def busca_rapida(context, query, limite=BUSCA_RAPIDA_LIMITE):
    """Poucos pacientes, para a busca do topo (Ctrl+K).

    Só ativos: a busca do topo serve ao atendimento do dia, e quem procura
    um arquivado está fazendo outra coisa — tem a lista de pacientes, com
    filtro e paginação, para isso.

    O escopo por inquilino vem de `_base_queryset`, que é
    `scope_to_tenant`. Não há caminho aqui que devolva paciente de outra
    clínica: a consulta nasce filtrada, e o filtro de busca só estreita.
    """
    query = (query or '').strip()
    if len(query) < AUTOCOMPLETE_MIN_CHARS:
        return Patient.objects.none()
    return (
        _base_queryset(context)
        .filter(status=PatientStatus.ACTIVE)
        .filter(_filtro_de_busca(query))
        .distinct()
        .order_by('full_name', 'id')[:limite]
    )


def list_patients(context, query='', page=1, include_archived=False):
    # O agendamento rapido cria uma linha de paciente para que o horario
    # tenha dono, mas ela ainda e so nome e contato. Exibi-la aqui antes de
    # a recepcao confirmar a ficha fazia um telefonema parecer cadastro.
    # O autocomplete da agenda continua separado e inclui o preliminar para
    # que uma segunda marcacao reutilize a mesma pessoa em vez de duplica-la.
    queryset = _base_queryset(context).filter(registration_stage=RegistrationStage.COMPLETE)
    if not include_archived:
        queryset = queryset.filter(status=PatientStatus.ACTIVE)
    query = (query or '').strip()
    if query:
        # Nome, CPF, contato e número do prontuário — ver `_filtro_de_busca`,
        # que é o mesmo critério da busca rápida do topo.
        queryset = queryset.filter(_filtro_de_busca(query)).distinct()
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
