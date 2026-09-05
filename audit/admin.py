from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'actor', 'tenant', 'action', 'outcome', 'object_type']
    list_filter = ['outcome', 'tenant']
    search_fields = ['action', 'object_type', 'actor__email']
    readonly_fields = [f.name for f in AuditEvent._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
