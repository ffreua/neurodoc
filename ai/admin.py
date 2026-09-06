from django.contrib import admin

from .models import AIArtifact, AIJob


@admin.register(AIJob)
class AIJobAdmin(admin.ModelAdmin):
    list_display = ['kind', 'status', 'patient', 'encounter', 'user', 'tenant']
    list_filter = ['kind', 'status', 'tenant']
    readonly_fields = ['source_hash', 'idempotency_key']


@admin.register(AIArtifact)
class AIArtifactAdmin(admin.ModelAdmin):
    list_display = ['job', 'provider', 'model', 'review_state', 'stale', 'tenant']
    list_filter = ['provider', 'review_state', 'stale', 'tenant']
    readonly_fields = ['result', 'source_refs']
