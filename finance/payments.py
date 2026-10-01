from django.db import transaction
from django.utils import timezone

from audit.services import record_audit_event

from .models import AdjustmentType, Payment, ReceivableStatus
from .pricing import quantize_brl


def net_received(receivable):
    total_paid = sum((p.amount for p in receivable.payments.all()), start=quantize_brl(0))
    total_refunded = sum(
        (a.amount for a in receivable.adjustments.filter(type=AdjustmentType.REFUND)), start=quantize_brl(0),
    )
    return quantize_brl(total_paid - total_refunded)


def balance(receivable):
    return quantize_brl(receivable.charged_amount - net_received(receivable))


def recompute_status(receivable):
    if receivable.status == ReceivableStatus.CANCELLED:
        return receivable
    remaining = balance(receivable)
    received = net_received(receivable)
    if remaining <= 0:
        receivable.status = ReceivableStatus.PAID
    elif received > 0:
        receivable.status = ReceivableStatus.PARTIAL
    else:
        receivable.status = ReceivableStatus.PENDING
    receivable.save(update_fields=['status'])
    return receivable


@transaction.atomic
def record_payment(receivable, amount, method, actor_id, paid_at=None, external_reference=''):
    amount = quantize_brl(amount)
    if amount <= 0:
        raise ValueError('O valor do pagamento precisa ser maior que zero.')
    payment = Payment.objects.create(
        tenant=receivable.tenant, receivable=receivable, paid_at=paid_at or timezone.now(),
        amount=amount, method=method, external_reference=external_reference[:100],
    )
    recompute_status(receivable)
    record_audit_event(
        actor_id, receivable.tenant_id, 'finance.payment_recorded',
        object_type='payment', object_id=payment.id, outcome='success',
    )
    return payment
