from django.contrib import admin

from .models import CatalogRelease, DiagnosisCode, ProcedureCode


@admin.register(CatalogRelease)
class CatalogReleaseAdmin(admin.ModelAdmin):
    list_display = ['system', 'version', 'status', 'imported_at']
    list_filter = ['system', 'status']

    def has_add_permission(self, request):
        return False


@admin.register(DiagnosisCode)
class DiagnosisCodeAdmin(admin.ModelAdmin):
    list_display = ['code', 'description', 'release', 'active']
    search_fields = ['code', 'description']
    list_filter = ['release']

    def has_add_permission(self, request):
        return False


@admin.register(ProcedureCode)
class ProcedureCodeAdmin(admin.ModelAdmin):
    list_display = ['code', 'description', 'release', 'active']
    search_fields = ['code', 'description']
    list_filter = ['release']

    def has_add_permission(self, request):
        return False
