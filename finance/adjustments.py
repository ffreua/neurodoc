from django.db import transaction

from audit.services import record_audit_event

from .models import AdjustmentType, FinancialAdjustment, ReceivableStatus
from .payments import _devolver, _travada, balance, net_received, recompute_status, quantize_brl


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
    original, receivable = receivable, _travada(receivable)
    if receivable.status == ReceivableStatus.CANCELLED:
        raise ValueError('Esta cobrança foi cancelada e não recebe ajuste.')
    # Os tetos (auditoria de 2026-11-11). Sem eles, um desconto de
    # R$ 2.000,00 digitado no lugar de R$ 20,00 deixava a cobrança negativa
    # e marcada "Pago" sem pagamento nenhum; o estorno maior que o recebido
    # deixava o recebido negativo.
    if adjustment_type == AdjustmentType.DISCOUNT and amount > receivable.charged_amount:
        raise ValueError('O desconto não pode ser maior que o valor cobrado.')
    if adjustment_type == AdjustmentType.REFUND:
        teto = net_received(receivable)
        if payment is not None:
            ja_estornado = sum(
                (a.amount for a in payment.adjustments.filter(type=AdjustmentType.REFUND)),
                start=quantize_brl(0),
            )
            teto = min(teto, quantize_brl(payment.amount - ja_estornado))
        if amount > teto:
            raise ValueError('O estorno não pode ser maior que o valor recebido.')
    if adjustment_type == AdjustmentType.WRITEOFF and amount > balance(receivable):
        raise ValueError('A baixa não pode ser maior que o saldo em aberto.')

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
    # balance through net_received() and written_off() in balance().
    recompute_status(receivable)
    _devolver(original, receivable)
    record_audit_event(
        approved_by.user_id, receivable.tenant_id, 'finance.adjustment_applied',
        object_type='financial_adjustment', object_id=adjustment.id, outcome='success',
        integrity_metadata={'type': adjustment_type},
    )
    return adjustment
