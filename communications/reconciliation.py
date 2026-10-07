from django.utils import timezone

from .models import Delivery, DeliveryAttempt, DeliveryAttemptOutcome, DeliveryChannel, DeliveryStatus
from .smsdev import SmsChannelDisabled, SmsSendFailed, check_delivery

# Baseline polling cadence per PRD section 12.3: 1, 5, 15, 60 minutes, then
# administrative review -- never an automatic blind resend.
POLL_OFFSETS_MINUTES = [1, 5, 15, 60]


def _poll_count(delivery):
    return delivery.attempts.filter(provider_code='dlr_poll').count()


def _record_poll(delivery, outcome, sanitized_error=''):
    DeliveryAttempt.objects.create(
        tenant=delivery.tenant, delivery=delivery, attempt_number=delivery.attempts.count() + 1,
        started_at=timezone.now(), ended_at=timezone.now(), outcome=outcome,
        provider_code='dlr_poll', sanitized_error=sanitized_error[:255],
    )


def _schedule_next_or_give_up(delivery, poll_count):
    if poll_count + 1 >= len(POLL_OFFSETS_MINUTES):
        delivery.status = DeliveryStatus.UNKNOWN
        delivery.next_attempt_at = None
    else:
        delivery.next_attempt_at = timezone.now() + timezone.timedelta(minutes=POLL_OFFSETS_MINUTES[poll_count + 1])
    delivery.save(update_fields=['status', 'next_attempt_at'])


#: O que o `descricao` do DLR do SMSDEV diz, e o que isso significa para
#: nos. Conferido contra a conta real em 2026-10-06 -- ate entao este
#: modulo so conhecia formas "documentadas publicamente", e nenhuma delas
#: era a que o provedor manda.
#: `CLICADA` e prova mais forte que `RECEBIDA`: o destinatario abriu o
#: link que ia na mensagem. `ENVIADA` nao entra -- e saiu daqui e
#: ainda nao se sabe se chegou, que e o que `unknown` quer dizer.
_DLR_ENTREGUE = {'RECEBIDA', 'ENTREGUE', 'DELIVERED', 'CLICADA'}
_DLR_FALHOU = {'NAO RECEBIDA', 'NÃO RECEBIDA', 'ERRO', 'REJEITADO', 'FAILED',
               'NUMERO INVALIDO', 'NÚMERO INVÁLIDO', 'EXPIRADA'}


def _extract_situacao(result, provider_id):
    """O que o SMSDEV respondeu sobre **esta** mensagem.

    Reescrito em 2026-10-06 contra a conta real. O que havia aqui nunca
    casou com nada, e a razao estava escrita no proprio docstring: o
    esquema "nao pode ser homologado contra uma conta viva (P-03)", entao
    reconhecia formas supostas. Duas suposicoes, as duas erradas:

    - esperava um **dicionario** com a chave `items`; o SMSDEV responde
      uma **lista** no topo (`[{...}]`) quando se pergunta por varios
      ids, e um objeto solto quando se pergunta por um;
    - lia a entrega em `situacao`, que vale `OK` quando a **consulta**
      deu certo -- nao quando a mensagem chegou. A entrega esta em
      `descricao` (`RECEBIDA`) e em `codigo`.

    O efeito: dezessete mensagens ficaram em "sem confirmacao" para
    sempre, inclusive uma que o provedor dizia `RECEBIDA` pela VIVO desde
    02/10. A clinica nunca soube que o SMS chegou.

    O desconhecido continua sendo `unknown`, e nao `failed`: dizer que
    falhou uma mensagem que pode ter chegado faz a recepcao ligar para o
    paciente avisando de um horario que ele ja sabe.
    """
    if isinstance(result, dict):
        itens = result.get('items') if isinstance(result.get('items'), list) else [result]
    elif isinstance(result, list):
        itens = result
    else:
        return 'unknown'

    for item in itens:
        if not isinstance(item, dict):
            continue
        # Sem `id` no retorno, a consulta foi por um id so e a resposta e
        # sobre ele: casar por igualdade descartaria a resposta certa.
        if item.get('id') is not None and str(item.get('id')) != str(provider_id):
            continue
        descricao = str(item.get('descricao', '')).strip().upper()
        if descricao in _DLR_ENTREGUE:
            return 'delivered'
        if descricao in _DLR_FALHOU:
            return 'failed'
    return 'unknown'


def reconcile_pending_sms():
    """Run every minute (Celery beat). Never retries blindly forever: each
    delivery gets exactly the 1/5/15/60-minute schedule, then stays
    UNKNOWN for a human to review.
    """
    due = Delivery.objects.filter(
        channel=DeliveryChannel.SMS, status=DeliveryStatus.ACCEPTED, next_attempt_at__lte=timezone.now(),
    )
    processed = 0
    for delivery in due:
        processed += 1
        poll_count = _poll_count(delivery)
        if not delivery.provider_id:
            delivery.status = DeliveryStatus.UNKNOWN
            delivery.next_attempt_at = None
            delivery.save(update_fields=['status', 'next_attempt_at'])
            continue
        try:
            result = check_delivery([delivery.provider_id])
        except (SmsChannelDisabled, SmsSendFailed) as exc:
            _record_poll(delivery, DeliveryAttemptOutcome.UNKNOWN, sanitized_error=exc.__class__.__name__)
            _schedule_next_or_give_up(delivery, poll_count)
            continue

        situacao = _extract_situacao(result, delivery.provider_id)
        if situacao == 'delivered':
            delivery.status = DeliveryStatus.DELIVERED
            delivery.next_attempt_at = None
            delivery.save(update_fields=['status', 'next_attempt_at'])
            _record_poll(delivery, DeliveryAttemptOutcome.DELIVERED)
        elif situacao == 'failed':
            delivery.status = DeliveryStatus.FAILED
            delivery.next_attempt_at = None
            delivery.save(update_fields=['status', 'next_attempt_at'])
            _record_poll(delivery, DeliveryAttemptOutcome.FAILED)
        else:
            _record_poll(delivery, DeliveryAttemptOutcome.UNKNOWN)
            _schedule_next_or_give_up(delivery, poll_count)
    return processed
