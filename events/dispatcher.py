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
    `consumer_name` is the ProcessedEvent idempotency key. More than one
    independent consumer can register for the same topic (e.g. both
    `finance` and `ai` react to `clinical.encounter_finalized`) -- each
    gets its own ProcessedEvent row and its own at-least-once delivery;
    one consumer's failure never blocks or skips another's.
    """
    _HANDLERS.setdefault(topic_prefix, []).append((consumer_name, handler))


def _handlers_for(topic):
    matches = []
    for prefix, entries in _HANDLERS.items():
        if topic.startswith(prefix):
            matches.extend(entries)
    return matches


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
    handlers = _handlers_for(event.topic)
    if not handlers:
        # Unroutable topic: leave it PENDING with a pushed-back available_at
        # rather than silently dropping it -- a future deploy may register
        # the missing handler.
        OutboxEvent.objects.filter(id=event.id).update(
            status=OutboxEventStatus.PENDING, available_at=timezone.now() + timezone.timedelta(minutes=5),
        )
        return 'no_handler'

    any_failed = False
    all_already_processed = True
    for consumer_name, handler in handlers:
        if ProcessedEvent.objects.filter(event=event, consumer=consumer_name).exists():
            # This consumer already applied a previous (possibly
            # redelivered) attempt -- skip it, but still let any other
            # consumer for this same event run.
            continue
        all_already_processed = False
        try:
            with transaction.atomic():
                handler(event)
                ProcessedEvent.objects.get_or_create(
                    event=event, consumer=consumer_name, defaults={'processed_at': timezone.now()},
                )
        except Exception:
            any_failed = True

    if any_failed:
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

    OutboxEvent.objects.filter(id=event.id).update(status=OutboxEventStatus.COMPLETED)
    return 'already_processed' if all_already_processed else 'completed'


def run_once():
    results = {}
    for event in _claim_batch():
        outcome = _process_one(event)
        results[outcome] = results.get(outcome, 0) + 1
    return results
