from django.db import models

from base.models import TenantModel


class ReportDefinitionStatus(models.TextChoices):
    DRAFT = 'draft', 'Rascunho'
    APPROVED = 'approved', 'Aprovada'
    RETIRED = 'retired', 'Descontinuada'


class ReportDefinition(TenantModel):
    """Governs RF-10.04: an inferential (statistical) report only ever
    exists tied to one of these, fully filled and approved -- there is no
    generic "calculate significance" button anywhere in the product.
    """

    name = models.CharField(max_length=255)
    question = models.TextField()
    population = models.TextField()
    outcome = models.TextField()
    unit_of_analysis = models.CharField(max_length=255)
    repeated_measures_handling = models.TextField(blank=True)
    missing_data_handling = models.TextField(blank=True)
    method = models.TextField()
    assumptions = models.TextField()
    approved_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=ReportDefinitionStatus.choices, default=ReportDefinitionStatus.DRAFT)

    def is_eligible_for_inference(self):
        required_fields = [
            self.question, self.population, self.outcome, self.unit_of_analysis, self.method, self.assumptions,
        ]
        return (
            self.status == ReportDefinitionStatus.APPROVED
            and self.approved_by_id is not None
            and all(field.strip() for field in required_fields)
        )

    def __str__(self):
        return self.name


class ReportExportKind(models.TextChoices):
    CSV = 'csv', 'CSV'
    PDF = 'pdf', 'PDF'


class ReportExportStatus(models.TextChoices):
    QUEUED = 'queued', 'Na fila'
    RUNNING = 'running', 'Processando'
    READY = 'ready', 'Pronta'
    FAILED = 'failed', 'Falhou'
    EXPIRED = 'expired', 'Expirada'


class ReportExport(TenantModel):
    requested_by = models.ForeignKey('tenancy.Membership', on_delete=models.PROTECT, related_name='report_exports')
    kind = models.CharField(max_length=20, choices=ReportExportKind.choices)
    report_name = models.CharField(max_length=100)
    parameters = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=20, choices=ReportExportStatus.choices, default=ReportExportStatus.QUEUED)
    storage_key = models.CharField(max_length=512, blank=True)
    row_count = models.PositiveIntegerField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f'{self.kind}:{self.report_name} ({self.status})'
