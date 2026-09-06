from django.contrib import admin

from .models import CaptureDevice, CaptureSession, CaptureUploadRecord


@admin.register(CaptureDevice)
class CaptureDeviceAdmin(admin.ModelAdmin):
    list_display = ['name', 'status', 'paired_by', 'paired_at', 'tenant']
    list_filter = ['status', 'tenant']
    readonly_fields = ['pairing_code_hash', 'api_key_hash']


@admin.register(CaptureSession)
class CaptureSessionAdmin(admin.ModelAdmin):
    list_display = ['patient', 'device', 'status', 'page_count', 'expires_at', 'tenant']
    list_filter = ['status', 'tenant']
    readonly_fields = ['token_hash']


@admin.register(CaptureUploadRecord)
class CaptureUploadRecordAdmin(admin.ModelAdmin):
    list_display = ['session', 'page_number', 'attachment', 'tenant']
    readonly_fields = ['sha256']
