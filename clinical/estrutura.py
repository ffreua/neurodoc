"""Os três jeitos de abrir um atendimento, e qual deles sugerir (1.41).

Primeira consulta (estruturado com queixa e história), seguimento e retorno
(estruturado com evolução) e texto livre. Os três saem do mesmo botão
**Novo atendimento** da ficha e do prontuário, e o servidor traduz o que foi
clicado em `kind` + `estrutura` aqui, num lugar só.

**O valor do botão continua sendo `kind`.** `structured` e `free_text` são o
que as duas portas mandavam até a 1.40, e quem reenviar um formulário velho
(a aba aberta antes da publicação) continua abrindo o que pediu; o
seguimento é o valor novo, `seguimento`. Valor desconhecido cai na primeira
consulta — o prontuário completo, e errar para o lado de pedir mais
registro é o erro aceitável aqui.

**A sugestão só escolhe o botão principal; quem decide é o clique.** Ela
olha, nesta ordem:

1. o horário de hoje deste paciente com check-in, se houver um só — a
   secretária já disse ali se era primeira consulta, seguimento ou retorno;
2. o histórico: paciente que já tem atendimento finalizado nesta clínica
   está em seguimento; sem nenhum, é primeira consulta.

Procedimento e "outro" na agenda não dizem nada sobre a consulta e caem no
histórico. A sugestão nunca é gravada: quem abre um seguimento por engano
troca para primeira consulta na própria aba, enquanto nada foi escrito
(`trocar_estrutura`).
"""
from datetime import timedelta

from django.utils import timezone

from .models import Encounter, EncounterKind, EncounterStatus, EstruturaDoAtendimento

#: O que o botão manda → (kind, estrutura).
ABERTURAS = {
    'structured': (EncounterKind.STRUCTURED, EstruturaDoAtendimento.PRIMEIRA),
    'seguimento': (EncounterKind.STRUCTURED, EstruturaDoAtendimento.SEGUIMENTO),
    'free_text': (EncounterKind.FREE_TEXT, EstruturaDoAtendimento.PRIMEIRA),
}
ABERTURA_PADRAO = 'structured'

#: Tipo do horário na agenda → valor do botão.
_PELO_TIPO_DO_HORARIO = {
    'first_visit': 'structured',
    'follow_up': 'seguimento',
    'return_visit': 'seguimento',
}


def abertura(valor):
    """(kind, estrutura) do que veio no POST, com o padrão para o desconhecido."""
    return ABERTURAS.get(valor) or ABERTURAS[ABERTURA_PADRAO]


def abertura_sugerida(tenant_id, patient, membership_id=None):
    """O valor do botão principal de **Novo atendimento**. Ver o módulo."""
    from scheduling.models import Appointment, AppointmentStatus

    hoje = timezone.localdate()
    horarios = Appointment.objects.filter(
        tenant_id=tenant_id, patient=patient,
        status__in=[AppointmentStatus.CHECKED_IN, AppointmentStatus.IN_PROGRESS],
        starts_at__date__range=(hoje - timedelta(days=1), hoje + timedelta(days=1)),
    )
    if membership_id is not None:
        horarios = horarios.filter(physician_membership_id=membership_id)
    tipos = list(horarios.values_list('type', flat=True)[:2])
    if len(tipos) == 1 and tipos[0] in _PELO_TIPO_DO_HORARIO:
        return _PELO_TIPO_DO_HORARIO[tipos[0]]
    ja_atendido = Encounter.objects.filter(
        tenant_id=tenant_id, patient=patient, status=EncounterStatus.FINALIZED,
    ).exists()
    return 'seguimento' if ja_atendido else 'structured'


def primeira_consulta(encounter):
    """A primeira consulta estruturada deste paciente, para o seguimento lê-la.

    A mais recente com queixa ou história escrita, antes deste atendimento,
    de qualquer médico da clínica — é leitura, como a gaveta da consulta
    anterior. `None` quando não há (paciente que só teve texto livre, ou o
    histórico migrado).
    """
    from django.db.models import Q

    return (
        Encounter.objects
        .filter(
            tenant_id=encounter.tenant_id, patient_id=encounter.patient_id,
            kind=EncounterKind.STRUCTURED, occurred_at__lt=encounter.occurred_at,
        )
        .exclude(id=encounter.id)
        .filter(~Q(chief_complaint='') | ~Q(hpi=''))
        .only('id', 'occurred_at', 'chief_complaint', 'hpi', 'status')
        .order_by('-occurred_at')
        .first()
    )


class TrocaRecusada(Exception):
    """A troca esconderia texto já escrito, ou o atendimento está fechado."""


def trocar_estrutura(encounter, destino):
    """Troca primeira consulta ↔ seguimento enquanto nada se perde de vista.

    O erro que isto corrige é o da sugestão — o paciente que já veio mas
    hoje é consulta nova, ou o contrário. **Só troca se o campo que some
    está vazio:** a evolução escrita num seguimento não pode virar texto
    invisível numa primeira consulta (foi assim que as impressões, gravadas
    e não desenhadas, ficaram ocultas antes da 1.20). Com texto, a recusa
    diz o que fazer.
    """
    if not encounter.is_editable():
        raise TrocaRecusada('Atendimento finalizado: o tipo não muda mais.')
    if encounter.kind != EncounterKind.STRUCTURED:
        raise TrocaRecusada('O atendimento em texto livre não tem primeira consulta nem seguimento.')
    if destino not in EstruturaDoAtendimento.values:
        raise TrocaRecusada('Tipo de atendimento desconhecido.')
    if destino == encounter.estrutura:
        return False
    if destino == EstruturaDoAtendimento.PRIMEIRA and encounter.evolucao.strip():
        raise TrocaRecusada(
            'A evolução já tem texto e não aparece na primeira consulta. Apague-a (ou '
            'copie para a história da doença atual depois da troca) e tente de novo.'
        )
    if destino == EstruturaDoAtendimento.SEGUIMENTO and (
        encounter.chief_complaint.strip() or encounter.hpi.strip()
    ):
        raise TrocaRecusada(
            'A queixa principal ou a história já têm texto, e o seguimento não as mostra. '
            'Apague-as (ou leve o texto para a evolução depois da troca) e tente de novo.'
        )
    encounter.estrutura = destino
    encounter.row_version += 1
    encounter.save(update_fields=['estrutura', 'row_version', 'updated_at'])
    return True
