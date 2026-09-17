from django.db import models

from base.models import TenantModel


class ChatSessionStatus(models.TextChoices):
    ACTIVE = 'active', 'Ativa'
    ARCHIVED = 'archived', 'Arquivada'


class ChatMessageRole(models.TextChoices):
    USER = 'user', 'Usuário'
    ASSISTANT = 'assistant', 'Assistente'
    SYSTEM = 'system', 'Sistema'


class ChatMessageState(models.TextChoices):
    PENDING = 'pending', 'Pendente'
    STREAMING = 'streaming', 'Transmitindo'
    COMPLETE = 'complete', 'Concluída'
    CANCELLED = 'cancelled', 'Cancelada'
    FAILED = 'failed', 'Falhou'


class ChatSession(TenantModel):
    owner_user = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='chat_sessions')
    patient = models.ForeignKey(
        'patients.Patient', on_delete=models.PROTECT, null=True, blank=True, related_name='chat_sessions',
    )
    title = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=ChatSessionStatus.choices, default=ChatSessionStatus.ACTIVE)
    last_message_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(fields=['tenant', 'owner_user'], name='ai_chatsession_owner_idx'),
        ]

    def __str__(self):
        return self.title or f'session {self.id}'


class ChatMessage(TenantModel):
    session = models.ForeignKey(ChatSession, on_delete=models.PROTECT, related_name='messages')
    role = models.CharField(max_length=20, choices=ChatMessageRole.choices)
    content = models.TextField(max_length=20000, blank=True)
    source_refs = models.JSONField(default=list, blank=True)
    ai_job = models.ForeignKey('ai.AIJob', on_delete=models.PROTECT, null=True, blank=True, related_name='+')
    state = models.CharField(max_length=20, choices=ChatMessageState.choices, default=ChatMessageState.COMPLETE)
    sequence = models.PositiveIntegerField()

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['session', 'sequence'], name='ai_chatmessage_session_sequence_uniq'),
        ]
        ordering = ['sequence']

    def __str__(self):
        return f'{self.session_id}#{self.sequence} ({self.role})'
