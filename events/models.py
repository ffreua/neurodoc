from django.db import models

from base.models import TenantModel, TimestampedModel


class OutboxEventStatus(models.TextChoices):
    PENDING = 'pending', 'Pendente'
    PROCESSING = 'processing', 'Processando'
    COMPLETED = 'completed', 'Concluído'
    FAILED = 'failed', 'Falhou'
    CANCELLED = 'cancelled', 'Cancelado'
    HELD_RESTORED = 'held_restored', 'Retido (restauração)'


class OutboxEvent(TenantModel):
    topic = models.CharField(max_length=100)
    aggregate_type = models.CharField(max_length=100)
    aggregate_id = models.UUIDField()
    event_version = models.PositiveBigIntegerField()
    payload_minimal = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=40, choices=OutboxEventStatus.choices, default=OutboxEventStatus.PENDING)
    available_at = models.DateTimeField()
    locked_until = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['tenant', 'topic', 'aggregate_type', 'aggregate_id', 'event_version'],
                name='events_outboxevent_unique_key',
            ),
        ]
        indexes = [
            models.Index(fields=['status', 'available_at'], name='events_outbox_dispatch_idx'),
        ]

    def __str__(self):
        return f'{self.topic}#{self.aggregate_id}v{self.event_version}'


class ProcessedEvent(TimestampedModel):
    event = models.ForeignKey(OutboxEvent, on_delete=models.PROTECT, related_name='processed_by')
    consumer = models.CharField(max_length=100)
    processed_at = models.DateTimeField()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['event', 'consumer'], name='events_processedevent_unique'),
        ]

    def __str__(self):
        return f'{self.event_id} / {self.consumer}'
