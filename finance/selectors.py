from .models import Payment, Receivable


def competence_view(tenant, start_date, end_date):
    """Accrual basis: charges recognized in the period they were *earned*
    (the encounter's own date), regardless of when money actually arrives.
    """
    return Receivable.objects.filter(
        tenant=tenant, competence_date__gte=start_date, competence_date__lte=end_date,
    ).order_by('competence_date')


def cash_view(tenant, start_date, end_date):
    """Cash basis: payments recognized in the period the money actually
    arrived, regardless of which competence period the underlying charge
    belongs to.
    """
    return Payment.objects.filter(
        tenant=tenant, paid_at__date__gte=start_date, paid_at__date__lte=end_date,
    ).select_related('receivable').order_by('paid_at')
