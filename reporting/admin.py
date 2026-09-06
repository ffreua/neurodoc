from django.contrib import admin

from .models import ReportDefinition, ReportExport


@admin.register(ReportDefinition)
class ReportDefinitionAdmin(admin.ModelAdmin):
    list_display = ['name', 'status', 'approved_by', 'approved_at', 'tenant']
    list_filter = ['status', 'tenant']


@admin.register(ReportExport)
class ReportExportAdmin(admin.ModelAdmin):
    list_display = ['report_name', 'kind', 'status', 'row_count', 'expires_at', 'tenant']
    list_filter = ['kind', 'status', 'tenant']
    readonly_fields = ['storage_key']
