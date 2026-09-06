from datetime import timedelta

from django.db import transaction

from events.models import OutboxEvent, OutboxEventStatus

REMINDER_TOPIC_PREFIX = 'scheduling.appointment_reminder'
REMINDER_OFFSETS_HOURS = (24, 2)


def _topic_for(hours_before):
    return f'{REMINDER_TOPIC_PREFIX}.{hours_before}h'


@transaction.atomic
def invalidate_stale_reminders(appointment):
    """Cancels any still-pending reminders from a previous version of this
    appointment — called before scheduling new ones on reschedule/cancel, so
    a stale reminder never fires with the old time/state.
    """
    OutboxEvent.objects.filter(
        tenant_id=appointment.tenant_id, topic__startswith=REMINDER_TOPIC_PREFIX,
        aggregate_type='appointment', aggregate_id=appointment.id,
        status=OutboxEventStatus.PENDING,
    ).exclude(event_version=appointment.row_version).update(status=OutboxEventStatus.CANCELLED)


RESERVED_TOPIC = 'scheduling.appointment_reserved'


@transaction.atomic
def emit_appointment_reserved(appointment):
    """A distinct, explicit event for administrative (CRM) integration --
    kept separate from the reminder events above, and from the synchronous
    audit trail entry, so a CRM-side failure can never affect the booking
    itself (the event is only ever consumed asynchronously by the outbox
    dispatcher).
    """
    OutboxEvent.objects.get_or_create(
        tenant_id=appointment.tenant_id, topic=RESERVED_TOPIC, aggregate_type='appointment',
        aggregate_id=appointment.id, event_version=appointment.row_version,
        defaults={
            'payload_minimal': {'appointment_id': str(appointment.id), 'patient_id': str(appointment.patient_id)},
            'available_at': _now(),
            'status': OutboxEventStatus.PENDING,
        },
    )


@transaction.atomic
def schedule_reminders(appointment):
    invalidate_stale_reminders(appointment)
    created = []
    for hours_before in REMINDER_OFFSETS_HOURS:
        available_at = appointment.starts_at - timedelta(hours=hours_before)
        event, _ = OutboxEvent.objects.get_or_create(
            tenant_id=appointment.tenant_id, topic=_topic_for(hours_before), aggregate_type='appointment',
            aggregate_id=appointment.id, event_version=appointment.row_version,
            defaults={
                'payload_minimal': {'appointment_id': str(appointment.id), 'hours_before': hours_before},
                'available_at': available_at,
                'status': OutboxEventStatus.PENDING if available_at > _now() else OutboxEventStatus.CANCELLED,
            },
        )
        created.append(event)
    return created


def _now():
    from django.utils import timezone
    return timezone.now()
