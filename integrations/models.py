from django.db import models

from base.models import TenantModel


class CaptureDeviceStatus(models.TextChoices):
    PENDING = 'pending', 'Aguardando pareamento'
    PAIRED = 'paired', 'Pareado'
    REVOKED = 'revoked', 'Revogado'


class CaptureSessionStatus(models.TextChoices):
    OPEN = 'open', 'Aberta'
    CLOSED = 'closed', 'Encerrada'
    EXPIRED = 'expired', 'Expirada'


class CaptureDevice(TenantModel):
    name = models.CharField(max_length=255)
    paired_by = models.ForeignKey('tenancy.Membership', on_delete=models.PROTECT, related_name='+')
    pairing_code_hash = models.CharField(max_length=255, blank=True)
    api_key_hash = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=CaptureDeviceStatus.choices, default=CaptureDeviceStatus.PENDING)
    paired_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.name} ({self.status})'


class CaptureSession(TenantModel):
    device = models.ForeignKey(CaptureDevice, on_delete=models.PROTECT, related_name='sessions')
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='capture_sessions')
    encounter = models.ForeignKey(
        'clinical.Encounter', on_delete=models.PROTECT, null=True, blank=True, related_name='capture_sessions',
    )
    opened_by = models.ForeignKey('tenancy.Membership', on_delete=models.PROTECT, related_name='+')
    token_hash = models.CharField(max_length=64)
    status = models.CharField(max_length=20, choices=CaptureSessionStatus.choices, default=CaptureSessionStatus.OPEN)
    expires_at = models.DateTimeField()
    page_count = models.PositiveIntegerField(default=0)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['token_hash'], name='capture_session_token_uniq'),
        ]

    def __str__(self):
        return f'capture session for {self.patient_id} ({self.status})'


class CaptureUploadRecord(TenantModel):
    """Hash/order provenance per page -- exists specifically so a repeated
    upload (same bytes) or an out-of-order page never attaches silently:
    the receiver checks this table before ever touching Attachment.
    """
    session = models.ForeignKey(CaptureSession, on_delete=models.PROTECT, related_name='upload_records')
    sha256 = models.CharField(max_length=64)
    page_number = models.PositiveIntegerField()
    attachment = models.ForeignKey('documents.Attachment', on_delete=models.PROTECT, related_name='+')

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['session', 'sha256'], name='capture_upload_hash_uniq'),
        ]

    def __str__(self):
        return f'{self.session_id} page {self.page_number}'
