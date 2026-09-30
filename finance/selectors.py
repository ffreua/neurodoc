from .models import Payment, Receivable


def visible_receivables(tenant):
    """Cobranças ainda abertas na visão operacional e gerencial."""
    return Receivable.objects.filter(
        tenant=tenant,
        archived_at__isnull=True,
        doctor_share_paid_at__isnull=True,
    )


def competence_view(tenant, start_date, end_date):
    """Accrual basis: charges recognized in the period they were *earned*
    (the encounter's own date), regardless of when money actually arrives.
    """
    return visible_receivables(tenant).filter(
        competence_date__gte=start_date, competence_date__lte=end_date,
    ).select_related('patient').order_by('competence_date', 'created_at')


def cash_view(tenant, start_date, end_date):
    """Cash basis: payments recognized in the period the money actually
    arrived, regardless of which competence period the underlying charge
    belongs to.
    """
    return Payment.objects.filter(
        tenant=tenant,
        receivable__archived_at__isnull=True,
        receivable__doctor_share_paid_at__isnull=True,
        paid_at__date__gte=start_date,
        paid_at__date__lte=end_date,
    ).select_related('receivable__patient').order_by('paid_at', 'created_at')
