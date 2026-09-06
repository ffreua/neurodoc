from django.db import models

from base.models import TenantModel

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_ATTACHMENT_PAGES = 100
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'tiff', 'tif', 'docx'}


class AttachmentClassification(models.TextChoices):
    CLINICAL = 'clinical', 'Clinical'
    ADMINISTRATIVE = 'administrative', 'Administrative'


class AttachmentScanStatus(models.TextChoices):
    QUARANTINED = 'quarantined', 'Quarantined'
    AVAILABLE = 'available', 'Available'
    REJECTED = 'rejected', 'Rejected'


class Attachment(TenantModel):
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='attachments')
    encounter = models.ForeignKey(
        'clinical.Encounter', on_delete=models.SET_NULL, null=True, blank=True, related_name='attachments',
    )
    storage_key = models.CharField(max_length=512, blank=True)
    original_name = models.CharField(max_length=255)
    mime = models.CharField(max_length=100)
    bytes = models.PositiveBigIntegerField()
    page_count = models.PositiveIntegerField(null=True, blank=True)
    sha256 = models.CharField(max_length=64)
    classification = models.CharField(max_length=40, choices=AttachmentClassification.choices)
    scan_status = models.CharField(
        max_length=40, choices=AttachmentScanStatus.choices, default=AttachmentScanStatus.QUARANTINED,
    )
    scan_error = models.CharField(max_length=255, blank=True)
    uploaded_by = models.ForeignKey('accounts.User', on_delete=models.PROTECT, related_name='+')
    document_date = models.DateField(null=True, blank=True)
    encryption_metadata = models.JSONField(default=dict, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_reason = models.CharField(max_length=255, blank=True)

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(fields=['tenant', 'patient'], name='documents_attach_patient_idx'),
        ]

    def __str__(self):
        return f'{self.original_name} ({self.scan_status})'


class AttachmentOcrPage(TenantModel):
    attachment = models.ForeignKey(Attachment, on_delete=models.PROTECT, related_name='ocr_pages')
    page_number = models.PositiveIntegerField()
    text = models.TextField(max_length=50000, blank=True)
    engine = models.CharField(max_length=40, default='tesseract')

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['attachment', 'page_number'], name='documents_ocrpage_unique_page'),
        ]

    def __str__(self):
        return f'{self.attachment_id} p{self.page_number}'
