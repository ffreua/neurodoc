from django.db import transaction
from django.db.models import F
from django.utils import timezone

from .models import OutboxEvent, OutboxEventStatus, ProcessedEvent

LEASE_SECONDS = 30
BATCH_SIZE = 50
MAX_ATTEMPTS = 8

_HANDLERS = {}


def register_handler(topic_prefix, consumer_name, handler):
    """Registers `handler(event)` for any topic starting with `topic_prefix`.
    `consumer_name` is the ProcessedEvent idempotency key -- distinct
    consumers of the same event (unlikely here, but future-proof) get
    independent at-least-once delivery.
    """
    _HANDLERS[topic_prefix] = (consumer_name, handler)


def _handler_for(topic):
    for prefix, entry in _HANDLERS.items():
        if topic.startswith(prefix):
            return entry
    return None, None


@transaction.atomic
def _claim_batch():
    now = timezone.now()
    claimable = OutboxEvent.objects.select_for_update(skip_locked=True).filter(
        status=OutboxEventStatus.PENDING, available_at__lte=now,
    ).order_by('available_at')[:BATCH_SIZE]
    # Reclaim leases abandoned by a crashed/killed worker (locked_until passed).
    stale = OutboxEvent.objects.select_for_update(skip_locked=True).filter(
        status=OutboxEventStatus.PROCESSING, locked_until__lt=now,
    ).order_by('available_at')[:BATCH_SIZE]
    ids = list(claimable.values_list('id', flat=True)) + list(stale.values_list('id', flat=True))
    if not ids:
        return []
    OutboxEvent.objects.filter(id__in=ids).update(
        status=OutboxEventStatus.PROCESSING, locked_until=now + timezone.timedelta(seconds=LEASE_SECONDS),
        attempts=F('attempts') + 1,
    )
    return list(OutboxEvent.objects.filter(id__in=ids))


def _process_one(event):
    consumer_name, handler = _handler_for(event.topic)
    if handler is None:
        # Unroutable topic: leave it PENDING with a pushed-back available_at
        # rather than silently dropping it -- a future deploy may register
        # the missing handler.
        OutboxEvent.objects.filter(id=event.id).update(
            status=OutboxEventStatus.PENDING, available_at=timezone.now() + timezone.timedelta(minutes=5),
        )
        return 'no_handler'

    if ProcessedEvent.objects.filter(event=event, consumer=consumer_name).exists():
        # Already applied by a previous (possibly redelivered) attempt --
        # ack without re-running the side effect.
        OutboxEvent.objects.filter(id=event.id).update(status=OutboxEventStatus.COMPLETED)
        return 'already_processed'

    try:
        with transaction.atomic():
            handler(event)
            ProcessedEvent.objects.get_or_create(
                event=event, consumer=consumer_name, defaults={'processed_at': timezone.now()},
            )
        OutboxEvent.objects.filter(id=event.id).update(status=OutboxEventStatus.COMPLETED)
        return 'completed'
    except Exception:
        attempts = event.attempts
        if attempts >= MAX_ATTEMPTS:
            OutboxEvent.objects.filter(id=event.id).update(status=OutboxEventStatus.FAILED)
            return 'failed'
        backoff_seconds = min(2 ** attempts, 900)
        OutboxEvent.objects.filter(id=event.id).update(
            status=OutboxEventStatus.PENDING,
            available_at=timezone.now() + timezone.timedelta(seconds=backoff_seconds),
        )
        return 'retrying'


def run_once():
    results = {}
    for event in _claim_batch():
        outcome = _process_one(event)
        results[outcome] = results.get(outcome, 0) + 1
    return results
