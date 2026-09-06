from django.contrib import admin

from .models import Attachment, AttachmentOcrPage


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ['original_name', 'patient', 'classification', 'scan_status', 'bytes', 'tenant']
    list_filter = ['scan_status', 'classification', 'tenant']
    search_fields = ['original_name', 'patient__full_name']
    readonly_fields = ['sha256', 'storage_key']


@admin.register(AttachmentOcrPage)
class AttachmentOcrPageAdmin(admin.ModelAdmin):
    list_display = ['attachment', 'page_number', 'engine']
