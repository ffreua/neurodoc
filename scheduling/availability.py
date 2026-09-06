from datetime import datetime, timedelta

from django.utils import timezone

from .models import OCCUPYING_STATUSES, Appointment, AvailabilityRule, ScheduleBlock, ScheduleBlockKind


def _combine(date, time_value):
    naive = datetime.combine(date, time_value)
    return timezone.make_aware(naive) if timezone.is_naive(naive) else naive


def _ends_on_ok(date):
    from django.db.models import Q
    return Q(ends_on__isnull=True) | Q(ends_on__gte=date)


def _rule_intervals(physician_membership_id, date):
    """Weekly rule intervals valid on this date, as (start_dt, end_dt) tuples."""
    weekday = date.weekday()
    rules = AvailabilityRule.objects.filter(
        physician_membership_id=physician_membership_id, weekday=weekday, starts_on__lte=date,
    ).filter(_ends_on_ok(date))
    return [(
        _combine(date, rule.local_start), _combine(date, rule.local_end), rule.slot_minutes, rule.buffer_minutes,
    ) for rule in rules]


def _blocks_on(physician_membership_id, date):
    day_start = _combine(date, datetime.min.time())
    day_end = day_start + timedelta(days=1)
    return ScheduleBlock.objects.filter(
        physician_membership_id=physician_membership_id, start_at__lt=day_end, end_at__gt=day_start,
    )


def _subtract_interval(intervals, block_start, block_end):
    result = []
    for start, end in intervals:
        if block_end <= start or block_start >= end:
            result.append((start, end))
            continue
        if block_start > start:
            result.append((start, block_start))
        if block_end < end:
            result.append((block_end, end))
    return result


def available_slots(physician_membership_id, date):
    """Returns a list of (start, end) datetime tuples the physician can be
    booked into on this date, after applying blocks/vacations/extra
    availability and existing occupying appointments. Date-specific
    exceptions (ScheduleBlock) always prevail over the weekly rule.
    """
    rule_intervals = []
    for start, end, slot_minutes, buffer_minutes in _rule_intervals(physician_membership_id, date):
        rule_intervals.append((start, end))

    intervals = list(rule_intervals)
    for block in _blocks_on(physician_membership_id, date):
        if block.kind == ScheduleBlockKind.EXTRA_AVAILABILITY:
            intervals.append((max(block.start_at, _combine(date, datetime.min.time())), block.end_at))
        else:
            intervals = _subtract_interval(intervals, block.start_at, block.end_at)

    occupied = Appointment.objects.filter(
        physician_membership_id=physician_membership_id, status__in=list(OCCUPYING_STATUSES),
        starts_at__lt=_combine(date, datetime.min.time()) + timedelta(days=1),
        ends_at__gt=_combine(date, datetime.min.time()),
    )
    for appt in occupied:
        intervals = _subtract_interval(intervals, appt.starts_at, appt.ends_at)

    slot_minutes = 30
    buffer_minutes = 0
    rules = list(_rule_intervals(physician_membership_id, date))
    if rules:
        slot_minutes = rules[0][2]
        buffer_minutes = rules[0][3]

    slots = []
    for start, end in intervals:
        cursor = start
        step = timedelta(minutes=slot_minutes + buffer_minutes)
        while cursor + timedelta(minutes=slot_minutes) <= end:
            slots.append((cursor, cursor + timedelta(minutes=slot_minutes)))
            cursor += step
    return sorted(slots)
