from .models import AdjustmentType, FinancialAdjustment, Payment, Receivable


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


def caixa(tenant, start_date, end_date):
    """O caixa do período: o que entrou e o que saiu, na ordem em que aconteceu.

    **Até a auditoria de 2026-11-11 só o que entrou.** O estorno é um
    `FinancialAdjustment`, e não um `Payment`, e o caixa lia só pagamentos:
    R$ 300,00 recebidos e devolvidos no mesmo dia apareciam como R$ 300,00
    em caixa, na tela e na planilha. Agora o estorno entra como saída, com
    valor negativo, no dia em que foi lançado — `created_at` é a única data
    que ele tem, e é quando o dinheiro voltou ao paciente.

    Devolve dicionários, e não objetos de dois modelos, para a tela e a
    exportação não precisarem saber qual é qual.
    """
    from django.utils import timezone

    from .payments import rotulo_do_metodo

    movimentos = []
    for p in cash_view(tenant, start_date, end_date):
        movimentos.append({
            'paciente': p.receivable.patient.full_name, 'quando': timezone.localtime(p.paid_at),
            'valor': p.amount, 'metodo': rotulo_do_metodo(p.method), 'estorno': False,
            'referencia': p.external_reference, 'nota': p.receivable.fiscal_document_number,
        })
    estornos = FinancialAdjustment.objects.filter(
        tenant=tenant, type=AdjustmentType.REFUND,
        receivable__archived_at__isnull=True,
        receivable__doctor_share_paid_at__isnull=True,
        created_at__date__gte=start_date, created_at__date__lte=end_date,
    ).select_related('receivable__patient')
    for a in estornos:
        movimentos.append({
            'paciente': a.receivable.patient.full_name, 'quando': timezone.localtime(a.created_at),
            'valor': -a.amount, 'metodo': 'Estorno', 'estorno': True,
            'referencia': a.reason, 'nota': a.receivable.fiscal_document_number,
        })
    movimentos.sort(key=lambda m: m['quando'])
    return movimentos
