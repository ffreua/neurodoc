from django.db import connection, transaction
from django.utils import timezone

from audit.services import record_audit_event

from .events import invalidate_stale_reminders, schedule_reminders
from .models import ALLOWED_TRANSITIONS, Appointment, AppointmentStatus


class SchedulingError(Exception):
    pass


class SlotUnavailable(SchedulingError):
    pass


class IllegalTransition(SchedulingError):
    pass


def _lock_days(physician_membership_id, dates):
    """Transaction-scoped advisory lock per (physician, day), acquired in a
    stable sorted order so multi-day appointments never deadlock against a
    concurrent reservation locking the same two days in reverse order.
    """
    for date in sorted(set(dates)):
        key = f'schedule:{physician_membership_id}:{date.isoformat()}'
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))', [key])


def _days_spanned(starts_at, ends_at):
    days = {starts_at.date(), ends_at.date()}
    return list(days)


def _build_occupied_range(starts_at, ends_at, buffer_minutes=0):
    from datetime import timedelta

    from django.db.backends.postgresql.psycopg_any import DateTimeTZRange

    return DateTimeTZRange(
        starts_at, ends_at + timedelta(minutes=buffer_minutes), bounds='[)',
    )


@transaction.atomic
def reserve_appointment(
    context, patient, physician_membership, starts_at, ends_at, appointment_type,
    is_overbook=False, override_reason='', override_by=None, buffer_minutes=0,
):
    if is_overbook and not override_reason:
        raise SchedulingError('Overbook requires a justification')
    _lock_days(physician_membership.id, _days_spanned(starts_at, ends_at))
    appointment = Appointment(
        tenant_id=context.tenant_id, patient=patient, physician_membership=physician_membership,
        starts_at=starts_at, ends_at=ends_at,
        occupied_range=_build_occupied_range(starts_at, ends_at, buffer_minutes),
        status=AppointmentStatus.SCHEDULED, type=appointment_type,
        is_overbook=is_overbook, override_reason=override_reason, override_by=override_by,
    )
    appointment.full_clean()
    appointment.save()
    record_audit_event(
        context.user_id, context.tenant_id, 'scheduling.appointment_reserved',
        object_type='appointment', object_id=appointment.id, outcome='success',
    )
    schedule_reminders(appointment)
    return appointment


@transaction.atomic
def reschedule_appointment(context, appointment, new_starts_at, new_ends_at, actor_id, buffer_minutes=0):
    _lock_days(appointment.physician_membership_id, _days_spanned(new_starts_at, new_ends_at))
    old_starts_at, old_ends_at, old_version = appointment.starts_at, appointment.ends_at, appointment.row_version
    appointment.starts_at = new_starts_at
    appointment.ends_at = new_ends_at
    appointment.occupied_range = _build_occupied_range(new_starts_at, new_ends_at, buffer_minutes)
    appointment.row_version += 1
    appointment.full_clean()
    appointment.save()
    record_audit_event(
        actor_id, context.tenant_id, 'scheduling.appointment_rescheduled',
        object_type='appointment', object_id=appointment.id, outcome='success',
        integrity_metadata={
            'old_starts_at': old_starts_at.isoformat(), 'old_ends_at': old_ends_at.isoformat(),
            'old_row_version': old_version, 'new_row_version': appointment.row_version,
        },
    )
    schedule_reminders(appointment)
    return appointment


@transaction.atomic
def transition_appointment(appointment, new_status, actor_id, **extra_fields):
    current = AppointmentStatus(appointment.status)
    allowed = ALLOWED_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise IllegalTransition(f'{current} -> {new_status} is not allowed')
    appointment.status = new_status
    appointment.row_version += 1
    for field, value in extra_fields.items():
        setattr(appointment, field, value)
    appointment.full_clean()
    appointment.save()
    record_audit_event(
        actor_id, appointment.tenant_id, f'scheduling.appointment_{new_status}',
        object_type='appointment', object_id=appointment.id, outcome='success',
    )
    return appointment


def cancel_appointment(appointment, actor_id, reason=''):
    result = transition_appointment(appointment, AppointmentStatus.CANCELLED, actor_id, cancellation_reason=reason)
    invalidate_stale_reminders(result)
    return result


def check_in(appointment, actor_id):
    return transition_appointment(appointment, AppointmentStatus.CHECKED_IN, actor_id)


def start_appointment(appointment, actor_id):
    return transition_appointment(appointment, AppointmentStatus.IN_PROGRESS, actor_id)


def complete_appointment(appointment, actor_id):
    return transition_appointment(appointment, AppointmentStatus.COMPLETED, actor_id)


def mark_no_show(appointment, actor_id):
    if timezone.now() < appointment.ends_at:
        raise SchedulingError('Cannot mark no-show before the appointment window ends')
    return transition_appointment(appointment, AppointmentStatus.NO_SHOW, actor_id)
