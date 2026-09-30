"""Retorno previsto: criar, resolver e avisar.

O médico fecha o atendimento e escolhe "volta em N meses". Até aqui essa
decisão morria ali — ninguém a registrava, ninguém a cobrava, e o paciente
crônico sumia até a próxima crise. Numa especialidade feita de seguimento
longo isso é paciente perdido, não comodidade perdida.

Este módulo é a regra; a tela da secretária e a tarefa diária são
consumidores dele.
"""
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event

from .models import ReturnStatus, ScheduledReturn

#: Quantos dias antes do retorno o paciente é avisado.
#:
#: Vinte, e não sete: quem precisa de retorno em seis meses costuma ter
#: agenda cheia e o médico também. Uma semana de antecedência descobre que
#: não há vaga; três semanas ainda dão tempo de encaixar.
#:
#: Não é configurável por clínica de propósito. Um prazo por clínica
#: multiplicaria os casos da tarefa diária sem que ninguém soubesse
#: responder qual é o prazo certo -- e o prazo certo é "com folga para
#: achar vaga", que vinte dias cumprem em qualquer agenda.
AVISO_DIAS_ANTES = 20

#: Intervalos que a tela oferece. Meses, porque é como a conduta é
#: pensada e dita: "volta em três meses", nunca "volta em 90 dias".
INTERVALOS_MESES = [1, 2, 3, 4, 6, 9, 12, 18, 24]


def _somar_meses(origem, meses):
    """Soma meses a uma data, sem estourar no fim do mês.

    31/01 mais um mês é 28/02, e não 03/03. `timedelta` de 30 dias erraria
    sistematicamente, e a diferença aparece como retorno previsto para o
    dia errado -- pequeno em um caso, constante em todos.
    """
    total = origem.month - 1 + meses
    ano = origem.year + total // 12
    mes = total % 12 + 1
    ultimo_dia = [31, 29 if (ano % 4 == 0 and (ano % 100 != 0 or ano % 400 == 0)) else 28,
                  31, 30, 31, 30, 31, 31, 30, 31, 30, 31][mes - 1]
    return date(ano, mes, min(origem.day, ultimo_dia))


@transaction.atomic
def agendar_retorno(context, encounter, meses, actor_membership):
    """Registra o retorno previsto de um atendimento.

    Idempotente por atendimento: finalizar duas vezes -- ou reenviar o
    formulário -- não cria dois retornos para a mesma consulta. O que a
    segunda chamada faz é **atualizar** o prazo, porque a intenção mais
    recente é a que vale.
    """
    if not meses:
        return None
    base = timezone.localtime(encounter.occurred_at).date()
    vencimento = _somar_meses(base, int(meses))

    registro, criado = ScheduledReturn.objects.update_or_create(
        tenant_id=context.tenant_id, origin_encounter=encounter,
        defaults={
            'patient': encounter.patient,
            'physician_membership': encounter.physician_membership,
            'interval_months': int(meses),
            'due_on': vencimento,
            'status': ReturnStatus.PENDING,
        },
    )
    record_audit_event(
        actor_membership.user_id, context.tenant_id,
        'scheduling.return_scheduled' if criado else 'scheduling.return_rescheduled',
        object_type='scheduled_return', object_id=registro.id, outcome='success',
        integrity_metadata={'due_on': vencimento.isoformat(), 'months': int(meses)},
    )
    return registro


def fila(tenant_id, physician_membership_id=None, incluir_resolvidos=False):
    """A fila da secretária: pendentes primeiro, atrasados no topo.

    Ordenada por data de vencimento, que é a ordem em que se deve ligar --
    quem já passou da data vem antes de quem vence na semana que vem.
    """
    consulta = (
        ScheduledReturn.objects
        .filter(tenant_id=tenant_id)
        .select_related('patient', 'physician_membership__user', 'appointment')
    )
    if not incluir_resolvidos:
        consulta = consulta.filter(status=ReturnStatus.PENDING)
    if physician_membership_id:
        consulta = consulta.filter(physician_membership_id=physician_membership_id)
    return consulta.order_by('due_on', 'patient__full_name')


@transaction.atomic
def resolver(context, registro, status, actor_membership, note='', appointment=None):
    """Tira uma linha da fila: agendada, concluída ou dispensada.

    `note` importa mais do que parece. Sem ela a lista devolve o mesmo nome
    amanhã, e quem ligou ontem não tem como dizer "já tentei três vezes, o
    telefone não atende" -- a informação fica com a pessoa, não com a
    clínica.
    """
    registro.status = status
    registro.resolved_at = timezone.now()
    registro.resolved_by = actor_membership
    if note:
        registro.note = note[:255]
    if appointment is not None:
        registro.appointment = appointment
    registro.full_clean()
    registro.save()
    record_audit_event(
        actor_membership.user_id, context.tenant_id, 'scheduling.return_resolved',
        object_type='scheduled_return', object_id=registro.id, outcome='success',
        integrity_metadata={'status': status},
    )
    return registro


def a_avisar(hoje=None):
    """Retornos cujo aviso vence hoje, em toda a instalação.

    O corte é `due_on <= hoje + 20 dias` e **não** `== hoje + 20`: a tarefa
    pode não ter rodado ontem -- servidor reiniciado, fila parada -- e a
    igualdade deixaria aquele dia sem aviso para sempre, sem nada
    indicando. Com `<=`, o dia perdido é recuperado na execução seguinte.

    `notified_at__isnull=True` é o que impede o mesmo paciente de receber
    vinte e-mails, um por dia, até a data chegar.
    """
    hoje = hoje or timezone.localdate()
    return (
        ScheduledReturn.objects
        .filter(
            status=ReturnStatus.PENDING,
            notified_at__isnull=True,
            due_on__lte=hoje + timedelta(days=AVISO_DIAS_ANTES),
            due_on__gte=hoje,
        )
        .select_related('patient', 'physician_membership__user', 'tenant')
        .order_by('due_on')
    )
