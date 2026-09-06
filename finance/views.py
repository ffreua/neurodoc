import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from tenancy.selectors import scope_to_tenant

from .adjustments import apply_adjustment
from .models import AdjustmentType, Receivable
from .payments import balance, net_received, record_payment
from .selectors import cash_view, competence_view


class TenantScopedView(LoginRequiredMixin, View):
    def dispatch(self, request, *args, **kwargs):
        if request.access_context is None:
            raise Http404
        return super().dispatch(request, *args, **kwargs)


def _parse_period(request):
    today = datetime.date.today()
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
        try:
            record_payment(
                receivable, request.POST.get('amount'), request.POST.get('method', 'other'),
                request.user.id, external_reference=request.POST.get('external_reference', ''),
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
        adjustment_type = request.POST.get('type')
        if adjustment_type not in AdjustmentType.values:
            return HttpResponseForbidden('Invalid adjustment type')
        payment = None
        if request.POST.get('payment_id'):
            payment = receivable.payments.filter(id=request.POST['payment_id']).first()
        try:
            apply_adjustment(
                receivable, adjustment_type, request.POST.get('amount'), request.POST.get('reason', ''),
                approved_by, payment=payment,
            )
        except ValueError as exc:
            return HttpResponseForbidden(str(exc))
        return redirect('finance:receivable-detail', receivable_id=receivable.id)
