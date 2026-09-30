import datetime

from django.contrib import messages
from django.db.models import Q
from django.http import Http404, HttpResponse, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from tenancy.permissions import Capability, CapabilityRequiredView
from tenancy.selectors import scope_to_tenant

from .adjustments import apply_adjustment
from .exports import (
    CASH_COLUMNS,
    COMPETENCE_COLUMNS,
    cash_rows,
    competence_rows,
    render_excel_csv,
)
from .forms import AdjustmentForm, DeleteFinancialHistoryForm, FiscalDocumentForm, PaymentForm
from .lifecycle import (
    archive_all_financial_history,
    can_manage_financial_history,
    delete_all_financial_history,
    mark_doctor_share_paid,
    restore_all_financial_history,
    undo_doctor_share_paid,
    update_fiscal_document_number,
)
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
            'can_manage_history': can_manage_financial_history(request.access_context),
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
            'can_manage_history': can_manage_financial_history(request.access_context),
        })


def _membership(request):
    from tenancy.models import Membership

    return Membership.objects.get(
        id=request.access_context.membership_id,
        tenant_id=request.access_context.tenant_id,
    )


class FinancialHistoryManagerView(TenantScopedView):
    """Ações de fechamento ficam fora da operação da secretaria/médico."""

    def dispatch(self, request, *args, **kwargs):
        if not can_manage_financial_history(request.access_context):
            raise Http404
        return super().dispatch(request, *args, **kwargs)


class FiscalDocumentUpdateView(TenantScopedView):
    def post(self, request, receivable_id):
        receivable = get_object_or_404(
            scope_to_tenant(Receivable.objects.all(), request.access_context), id=receivable_id,
        )
        form = FiscalDocumentForm(request.POST)
        if not form.is_valid():
            messages.error(request, next(iter(form.errors.values()))[0])
            return redirect('finance:receivable-detail', receivable_id=receivable.id)
        update_fiscal_document_number(
            receivable, form.cleaned_data['fiscal_document_number'], request.user.id,
        )
        messages.success(request, 'Número do documento fiscal salvo.')
        return redirect('finance:receivable-detail', receivable_id=receivable.id)


class _CSVExportView(TenantScopedView):
    filename_prefix = None
    columns = None

    def rows(self, tenant, start, end):
        raise NotImplementedError

    def get(self, request):
        start, end = _parse_period(request)
        tenant = _tenant(request.access_context.tenant_id)
        response = HttpResponse(
            render_excel_csv(self.rows(tenant, start, end), self.columns),
            content_type='text/csv; charset=utf-8',
        )
        filename = f'{self.filename_prefix}-{start.isoformat()}-a-{end.isoformat()}.csv'
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Cache-Control'] = 'private, no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        return response


class CompetenceExportView(_CSVExportView):
    filename_prefix = 'competencia'
    columns = COMPETENCE_COLUMNS

    def rows(self, tenant, start, end):
        return competence_rows(competence_view(tenant, start, end))


class CashExportView(_CSVExportView):
    filename_prefix = 'caixa'
    columns = CASH_COLUMNS

    def rows(self, tenant, start, end):
        return cash_rows(cash_view(tenant, start, end))


class MarkDoctorSharePaidView(FinancialHistoryManagerView):
    def post(self, request, receivable_id):
        receivable = get_object_or_404(
            scope_to_tenant(Receivable.objects.all(), request.access_context), id=receivable_id,
        )
        try:
            mark_doctor_share_paid(receivable, _membership(request))
        except ValueError as exc:
            messages.error(request, str(exc))
            return redirect('finance:receivable-detail', receivable_id=receivable.id)
        messages.success(request, 'Repasse marcado como realizado.')
        return redirect('finance:overview')


class UndoDoctorSharePaidView(FinancialHistoryManagerView):
    def post(self, request, receivable_id):
        receivable = get_object_or_404(
            scope_to_tenant(Receivable.objects.all(), request.access_context), id=receivable_id,
        )
        undo_doctor_share_paid(receivable, _membership(request))
        messages.success(request, 'Repasse reaberto e devolvido ao financeiro.')
        return redirect('finance:history')


def _history_context(request, *, delete_form=None, archive_error=''):
    tenant = _tenant(request.access_context.tenant_id)
    withdrawn = (
        Receivable.objects.filter(tenant=tenant)
        .filter(Q(archived_at__isnull=False) | Q(doctor_share_paid_at__isnull=False))
        .select_related('patient', 'archived_by__user', 'doctor_share_paid_by__user')
        .order_by('-archived_at', '-doctor_share_paid_at', '-updated_at')[:200]
    )
    return {
        'withdrawn_receivables': withdrawn,
        'archived_count': Receivable.objects.filter(
            tenant=tenant, archived_at__isnull=False,
        ).count(),
        'active_count': Receivable.objects.filter(
            tenant=tenant, archived_at__isnull=True,
        ).count(),
        'delete_form': delete_form or DeleteFinancialHistoryForm(),
        'archive_error': archive_error,
    }


class FinancialHistoryView(FinancialHistoryManagerView):
    def get(self, request):
        return render(request, 'finance/history.html', _history_context(request))


class ArchiveFinancialHistoryView(FinancialHistoryManagerView):
    def post(self, request):
        if (request.POST.get('confirmation') or '').strip() != 'ARQUIVAR':
            return render(
                request, 'finance/history.html',
                _history_context(request, archive_error='Digite ARQUIVAR exatamente como mostrado.'),
                status=400,
            )
        count = archive_all_financial_history(
            _tenant(request.access_context.tenant_id), _membership(request),
        )
        messages.success(request, f'{count} cobrança(s) arquivada(s).')
        return redirect('finance:history')


class RestoreFinancialHistoryView(FinancialHistoryManagerView):
    def post(self, request):
        count = restore_all_financial_history(
            _tenant(request.access_context.tenant_id), _membership(request),
        )
        messages.success(request, f'{count} cobrança(s) restaurada(s).')
        return redirect('finance:history')


class DeleteFinancialHistoryView(FinancialHistoryManagerView):
    def post(self, request):
        form = DeleteFinancialHistoryForm(request.POST)
        if not form.is_valid():
            return render(
                request, 'finance/history.html',
                _history_context(request, delete_form=form),
                status=400,
            )
        counts = delete_all_financial_history(
            _tenant(request.access_context.tenant_id), _membership(request),
        )
        messages.success(
            request,
            f'Histórico apagado: {counts["receivables"]} cobrança(s), '
            f'{counts["payments"]} pagamento(s) e {counts["adjustments"]} ajuste(s).',
        )
        return redirect('finance:overview')


class RecordPaymentView(TenantScopedView):
    def post(self, request, receivable_id):
        receivable = get_object_or_404(
            scope_to_tenant(Receivable.objects.all(), request.access_context), id=receivable_id,
        )
        if receivable.archived_at or receivable.doctor_share_paid_at:
            return HttpResponseForbidden('Cobrança retirada do financeiro não aceita novos pagamentos.')
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
        if receivable.archived_at or receivable.doctor_share_paid_at:
            return HttpResponseForbidden('Cobrança retirada do financeiro não aceita novos ajustes.')
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
