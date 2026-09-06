import requests
from django.conf import settings

SEND_URL = 'https://api.smsdev.com.br/v1/send'
DLR_URL = 'https://api.smsdev.com.br/v1/dlr'
REQUEST_TIMEOUT_SECONDS = 10


class SmsChannelDisabled(Exception):
    """SMS_ENABLED is False (P-03 unresolved) -- never silently pretend to
    send; the caller must treat this the same as "no contact available".
    """


class SmsSendFailed(Exception):
    pass


def send_sms(number, message, refer):
    """POSTs to SMSDEV per the documented contract: key/type=9/number/msg/
    refer, JSON body, TLS verified, key never in the URL or in logs.
    `refer` (<=100 chars) is our own idempotency marker on the local side
    only -- SMSDEV's own delivery guarantees are not assumed exactly-once.
    """
    if not settings.SMS_ENABLED:
        raise SmsChannelDisabled('SMS channel is disabled (SMS_ENABLED=False)')
    if len(refer) > 100:
        raise ValueError('refer must be at most 100 characters')
    if len(message) > 160:
        raise ValueError('message must fit a single 160-character segment for this baseline')
    try:
        response = requests.post(
            SEND_URL,
            json={'key': settings.SMSDEV_API_KEY, 'type': 9, 'number': number, 'msg': message, 'refer': refer},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise SmsSendFailed(f'SMSDEV request failed: {exc.__class__.__name__}') from exc
    if response.status_code != 200:
        raise SmsSendFailed(f'SMSDEV returned HTTP {response.status_code}')
    return response.json()


def check_delivery(message_ids):
    """Polls delivery status for a batch of provider message ids. Baseline
    polling cadence (1/5/15/60 minutes then administrative review) is
    implemented by the caller (communications.reconciliation), not here.
    """
    if not settings.SMS_ENABLED:
        raise SmsChannelDisabled('SMS channel is disabled (SMS_ENABLED=False)')
    try:
        response = requests.post(
            DLR_URL, json={'key': settings.SMSDEV_API_KEY, 'id': message_ids}, timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise SmsSendFailed(f'SMSDEV DLR request failed: {exc.__class__.__name__}') from exc
    if response.status_code != 200:
        raise SmsSendFailed(f'SMSDEV DLR returned HTTP {response.status_code}')
    return response.json()
