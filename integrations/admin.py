from django.contrib import admin

from .models import CaptureDevice, CaptureSession, CaptureUploadRecord


@admin.register(CaptureDevice)
class CaptureDeviceAdmin(admin.ModelAdmin):
    """Proveniência histórica da captura local descontinuada."""

    list_display = ['name', 'status', 'paired_by', 'paired_at', 'tenant']
    list_filter = ['status', 'tenant']
    readonly_fields = ['pairing_code_hash', 'api_key_hash']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CaptureSession)
class CaptureSessionAdmin(admin.ModelAdmin):
    list_display = ['patient', 'device', 'status', 'page_count', 'expires_at', 'tenant']
    list_filter = ['status', 'tenant']
    readonly_fields = ['token_hash']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CaptureUploadRecord)
class CaptureUploadRecordAdmin(admin.ModelAdmin):
    list_display = ['session', 'page_number', 'attachment', 'tenant']
    readonly_fields = ['sha256']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
