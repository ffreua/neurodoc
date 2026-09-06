from django.contrib import admin

from .models import OutboxEvent, ProcessedEvent


@admin.register(OutboxEvent)
class OutboxEventAdmin(admin.ModelAdmin):
    list_display = ['topic', 'aggregate_type', 'aggregate_id', 'event_version', 'status', 'available_at']
    list_filter = ['status', 'topic']

    def has_add_permission(self, request):
        return False


@admin.register(ProcessedEvent)
class ProcessedEventAdmin(admin.ModelAdmin):
    list_display = ['event', 'consumer', 'processed_at']

    def has_add_permission(self, request):
        return False
