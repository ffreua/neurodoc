import datetime

from django.utils import timezone
from django.contrib import messages
from django.http import HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render

from tenancy.permissions import Capability, CapabilityRequiredView
from tenancy.selectors import scope_to_tenant

from .adjustments import apply_adjustment
from .forms import AdjustmentForm, PaymentForm
from .models import Receivable
from .payments import balance, net_received, record_payment
from .selectors import cash_view, competence_view


class TenantScopedView(CapabilityRequiredView):
    """Financeiro: recebível, pagamento e ajuste.

    O PRD trata financeiro e CRM na mesma linha e a dá aos quatro papéis,
    com escopo próprio para o médico. Escopo por médico não está modelado
    aqui; o que a capacidade garante é que a tela exija vínculo com o papel,
    e não apenas sessão iniciada.
    """

    required_capability = Capability.FINANCE


def _parse_period(request):
    # `localdate()` e nao `date.today()`: o conteiner roda em UTC e o
    # produto em America/Sao_Paulo. Das 21h a meia-noite o UTC ja esta no
    # dia seguinte, e o periodo padrao desta tela abria em 'amanha' --
    # no ultimo dia do mes, ja no mes que vem, com tudo zerado.
    today = timezone.localdate()
    start = request.GET.get('start') or str(today.replace(day=1))
    end = request.GET.get('end') or str(today)
    return datetime.date.fromisoformat(start), datetime.date.fromisoformat(end)


class FinanceOverviewView(TenantScopedView):
    """Competence and cash are two distinct, clearly labeled tables --
    never merged into one number. Only patient name, amounts, dates and
    status are shown here; no chief complaint, HPI, diagnosis or any other
    clinical text ever reaches this template (H-14).
    """

    def get(self, request):
        start, end = _parse_period(request)
        tenant = _tenant(request.access_context.tenant_id)
        receivables = competence_view(tenant, start, end)
        payments = cash_view(tenant, start, end)
        return render(request, 'finance/overview.html', {
            'start': start, 'end': end, 'receivables': receivables, 'payments': payments,
        })


def _tenant(tenant_id):
    from tenancy.models import Tenant

    return Tenant.objects.get(id=tenant_id)


class ReceivableDetailView(TenantScopedView):
    def get(self, request, receivable_id):
        receivable = get_object_or_404(
            scope_to_tenant(Receivable.objects.all(), request.access_context), id=receivable_id,
        )
        return render(request, 'finance/receivable_detail.html', {
            'receivable': receivable, 'balance': balance(receivable), 'net_received': net_received(receivable),
        })


class RecordPaymentView(TenantScopedView):
    def post(self, request, receivable_id):
        receivable = get_object_or_404(
            scope_to_tenant(Receivable.objects.all(), request.access_context), id=receivable_id,
        )
        # O formulario existe porque `except ValueError` nao cobria o caso
        # real: `Decimal('150,00')` levanta `InvalidOperation`, que herda de
        # `ArithmeticError`. A view devolvia 500 para quem digitasse o valor
        # do jeito brasileiro. Ver `finance/forms.py`.
        form = PaymentForm(request.POST)
        if not form.is_valid():
            messages.error(request, next(iter(form.errors.values()))[0])
            return redirect('finance:receivable-detail', receivable_id=receivable.id)
        try:
            record_payment(
                receivable, form.cleaned_data['amount'], form.cleaned_data['method'],
                request.user.id,
                external_reference=form.cleaned_data['external_reference'],
            )
        except ValueError as exc:
            return HttpResponseForbidden(str(exc))
        return redirect('finance:receivable-detail', receivable_id=receivable.id)


class ApplyAdjustmentView(TenantScopedView):
    def post(self, request, receivable_id):
        from tenancy.models import Membership

        receivable = get_object_or_404(
            scope_to_tenant(Receivable.objects.all(), request.access_context), id=receivable_id,
        )
        approved_by = Membership.objects.filter(id=request.access_context.membership_id).first()
        form = AdjustmentForm(request.POST)
        if not form.is_valid():
            messages.error(request, next(iter(form.errors.values()))[0])
            return redirect('finance:receivable-detail', receivable_id=receivable.id)
        payment = None
        if request.POST.get('payment_id'):
            # O pagamento e buscado DENTRO do recebivel: um id de outro
            # recebivel (ou de outra clinica) simplesmente nao casa.
            payment = receivable.payments.filter(id=request.POST['payment_id']).first()
        try:
            apply_adjustment(
                receivable, form.cleaned_data['type'], form.cleaned_data['amount'],
                form.cleaned_data['reason'], approved_by, payment=payment,
            )
        except ValueError as exc:
            return HttpResponseForbidden(str(exc))
        return redirect('finance:receivable-detail', receivable_id=receivable.id)
