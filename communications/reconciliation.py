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


def _extract_situacao(result, provider_id):
    """Best-effort parse of the SMSDEV DLR response. The exact response
    schema could not be homologated against a live account (P-03), so this
    only recognizes the shapes documented publicly; anything else is
    treated as still-unknown rather than guessed.
    """
    for item in result.get('items', []) if isinstance(result, dict) else []:
        if str(item.get('id')) == str(provider_id):
            status = str(item.get('situacao', '')).upper()
            if status in ('DELIVERED', 'ENTREGUE'):
                return 'delivered'
            if status in ('FAILED', 'REJEITADO', 'ERRO'):
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
