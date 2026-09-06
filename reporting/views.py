import datetime

from django.contrib.auth.mixins import LoginRequiredMixin
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View

from tenancy.models import Tenant

from . import operations, patients
from .models import ReportExport, ReportExportKind, ReportExportStatus
from .services import request_export


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


class DashboardView(TenantScopedView):
    """Every number on this page is labeled with its period, unit and n --
    a plain HTML table doubles as its own "tabela alternativa" (RNF-01.09)
    since there is no chart to begin with, consistent with this project's
    established no-JS-by-default UI pattern.
    """

    def get(self, request):
        start, end = _parse_period(request)
        tenant = Tenant.objects.get(id=request.access_context.tenant_id)

        indicators = {
            'active_patients': patients.active_patients_count(tenant),
            'patients_seen': patients.patients_seen(tenant, start, end),
            'new_patients': patients.new_patients_count(tenant, start, end),
            'returning_patients': patients.returning_patients_count(tenant, start, end),
            'no_show': patients.no_show_rate(tenant, start, end),
            'age': patients.age_distribution(tenant, end),
            'location': patients.location_distribution(tenant),
            'revenue_by_competence': operations.revenue_by_competence(tenant, start, end),
            'cash_received': operations.cash_received(tenant, start, end),
            'outstanding_balance': operations.outstanding_balance(tenant, end),
            'doctor_share_forecast': operations.doctor_share_forecast(tenant, start, end),
            'payment_category': operations.payment_category_breakdown(tenant, start, end),
        }
        return render(request, 'reporting/dashboard.html', {'start': start, 'end': end, 'indicators': indicators})


class ExportRequestView(TenantScopedView):
    def post(self, request):
        from tenancy.models import Membership

        membership = Membership.objects.filter(id=request.access_context.membership_id).first()
        report_name = request.POST.get('report_name')
        parameters = {'start': request.POST.get('start'), 'end': request.POST.get('end')}
        export = request_export(request.access_context, membership, report_name, parameters, kind=ReportExportKind.CSV)
        return redirect('reporting:export-detail', export_id=export.id)


class ExportDetailView(TenantScopedView):
    def get(self, request, export_id):
        from tenancy.selectors import scope_to_tenant

        export = get_object_or_404(scope_to_tenant(ReportExport.objects.all(), request.access_context), id=export_id)
        return render(request, 'reporting/export_detail.html', {'export': export})


class ExportDownloadView(TenantScopedView):
    def get(self, request, export_id):
        from tenancy.selectors import scope_to_tenant

        export = get_object_or_404(scope_to_tenant(ReportExport.objects.all(), request.access_context), id=export_id)
        if export.status != ReportExportStatus.READY or not export.storage_key:
            raise Http404
        with open(export.storage_key, 'rb') as fh:
            content = fh.read()
        response = HttpResponse(content, content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{export.report_name}.csv"'
        response['Cache-Control'] = 'private, no-store'
        return response
