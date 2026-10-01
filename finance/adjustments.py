from django.db import transaction

from audit.services import record_audit_event

from .models import AdjustmentType, FinancialAdjustment
from .payments import recompute_status, quantize_brl


@transaction.atomic
def apply_adjustment(receivable, adjustment_type, amount, reason, approved_by, payment=None):
    """Discount/surcharge change how much is owed (`charged_amount`);
    refund/writeoff never touch it -- they only affect how much has
    effectively been *received* (see finance.payments.net_received), so a
    refund can never make the original Payment row disappear or change.
    """
    amount = quantize_brl(amount)
    if amount <= 0:
        raise ValueError('O valor do ajuste precisa ser maior que zero.')
    if payment is not None and payment.receivable_id != receivable.id:
        raise ValueError('Este pagamento é de outra cobrança.')

    adjustment = FinancialAdjustment.objects.create(
        tenant=receivable.tenant, receivable=receivable, payment=payment, type=adjustment_type,
        amount=amount, reason=reason[:255], approved_by=approved_by,
    )
    if adjustment_type == AdjustmentType.DISCOUNT:
        receivable.charged_amount = quantize_brl(receivable.charged_amount - amount)
        receivable.save(update_fields=['charged_amount'])
    elif adjustment_type == AdjustmentType.SURCHARGE:
        receivable.charged_amount = quantize_brl(receivable.charged_amount + amount)
        receivable.save(update_fields=['charged_amount'])
    # REFUND and WRITEOFF leave charged_amount untouched; they change the
    # balance only through net_received()/recompute_status() below.
    recompute_status(receivable)
    record_audit_event(
        approved_by.user_id, receivable.tenant_id, 'finance.adjustment_applied',
        object_type='financial_adjustment', object_id=adjustment.id, outcome='success',
        integrity_metadata={'type': adjustment_type},
    )
    return adjustment
