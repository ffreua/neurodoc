from django.db import models
from django.db.models import Q

from base.models import TenantModel

MAX_ATTACHMENT_BYTES = 25 * 1024 * 1024
MAX_ATTACHMENT_PAGES = 100
ALLOWED_EXTENSIONS = {'pdf', 'jpg', 'jpeg', 'png', 'tiff', 'tif', 'docx'}


class AttachmentClassification(models.TextChoices):
    CLINICAL = 'clinical', 'Clínico'
    ADMINISTRATIVE = 'administrative', 'Administrativo'


class AttachmentScanStatus(models.TextChoices):
    QUARANTINED = 'quarantined', 'Em quarentena'
    AVAILABLE = 'available', 'Liberado'
    REJECTED = 'rejected', 'Recusado'


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


class MedicalDocumentKind(models.TextChoices):
    PRESCRIPTION = 'prescription', 'Receita'
    REPORT = 'report', 'Relatório'
    REQUEST = 'request', 'Pedido de exame'
    REFERRAL = 'referral', 'Encaminhamento'


class MedicalDocumentStatus(models.TextChoices):
    DRAFT = 'draft', 'Rascunho'
    READY_TO_SIGN = 'ready_to_sign', 'Pronto para assinar'
    SIGNING = 'signing', 'Assinando'
    ISSUED = 'issued', 'Emitido'
    FAILED = 'failed', 'Falhou'


class MedicalDocument(TenantModel):
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='medical_documents')
    encounter = models.ForeignKey(
        'clinical.Encounter', on_delete=models.PROTECT, related_name='medical_documents',
    )
    physician = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, related_name='medical_documents',
    )
    document_number = models.CharField(max_length=64, blank=True)
    version = models.PositiveIntegerField(default=1)
    kind = models.CharField(max_length=40, choices=MedicalDocumentKind.choices)
    template_version = models.CharField(max_length=20, default='v1')
    content_snapshot = models.JSONField(default=dict, blank=True)
    pdf_attachment = models.ForeignKey(
        Attachment, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    signed_pdf_attachment = models.ForeignKey(
        Attachment, on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    status = models.CharField(max_length=40, choices=MedicalDocumentStatus.choices, default=MedicalDocumentStatus.DRAFT)
    issued_at = models.DateTimeField(null=True, blank=True)
    signature_metadata = models.JSONField(default=dict, blank=True)
    replaces_document = models.ForeignKey(
        'self', on_delete=models.SET_NULL, null=True, blank=True, related_name='replaced_by',
    )

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['tenant', 'document_number'], condition=~Q(document_number=''),
                name='documents_medicaldocument_number_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['tenant', 'patient'], name='documents_meddoc_patient_idx'),
        ]

    def __str__(self):
        return self.document_number or f'{self.kind} draft ({self.id})'


class SigningCredentialStatus(models.TextChoices):
    ACTIVE = 'active', 'Ativo'
    EXPIRED = 'expired', 'Expirado'
    REVOKED = 'revoked', 'Revogado'


class SigningCredential(TenantModel):
    physician = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, related_name='signing_credentials',
    )
    ciphertext_path = models.CharField(max_length=512)
    wrapped_key_metadata = models.JSONField(default=dict)
    certificate_serial = models.CharField(max_length=64)
    certificate_fingerprint = models.CharField(max_length=64)
    issuer = models.CharField(max_length=255)
    not_before = models.DateTimeField()
    not_after = models.DateTimeField()
    status = models.CharField(
        max_length=40, choices=SigningCredentialStatus.choices, default=SigningCredentialStatus.ACTIVE,
    )

    def __str__(self):
        return f'{self.certificate_serial} ({self.status})'


class SigningSession(TenantModel):
    physician = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, related_name='signing_sessions',
    )
    credential = models.ForeignKey(SigningCredential, on_delete=models.PROTECT, related_name='sessions')
    duration_hours = models.PositiveSmallIntegerField()
    expires_at = models.DateTimeField()
    revoked_at = models.DateTimeField(null=True, blank=True)
    mfa_at = models.DateTimeField()
    session_binding_hash = models.CharField(max_length=64)
    encrypted_unlock_material = models.TextField()
    ephemeral_key_id = models.UUIDField()

    def __str__(self):
        return f'session {self.id} ({self.physician_id})'
