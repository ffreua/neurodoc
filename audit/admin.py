from django.contrib import admin

from .models import AuditEvent


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ['created_at', 'actor', 'tenant', 'action', 'outcome', 'object_type']
    list_filter = ['outcome', 'tenant']
    search_fields = ['action', 'object_type', 'actor__email']
    # Os metadados ficam fora da tela do admin. Eventos antigos guardaram
    # nome de medicamento, de exame e escore de escala, e a trilha é imutável
    # (trigger), então não há como limpá-los; o que dá é não exibi-los a quem
    # opera o servidor, que lê prontuário só com vínculo (auditoria externa
    # de 2026-11-20, e `base.admin.SemConteudoClinicoAdmin`).
    exclude = ['integrity_metadata']
    readonly_fields = [f.name for f in AuditEvent._meta.fields if f.name != 'integrity_metadata']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
