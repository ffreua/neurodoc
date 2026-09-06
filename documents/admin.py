from django.contrib import admin

from .models import Attachment, AttachmentOcrPage, MedicalDocument, SigningCredential, SigningSession


@admin.register(Attachment)
class AttachmentAdmin(admin.ModelAdmin):
    list_display = ['original_name', 'patient', 'classification', 'scan_status', 'bytes', 'tenant']
    list_filter = ['scan_status', 'classification', 'tenant']
    search_fields = ['original_name', 'patient__full_name']
    readonly_fields = ['sha256', 'storage_key']


@admin.register(AttachmentOcrPage)
class AttachmentOcrPageAdmin(admin.ModelAdmin):
    list_display = ['attachment', 'page_number', 'engine']


@admin.register(MedicalDocument)
class MedicalDocumentAdmin(admin.ModelAdmin):
    list_display = ['document_number', 'kind', 'status', 'version', 'patient', 'physician', 'tenant']
    list_filter = ['kind', 'status', 'tenant']
    search_fields = ['document_number', 'patient__full_name']
    readonly_fields = ['signature_metadata', 'content_snapshot']


@admin.register(SigningCredential)
class SigningCredentialAdmin(admin.ModelAdmin):
    list_display = ['certificate_serial', 'physician', 'status', 'not_before', 'not_after', 'tenant']
    list_filter = ['status', 'tenant']
    readonly_fields = ['ciphertext_path', 'wrapped_key_metadata', 'certificate_fingerprint']


@admin.register(SigningSession)
class SigningSessionAdmin(admin.ModelAdmin):
    list_display = ['physician', 'duration_hours', 'expires_at', 'revoked_at', 'tenant']
    list_filter = ['tenant']
    readonly_fields = ['encrypted_unlock_material', 'ephemeral_key_id', 'session_binding_hash']
