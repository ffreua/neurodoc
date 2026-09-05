from django.conf import settings
from django.db import models

from base.models import TimestampedModel


class AuditOutcome(models.TextChoices):
    SUCCESS = 'success', 'Success'
    DENIED = 'denied', 'Denied'
    ERROR = 'error', 'Error'


class AuditEvent(TimestampedModel):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        null=True, blank=True, related_name='audit_events',
    )
    tenant = models.ForeignKey(
        'tenancy.Tenant', on_delete=models.PROTECT, null=True, blank=True,
    )
    action = models.CharField(max_length=255)
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.UUIDField(null=True, blank=True)
    purpose = models.CharField(max_length=255, blank=True)
    outcome = models.CharField(max_length=40, choices=AuditOutcome.choices)
    request_id = models.UUIDField(null=True, blank=True)
    origin_ip_protected = models.CharField(max_length=64, blank=True)
    integrity_metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['tenant', 'created_at']),
            models.Index(fields=['object_type', 'object_id']),
        ]

    def __str__(self):
        return f'{self.action} ({self.outcome})'
