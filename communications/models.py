from django.db import models
from django.db.models import Q

from base.models import TenantModel


class DeliveryChannel(models.TextChoices):
    EMAIL = 'email', 'Email'
    SMS = 'sms', 'SMS'


class DeliveryStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    ACCEPTED = 'accepted', 'Accepted'
    DELIVERED = 'delivered', 'Delivered'
    UNKNOWN = 'unknown', 'Unknown'
    FAILED = 'failed', 'Failed'
    NO_CONTACT = 'no_contact', 'No contact'


class DeliveryAttemptOutcome(models.TextChoices):
    ACCEPTED = 'accepted', 'Accepted'
    DELIVERED = 'delivered', 'Delivered'
    UNKNOWN = 'unknown', 'Unknown'
    FAILED = 'failed', 'Failed'


class Delivery(TenantModel):
    document = models.ForeignKey(
        'documents.MedicalDocument', on_delete=models.PROTECT, null=True, blank=True, related_name='deliveries',
    )
    appointment = models.ForeignKey(
        'scheduling.Appointment', on_delete=models.PROTECT, null=True, blank=True, related_name='deliveries',
    )
    contact = models.ForeignKey('patients.PatientContact', on_delete=models.PROTECT, related_name='deliveries')
    channel = models.CharField(max_length=20, choices=DeliveryChannel.choices)
    event_version = models.PositiveBigIntegerField()
    status = models.CharField(max_length=20, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING)
    provider_id = models.CharField(max_length=100, blank=True)
    idempotency_key = models.CharField(max_length=100)
    next_attempt_at = models.DateTimeField(null=True, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant', 'idempotency_key'], name='communications_delivery_idem_uniq'),
            models.CheckConstraint(
                condition=(
                    Q(document__isnull=False, appointment__isnull=True)
                    | Q(document__isnull=True, appointment__isnull=False)
                ),
                name='communications_delivery_single_target',
            ),
        ]

    def __str__(self):
        return f'{self.channel}:{self.contact_id} ({self.status})'


class DeliveryAttempt(TenantModel):
    delivery = models.ForeignKey(Delivery, on_delete=models.PROTECT, related_name='attempts')
    attempt_number = models.PositiveIntegerField()
    started_at = models.DateTimeField()
    ended_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=20, choices=DeliveryAttemptOutcome.choices)
    provider_code = models.CharField(max_length=100, blank=True)
    sanitized_error = models.CharField(max_length=255, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['delivery', 'attempt_number'], name='communications_deliveryattempt_unique',
            ),
        ]

    def __str__(self):
        return f'{self.delivery_id}#{self.attempt_number} ({self.outcome})'


class DocumentAccessToken(TenantModel):
    document = models.ForeignKey('documents.MedicalDocument', on_delete=models.PROTECT, related_name='access_tokens')
    contact = models.ForeignKey('patients.PatientContact', on_delete=models.PROTECT, related_name='+')
    token_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    last_access_at = models.DateTimeField(null=True, blank=True)
    otp_hash = models.CharField(max_length=255, blank=True)
    otp_expires_at = models.DateTimeField(null=True, blank=True)
    otp_attempts = models.PositiveSmallIntegerField(default=0)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['token_hash'], name='communications_accesstoken_hash_uniq'),
        ]

    def __str__(self):
        return f'token for document {self.document_id}'
