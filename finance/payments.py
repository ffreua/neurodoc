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


def written_off(receivable):
    """O que a clínica deu por perdido ("Baixa"): não entrou, e não se cobra mais."""
    return sum(
        (a.amount for a in receivable.adjustments.filter(type=AdjustmentType.WRITEOFF)),
        start=quantize_brl(0),
    )


def balance(receivable):
    """Quanto ainda se cobra.

    A baixa entra aqui e **não** em `net_received`: ela não é dinheiro que
    entrou, é o que se deixou de cobrar. Até a auditoria de 2026-11-11 ela
    não entrava em lugar nenhum — o ajuste era gravado, e o saldo e a
    situação da cobrança continuavam os mesmos, como se a baixa não
    existisse.
    """
    return quantize_brl(receivable.charged_amount - net_received(receivable) - written_off(receivable))


def _travada(receivable):
    """A cobrança relida com a linha travada, para quem vai mudar o saldo.

    Sem a trava, dois pagamentos simultâneos que juntos quitavam a
    cobrança viam cada um só o próprio e gravavam "Parcial"; dois
    descontos partiam do mesmo valor, e o último apagava o primeiro
    (auditoria de 2026-11-11). `delete_payment` já travava; estes não.
    """
    from .models import Receivable

    return Receivable.objects.select_for_update().get(id=receivable.id)


def _devolver(original, travada):
    """O objeto de quem chamou volta com o que foi gravado."""
    original.charged_amount = travada.charged_amount
    original.status = travada.status


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
    original, receivable = receivable, _travada(receivable)
    if receivable.status == ReceivableStatus.CANCELLED:
        # A cobrança cancelada continua abrindo pela URL (a antiga do exame,
        # trocada de forma de cobrança). O pagamento entrava no caixa, e a
        # situação continuava "Cancelado".
        raise ValueError('Esta cobrança foi cancelada e não recebe pagamento.')
    payment = Payment.objects.create(
        tenant=receivable.tenant, receivable=receivable, paid_at=paid_at or timezone.now(),
        amount=amount, method=method, external_reference=external_reference[:100],
    )
    recompute_status(receivable)
    _devolver(original, receivable)
    record_audit_event(
        actor_id, receivable.tenant_id, 'finance.payment_recorded',
        object_type='payment', object_id=payment.id, outcome='success',
    )
    return payment


#: As formas de pagamento oferecidas na tela (2026-11-05), na ordem em que
#: aparecem. O banco guarda o **rótulo**, e não um código: `Payment.method`
#: sempre foi texto livre, e há pagamentos antigos com "Credito" ou
#: "other" escritos à mão. Guardar o rótulo deixa o novo e o antigo lidos
#: do mesmo jeito, no caixa, na exportação e na tela, sem migração.
METODOS = (
    ('credito_vista', 'Crédito à vista'),
    ('credito_parcelado', 'Crédito parcelado'),
    ('debito', 'Débito'),
    ('pix', 'PIX'),
    ('dinheiro', 'Dinheiro'),
    ('outro', 'Outro'),
)
#: Quanto do texto de "Outro" cabe na coluna de 40, depois de "Outro: ".
MAX_OUTRO = 40 - len('Outro: ')


def rotulo_do_metodo(valor):
    """Como a forma gravada aparece. `other` é o padrão antigo da view."""
    valor = (valor or '').strip()
    if valor in ('', 'other'):
        return 'Outro'
    return valor


class PagamentoNaoExcluivel(Exception):
    """O pagamento não pode sair, e o motivo é para quem está na tela."""


@transaction.atomic
def delete_payment(payment, actor_id):
    """Apaga um pagamento lançado errado (2026-11-05).

    É erro de digitação — R$ 12.000,00 no lugar de R$ 1.200,00 — e a forma
    certa de desfazê-lo é tirar a linha, e não um estorno: estorno diz que
    o dinheiro entrou e voltou, e esse dinheiro nunca entrou. O caixa do
    dia e o saldo da cobrança precisam mostrar o que de fato aconteceu.

    O que fica é a trilha: valor, forma e data do pagamento apagado, sem
    nome de paciente, para quem precisar explicar o caixa depois.

    Não apaga quando há estorno ligado a ele (o estorno refere o pagamento e
    perderia o sentido) nem em cobrança já retirada do financeiro.
    """
    from .models import Receivable

    receivable = Receivable.objects.select_for_update().get(id=payment.receivable_id)
    if receivable.archived_at or receivable.doctor_share_paid_at:
        raise PagamentoNaoExcluivel(
            'Esta cobrança já saiu do financeiro (repasse realizado ou arquivada). '
            'Desfaça o repasse antes de apagar o pagamento.'
        )
    if payment.adjustments.exists():
        raise PagamentoNaoExcluivel(
            'Há um ajuste ligado a este pagamento. Ele não pode ser apagado sozinho.'
        )
    dados = {
        'amount': str(payment.amount), 'method': payment.method[:40],
        'paid_at': payment.paid_at.isoformat(), 'receivable_id': str(receivable.id),
    }
    payment_id = payment.id
    payment.delete()
    recompute_status(receivable)
    record_audit_event(
        actor_id, receivable.tenant_id, 'finance.payment_deleted',
        object_type='payment', object_id=payment_id, outcome='success',
        integrity_metadata=dados,
    )
    return receivable
