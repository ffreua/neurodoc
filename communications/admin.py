from django.contrib import admin

from .models import Delivery, DeliveryAttempt, DocumentAccessToken


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ['channel', 'status', 'contact', 'document', 'appointment', 'tenant']
    list_filter = ['channel', 'status', 'tenant']
    readonly_fields = ['idempotency_key', 'provider_id']


@admin.register(DeliveryAttempt)
class DeliveryAttemptAdmin(admin.ModelAdmin):
    list_display = ['delivery', 'attempt_number', 'outcome', 'started_at']
    list_filter = ['outcome', 'tenant']


@admin.register(DocumentAccessToken)
class DocumentAccessTokenAdmin(admin.ModelAdmin):
    list_display = ['document', 'contact', 'expires_at', 'revoked_at', 'last_access_at', 'tenant']
    readonly_fields = ['token_hash', 'otp_hash']
