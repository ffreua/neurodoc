from django.contrib import admin

from base.admin import SemConteudoClinicoAdmin

from .chat_models import ChatMessage, ChatSession
from .models import AIArtifact, AIJob


@admin.register(AIJob)
class AIJobAdmin(SemConteudoClinicoAdmin):
    list_display = ['kind', 'status', 'patient', 'encounter', 'user', 'tenant']
    list_filter = ['kind', 'status', 'tenant']
    readonly_fields = ['source_hash', 'idempotency_key']


@admin.register(AIArtifact)
class AIArtifactAdmin(SemConteudoClinicoAdmin):
    list_display = ['job', 'provider', 'model', 'review_state', 'stale', 'tenant']
    list_filter = ['provider', 'review_state', 'stale', 'tenant']
    readonly_fields = ['result', 'source_refs']


@admin.register(ChatSession)
class ChatSessionAdmin(SemConteudoClinicoAdmin):
    list_display = ['title', 'owner_user', 'patient', 'status', 'last_message_at', 'tenant']
    list_filter = ['status', 'tenant']


@admin.register(ChatMessage)
class ChatMessageAdmin(SemConteudoClinicoAdmin):
    list_display = ['session', 'sequence', 'role', 'state', 'tenant']
    list_filter = ['role', 'state', 'tenant']
