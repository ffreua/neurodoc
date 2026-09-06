from django.db import models

from base.models import TimestampedModel


class CatalogSystem(models.TextChoices):
    CID10 = 'CID10', 'CID-10'
    TUSS = 'TUSS', 'TUSS'


class CatalogReleaseStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    ACTIVE = 'active', 'Active'
    SUPERSEDED = 'superseded', 'Superseded'


class CatalogRelease(TimestampedModel):
    system = models.CharField(max_length=10, choices=CatalogSystem.choices)
    version = models.CharField(max_length=40)
    source_url = models.URLField(max_length=2048, blank=True)
    imported_at = models.DateTimeField(null=True, blank=True)
    content_sha256 = models.CharField(max_length=64, blank=True)
    license_note = models.TextField(max_length=2000, blank=True)
    status = models.CharField(max_length=40, choices=CatalogReleaseStatus.choices, default=CatalogReleaseStatus.DRAFT)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['system', 'version'], name='catalogs_catalogrelease_system_version_uniq'),
        ]

    def __str__(self):
        return f'{self.system} {self.version} ({self.status})'


class DiagnosisCode(TimestampedModel):
    release = models.ForeignKey(CatalogRelease, on_delete=models.PROTECT, related_name='diagnosis_codes')
    code = models.CharField(max_length=20)
    description = models.TextField(max_length=4000)
    parent_code = models.CharField(max_length=20, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['release', 'code'], name='catalogs_diagnosiscode_release_code_uniq'),
        ]

    def __str__(self):
        return f'{self.code} — {self.description[:60]}'


class ProcedureCode(TimestampedModel):
    release = models.ForeignKey(CatalogRelease, on_delete=models.PROTECT, related_name='procedure_codes')
    code = models.CharField(max_length=20)
    description = models.TextField(max_length=4000)
    parent_code = models.CharField(max_length=20, blank=True)
    active = models.BooleanField(default=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['release', 'code'], name='catalogs_procedurecode_release_code_uniq'),
        ]

    def __str__(self):
        return f'{self.code} — {self.description[:60]}'
