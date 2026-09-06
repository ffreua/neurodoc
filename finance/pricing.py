from datetime import date
from decimal import ROUND_HALF_UP, Decimal

from django.db import connection, transaction
from django.db.models import Q

from .models import FeeSchedule


def quantize_brl(value):
    return Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)


class OverlappingFeeSchedule(Exception):
    pass


class NoApplicableFeeSchedule(Exception):
    pass


def _overlap_lock_key(tenant_id, physician_id, plan_id, procedure_id, payment_category):
    return f'feeschedule:{tenant_id}:{physician_id}:{plan_id}:{procedure_id}:{payment_category}'


@transaction.atomic
def create_fee_schedule(tenant, payment_category, gross_amount, doctor_share_amount, effective_from,
                        physician=None, plan=None, procedure=None, effective_to=None):
    """`physician`/`plan`/`procedure` left None means "applies broadly" --
    two rules are "equivalent" (and therefore must not overlap in time)
    only when all three match exactly, NULL included, which is why this is
    an application-level check rather than a Postgres EXCLUDE constraint
    (NULL never equals NULL under `=`, so a naive exclusion constraint
    would silently let two open-ended general rules coexist).
    """
    with connection.cursor() as cursor:
        cursor.execute(
            'SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))',
            [_overlap_lock_key(
                tenant.id, physician.id if physician else None, plan.id if plan else None,
                procedure.id if procedure else None, payment_category,
            )],
        )
    candidates = FeeSchedule.objects.filter(
        tenant=tenant, physician=physician, plan=plan, procedure=procedure, payment_category=payment_category,
    )
    new_end = effective_to or date.max
    for existing in candidates:
        existing_end = existing.effective_to or date.max
        if existing.effective_from < new_end and effective_from < existing_end:
            raise OverlappingFeeSchedule(
                f'Overlaps existing rule {existing.id} ({existing.effective_from}..{existing.effective_to})',
            )
    return FeeSchedule.objects.create(
        tenant=tenant, physician=physician, plan=plan, procedure=procedure, payment_category=payment_category,
        gross_amount=quantize_brl(gross_amount), doctor_share_amount=quantize_brl(doctor_share_amount),
        effective_from=effective_from, effective_to=effective_to,
    )


def _candidates_by_specificity(tenant, physician, plan, procedure, payment_category, at):
    filters = [
        {'physician': physician, 'plan': plan, 'procedure': procedure},
        {'physician': physician, 'plan': plan, 'procedure': None},
        {'physician': physician, 'plan': None, 'procedure': None},
        {'physician': None, 'plan': plan, 'procedure': procedure},
        {'physician': None, 'plan': plan, 'procedure': None},
        {'physician': None, 'plan': None, 'procedure': procedure},
        {'physician': None, 'plan': None, 'procedure': None},
    ]
    seen = set()
    for f in filters:
        key = tuple(sorted((k, v.id if v else None) for k, v in f.items()))
        if key in seen:
            continue
        seen.add(key)
        match = FeeSchedule.objects.filter(
            tenant=tenant, payment_category=payment_category, effective_from__lte=at, **f,
        ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=at)).order_by('-effective_from').first()
        if match:
            return match
    return None


def resolve_price(tenant, physician, payment_category, at, plan=None, procedure=None):
    """Most-specific rule wins: physician+plan+procedure, then progressively
    more general combinations, down to a fully general rule for the
    tenant. Raises if nothing at all is applicable on that date.
    """
    match = _candidates_by_specificity(tenant, physician, plan, procedure, payment_category, at)
    if match is None:
        raise NoApplicableFeeSchedule(
            f'No fee schedule applies for {payment_category} on {at} (physician={physician}, plan={plan})',
        )
    return match


def snapshot_from_fee_schedule(fee_schedule):
    return {
        'fee_schedule_id': str(fee_schedule.id),
        'payment_category': fee_schedule.payment_category,
        'gross_amount': str(fee_schedule.gross_amount),
        'doctor_share_amount': str(fee_schedule.doctor_share_amount),
        'physician_id': str(fee_schedule.physician_id) if fee_schedule.physician_id else None,
        'plan_id': str(fee_schedule.plan_id) if fee_schedule.plan_id else None,
        'procedure_id': str(fee_schedule.procedure_id) if fee_schedule.procedure_id else None,
    }
