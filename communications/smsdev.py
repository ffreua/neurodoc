import requests
from django.conf import settings

SEND_URL = 'https://api.smsdev.com.br/v1/send'
DLR_URL = 'https://api.smsdev.com.br/v1/dlr'
REQUEST_TIMEOUT_SECONDS = 10


class SmsChannelDisabled(Exception):
    """Canal de SMS desligado — nunca finge que enviou.

    Duas coisas podem desligá-lo: `SMS_ENABLED=False` na instalação (P-03) ou
    a clínica não ter ativado o canal na tela do gestor. Quem chama trata
    isso igual a "não há contato disponível".
    """


class SmsSendFailed(Exception):
    pass


def resolve_api_key(tenant_id=None):
    """A chave a usar: a da clínica, se houver; senão a da instalação.

    A chave por clínica é o caso normal — quem tem conta no SMSDEV é a
    clínica. A da instalação continua valendo como padrão para quem não
    configurou a própria, e é o que mantém funcionando o que já estava
    montado por Docker Secret.
    """
    if tenant_id is not None:
        # O plano da clinica, conferido aqui e nao so na tela.
        #
        # Esta funcao e o ponto por onde passa **todo** SMS: o lembrete de
        # consulta, o codigo de acesso a documento e a consulta de saldo.
        # Os dois primeiros nascem de evento e de tarefa do worker, sem
        # tela nenhuma e sem ninguem clicando -- deixar o corte so na tela
        # de configuracao fecharia a porta que tem tela e deixaria aquelas
        # abertas, gastando o credito da instalacao numa clinica que nao
        # contratou o recurso.
        #
        # Antes da leitura da chave da clinica, de proposito: o corte e por
        # plano, e vale inclusive para quem trouxe a propria chave. Ver
        # `tenancy.plans.has_sms`.
        from tenancy.models import Tenant
        from tenancy.plans import has_sms

        plano = Tenant.objects.filter(id=tenant_id).values_list('plan', flat=True).first()
        if plano is not None and not has_sms(plano):
            raise SmsChannelDisabled(
                'O plano desta clinica nao inclui envio de SMS. O aviso por e-mail '
                'continua funcionando.'
            )

        from base.crypto import SecretUnavailable

        from .models import MessagingSettings

        row = MessagingSettings.objects.filter(tenant_id=tenant_id).first()
        if row is not None and row.has_api_key:
            if not row.sms_enabled:
                raise SmsChannelDisabled(
                    'O canal de SMS está desativado nas configurações desta clínica.'
                )
            try:
                return row.api_key()
            except SecretUnavailable as exc:
                raise SmsSendFailed(str(exc)) from exc
    key = getattr(settings, 'SMSDEV_API_KEY', '')
    if not key:
        raise SmsChannelDisabled(
            'Nenhuma chave do SMSDEV configurada. Informe-a em Configurações da clínica.'
        )
    return key


def send_sms(number, message, refer, tenant_id=None):
    """POSTs to SMSDEV per the documented contract: key/type=9/number/msg/
    refer, JSON body, TLS verified, key never in the URL or in logs.
    `refer` (<=100 chars) is our own idempotency marker on the local side
    only -- SMSDEV's own delivery guarantees are not assumed exactly-once.
    """
    if not settings.SMS_ENABLED:
        raise SmsChannelDisabled('SMS channel is disabled (SMS_ENABLED=False)')
    # `SmsSendFailed`, e nao `ValueError`.
    #
    # As duas condicoes abaixo sao defeito nosso, nao falha do provedor --
    # mas o chamador e o mesmo nos dois casos, e so `SmsSendFailed` ele
    # sabe tratar. Com `ValueError`, a mensagem de documento que passou de
    # 160 caracteres subiu por `_send`, por `deliver_document` e pela view
    # ate virar `Server Error (500)` na cara do medico, com o documento ja
    # assinado. Quem impede o defeito de chegar aqui e
    # `services._sms_document_message` e o roteiro que mede a mensagem com
    # o link real; esta linha so garante que, se chegar, vire uma entrega
    # marcada como falha em vez de uma tela de erro.
    if len(refer) > 100:
        raise SmsSendFailed('refer must be at most 100 characters')
    if len(message) > 160:
        raise SmsSendFailed(
            f'message of {len(message)} chars exceeds the 160-character segment'
        )
    api_key = resolve_api_key(tenant_id)
    try:
        response = requests.post(
            SEND_URL,
            json={'key': api_key, 'type': 9, 'number': number, 'msg': message, 'refer': refer},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise SmsSendFailed(f'SMSDEV request failed: {exc.__class__.__name__}') from exc
    if response.status_code != 200:
        raise SmsSendFailed(f'SMSDEV returned HTTP {response.status_code}')
    return response.json()


def check_balance(tenant_id=None):
    """Consulta o saldo da conta — é o teste da chave sem enviar SMS.

    Serve ao botão "testar" da tela de configuração: confirma que a chave é
    aceita pelo provedor sem gastar crédito nem mandar mensagem para o
    telefone de ninguém.
    """
    api_key = resolve_api_key(tenant_id)
    try:
        response = requests.post(
            SEND_URL, json={'key': api_key, 'action': 'saldo'}, timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise SmsSendFailed(f'SMSDEV request failed: {exc.__class__.__name__}') from exc
    if response.status_code != 200:
        raise SmsSendFailed(f'SMSDEV returned HTTP {response.status_code}')
    return response.json()


def check_delivery(message_ids, tenant_id=None):
    """Polls delivery status for a batch of provider message ids. Baseline
    polling cadence (1/5/15/60 minutes then administrative review) is
    implemented by the caller (communications.reconciliation), not here.
    """
    if not settings.SMS_ENABLED:
        raise SmsChannelDisabled('SMS channel is disabled (SMS_ENABLED=False)')
    api_key = resolve_api_key(tenant_id)
    try:
        response = requests.post(
            DLR_URL, json={'key': api_key, 'id': message_ids}, timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise SmsSendFailed(f'SMSDEV DLR request failed: {exc.__class__.__name__}') from exc
    if response.status_code != 200:
        raise SmsSendFailed(f'SMSDEV DLR returned HTTP {response.status_code}')
    return response.json()
