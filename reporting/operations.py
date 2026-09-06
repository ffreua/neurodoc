import datetime
from decimal import Decimal

from django.db.models import Q
from django.utils import timezone

from finance.models import FinancialAdjustment, Payment, Receivable, ReceivableStatus
from finance.payments import quantize_brl
from scheduling.models import OCCUPYING_STATUSES, Appointment, AvailabilityRule, ScheduleBlock


def _day_bounds(day):
    start = timezone.make_aware(datetime.datetime.combine(day, datetime.time.min))
    end = timezone.make_aware(datetime.datetime.combine(day, datetime.time.max))
    return start, end


def schedule_occupancy(tenant, physician_membership, start, end):
    """Minutos ocupados por reservas válidas / minutos ofertados após
    bloqueios. Encaixes (`is_overbook`) são somados à parte -- nunca
    misturados ao numerador padrão, para nunca mascarar uma taxa > 100%.
    """
    offered_minutes = 0
    day = start
    while day <= end:
        weekday = day.weekday()
        rules = AvailabilityRule.objects.filter(
            tenant=tenant, physician_membership=physician_membership, weekday=weekday,
        ).filter(Q(starts_on__isnull=True) | Q(starts_on__lte=day)).filter(
            Q(ends_on__isnull=True) | Q(ends_on__gte=day),
        )
        day_offered = sum(
            (rule.local_end.hour * 60 + rule.local_end.minute) - (rule.local_start.hour * 60 + rule.local_start.minute)
            for rule in rules
        )
        day_start, day_end = _day_bounds(day)
        blocks = ScheduleBlock.objects.filter(
            tenant=tenant, physician_membership=physician_membership, kind__in=['block', 'vacation'],
            start_at__lte=day_end, end_at__gte=day_start,
        )
        blocked_minutes = 0
        for block in blocks:
            overlap_start = max(block.start_at, day_start)
            overlap_end = min(block.end_at, day_end)
            if overlap_end > overlap_start:
                blocked_minutes += (overlap_end - overlap_start).total_seconds() / 60
        offered_minutes += max(day_offered - blocked_minutes, 0)
        day += datetime.timedelta(days=1)

    appointments = Appointment.objects.filter(
        tenant=tenant, physician_membership=physician_membership,
        starts_at__date__gte=start, starts_at__date__lte=end, status__in=OCCUPYING_STATUSES,
    )
    occupied_minutes = 0.0
    overbook_minutes = 0.0
    for appt in appointments:
        duration = (appt.ends_at - appt.starts_at).total_seconds() / 60
        if appt.is_overbook:
            overbook_minutes += duration
        else:
            occupied_minutes += duration

    return {
        'offered_minutes': offered_minutes, 'occupied_minutes': occupied_minutes, 'overbook_minutes': overbook_minutes,
        'rate': (occupied_minutes / offered_minutes) if offered_minutes else None,
        'rate_with_overbook': ((occupied_minutes + overbook_minutes) / offered_minutes) if offered_minutes else None,
    }


def payment_category_breakdown(tenant, start, end, unit='patient'):
    """`unit='patient'` (padrão) ou `unit='appointment'` -- nunca soma as
    duas visões sem indicar qual foi escolhida, e nunca duplica um
    paciente que tenha ambas as categorias na mesma janela.
    """
    receivables = Receivable.objects.filter(
        tenant=tenant, competence_date__gte=start, competence_date__lte=end,
    ).exclude(status=ReceivableStatus.CANCELLED)
    result = {}
    for category_field, snapshot_key in [('private', 'private'), ('insurance', 'insurance')]:
        qs = receivables.filter(fee_snapshot__payment_category=snapshot_key)
        if unit == 'patient':
            result[category_field] = qs.values('patient_id').distinct().count()
        else:
            result[category_field] = qs.count()
    return result


def revenue_by_competence(tenant, start, end):
    """Soma charged_amount (já líquido de desconto/acréscimo, aplicados em
    S09 diretamente sobre esse campo) das cobranças elegíveis pela
    competence_date -- recebimento em caixa é reportado separadamente.
    """
    receivables = Receivable.objects.filter(
        tenant=tenant, competence_date__gte=start, competence_date__lte=end,
    ).exclude(status=ReceivableStatus.CANCELLED)
    total = quantize_brl(0)
    for r in receivables:
        total += r.charged_amount
    return total


def cash_received(tenant, start, end):
    """Soma Payment.amount menos estornos, pela data em que o dinheiro
    efetivamente chegou (paid_at) -- nunca pela competência da cobrança.
    """
    payments = Payment.objects.filter(tenant=tenant, paid_at__date__gte=start, paid_at__date__lte=end)
    total_paid = quantize_brl(0)
    for p in payments:
        total_paid += p.amount
    refunds = FinancialAdjustment.objects.filter(
        tenant=tenant, type='refund', payment__paid_at__date__gte=start, payment__paid_at__date__lte=end,
    )
    total_refunded = quantize_brl(0)
    for a in refunds:
        total_refunded += a.amount
    return quantize_brl(total_paid - total_refunded)


def outstanding_balance(tenant, as_of_date):
    """Cobrado líquido menos recebido líquido, por vencimento até a data
    de corte -- um saldo negativo indica crédito e exige conciliação, não
    é tratado como dívida.
    """
    from finance.payments import balance

    receivables = Receivable.objects.filter(
        tenant=tenant, due_date__lte=as_of_date,
    ).exclude(status=ReceivableStatus.CANCELLED)
    total = quantize_brl(0)
    for r in receivables:
        total += balance(r)
    return total


def doctor_share_forecast(tenant, start, end):
    """Soma do repasse previsto (snapshot congelado no momento da
    cobrança) -- nunca rotulado como repasse efetivamente pago.
    """
    receivables = Receivable.objects.filter(
        tenant=tenant, competence_date__gte=start, competence_date__lte=end,
    ).exclude(status=ReceivableStatus.CANCELLED)
    total = quantize_brl(0)
    for r in receivables:
        share = r.fee_snapshot.get('doctor_share_amount')
        if share:
            total += quantize_brl(Decimal(share))
    return total
