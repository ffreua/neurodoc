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
            # Com a chave de **quem enviou**. O id da mensagem existe na conta
            # da clinica que a mandou; perguntado com a chave da instalacao,
            # o SMSDEV nao o conhece, e a entrega real terminava "sem
            # confirmacao" (auditoria de 2026-10-09, ND-1121-006). So nao
            # aparecia porque, ate aqui, a chave propria e a da instalacao
            # eram a mesma conta.
            result = check_delivery([delivery.provider_id], tenant_id=delivery.tenant_id)
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


# --------------------------------------------------------------- WhatsApp
#
# A situação da mensagem de WhatsApp chega pelo aviso de status da Twilio
# (`communications.webhooks`), que a Twilio não garante entregar nem em
# ordem. A consulta abaixo cobre o aviso que não veio — inclusive o que foi
# recusado por assinatura na janela em que a clínica trocou o Auth Token na
# Twilio e ainda não aqui. Duas consultas, e depois "Sem confirmação" para
# alguém olhar, como no SMS: nunca um reenvio às cegas.

WHATSAPP_PRIMEIRA_CONSULTA_MINUTOS = 15
WHATSAPP_CONSULTAS_MINUTOS = [WHATSAPP_PRIMEIRA_CONSULTA_MINUTOS, 60]


def aplicar_status_whatsapp(tenant_id, message_sid, status_twilio, codigo_erro='', origem='wa_status'):
    """Aplica a situação da Twilio à entrega **desta clínica** com este SID.

    Só avança: aceita (ou sem confirmação) vira entregue ou falhou, por um
    `UPDATE` condicional. O aviso repetido, o fora de ordem ("sent" depois
    de "delivered") e dois avisos ao mesmo tempo não regridem nem duplicam
    nada — só quem fizer a transição grava a tentativa. Devolve se mudou.
    """
    from .whatsapp_twilio import STATUS_ENTREGUE, STATUS_FALHOU, traduzir_erro

    if status_twilio in STATUS_ENTREGUE:
        novo, resultado, texto = DeliveryStatus.DELIVERED, DeliveryAttemptOutcome.DELIVERED, ''
    elif status_twilio in STATUS_FALHOU:
        novo, resultado = DeliveryStatus.FAILED, DeliveryAttemptOutcome.FAILED
        texto = traduzir_erro(None, {'code': codigo_erro})[1] if codigo_erro else ''
    else:
        return False
    alvo = Delivery.objects.filter(
        tenant_id=tenant_id, channel=DeliveryChannel.WHATSAPP, provider_id=message_sid,
    )
    mudou = alvo.filter(
        status__in=[DeliveryStatus.ACCEPTED, DeliveryStatus.UNKNOWN],
    ).update(status=novo, next_attempt_at=None)
    if mudou:
        delivery = alvo.first()
        codigo = f'{origem}:{status_twilio}' + (f':{codigo_erro}' if codigo_erro else '')
        DeliveryAttempt.objects.create(
            tenant=delivery.tenant, delivery=delivery,
            attempt_number=delivery.attempts.count() + 1,
            started_at=timezone.now(), ended_at=timezone.now(), outcome=resultado,
            provider_code=codigo[:100], sanitized_error=texto[:255],
        )
    return bool(mudou)


def reconcile_pending_whatsapp():
    """Consulta na Twilio as mensagens aceitas que não tiveram aviso de status."""
    from .models import WhatsAppTwilio
    from .whatsapp_twilio import FalhaDeTransporte, WhatsAppIndisponivel, WhatsAppRecusado, consultar_mensagem

    due = Delivery.objects.filter(
        channel=DeliveryChannel.WHATSAPP, status=DeliveryStatus.ACCEPTED,
        next_attempt_at__lte=timezone.now(),
    )
    processed = 0
    for delivery in due:
        processed += 1
        consultas = delivery.attempts.filter(provider_code__startswith='wa_poll').count()
        config = WhatsAppTwilio.objects.filter(tenant_id=delivery.tenant_id).first()
        situacao = codigo = ''
        if delivery.provider_id and config is not None and config.tem_credenciais:
            try:
                situacao, codigo = consultar_mensagem(config, delivery.provider_id)
            except (FalhaDeTransporte, WhatsAppIndisponivel, WhatsAppRecusado):
                situacao = ''
        if aplicar_status_whatsapp(delivery.tenant_id, delivery.provider_id, situacao, codigo, 'wa_poll'):
            continue
        DeliveryAttempt.objects.create(
            tenant=delivery.tenant, delivery=delivery, attempt_number=delivery.attempts.count() + 1,
            started_at=timezone.now(), ended_at=timezone.now(),
            outcome=DeliveryAttemptOutcome.UNKNOWN, provider_code=f'wa_poll:{situacao or "?"}'[:100],
        )
        if consultas + 1 >= len(WHATSAPP_CONSULTAS_MINUTOS):
            delivery.status = DeliveryStatus.UNKNOWN
            delivery.next_attempt_at = None
        else:
            delivery.next_attempt_at = timezone.now() + timezone.timedelta(
                minutes=WHATSAPP_CONSULTAS_MINUTOS[consultas + 1] - WHATSAPP_CONSULTAS_MINUTOS[consultas],
            )
        delivery.save(update_fields=['status', 'next_attempt_at'])
    return processed
