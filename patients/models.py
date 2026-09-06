from django.core.exceptions import ValidationError
from django.db import models
from django.db.models.functions import Lower

from base.models import TenantModel
from base.validators import is_valid_cpf


class SexAtRegistration(models.TextChoices):
    FEMALE = 'female', 'Feminino'
    MALE = 'male', 'Masculino'
    INTERSEX = 'intersex', 'Intersexo'
    NOT_INFORMED = 'not_informed', 'Não informado'


class MaritalStatus(models.TextChoices):
    SINGLE = 'single', 'Solteiro(a)'
    MARRIED = 'married', 'Casado(a)'
    STABLE_UNION = 'stable_union', 'União estável'
    DIVORCED = 'divorced', 'Divorciado(a)'
    WIDOWED = 'widowed', 'Viúvo(a)'
    OTHER = 'other', 'Outro'
    NOT_INFORMED = 'not_informed', 'Não informado'


class ReferralSource(models.TextChoices):
    PATIENT = 'patient', 'Paciente'
    PHYSICIAN = 'physician', 'Médico'
    INTERNET = 'internet', 'Internet'
    PLAN = 'plan', 'Plano'
    OTHER = 'other', 'Outro'
    NOT_INFORMED = 'not_informed', 'Não informado'


class PaymentCategory(models.TextChoices):
    PRIVATE = 'private', 'Particular'
    PLAN = 'plan', 'Plano'


class PatientStatus(models.TextChoices):
    ACTIVE = 'active', 'Active'
    ARCHIVED = 'archived', 'Archived'


class Insurer(TenantModel):
    name = models.CharField(max_length=255)
    ans_registration = models.CharField(max_length=40, blank=True)
    active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class HealthPlan(TenantModel):
    insurer = models.ForeignKey(Insurer, on_delete=models.PROTECT, related_name='plans')
    name = models.CharField(max_length=255)
    active = models.BooleanField(default=True)
    administrative_notes = models.TextField(max_length=2000, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(fields=['tenant', 'insurer', 'name'], name='patients_healthplan_tenant_insurer_name_uniq'),
        ]

    def __str__(self):
        return f'{self.insurer.name} — {self.name}'


class Patient(TenantModel):
    full_name = models.CharField(max_length=255)
    birth_date = models.DateField(null=True, blank=True)
    birth_date_unknown_reason = models.CharField(max_length=255, blank=True)
    estimated_birth_year = models.PositiveSmallIntegerField(null=True, blank=True)
    sex_at_registration = models.CharField(
        max_length=40, choices=SexAtRegistration.choices, default=SexAtRegistration.NOT_INFORMED,
    )
    cpf = models.CharField(max_length=11, null=True, blank=True)
    identity_number = models.CharField(max_length=30, blank=True)
    mother_name = models.CharField(max_length=255, blank=True)
    postal_code = models.CharField(max_length=8, blank=True)
    street = models.CharField(max_length=255, blank=True)
    number = models.CharField(max_length=30, blank=True)
    complement = models.CharField(max_length=100, blank=True)
    district = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=2, blank=True)
    country = models.CharField(max_length=2, default='BR')
    address_source = models.CharField(max_length=40, blank=True)
    referral_source = models.CharField(
        max_length=40, choices=ReferralSource.choices, default=ReferralSource.NOT_INFORMED,
    )
    referral_details = models.CharField(max_length=255, blank=True)
    marital_status = models.CharField(
        max_length=40, choices=MaritalStatus.choices, default=MaritalStatus.NOT_INFORMED,
    )
    occupation = models.CharField(max_length=150, blank=True)
    payment_category = models.CharField(max_length=40, choices=PaymentCategory.choices, default=PaymentCategory.PRIVATE)
    active_coverage = models.ForeignKey(
        'patients.PatientCoverage', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    responsible_membership = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, null=True, blank=True, related_name='responsible_patients',
    )
    administrative_notes = models.TextField(max_length=2000, blank=True)
    status = models.CharField(max_length=40, choices=PatientStatus.choices, default=PatientStatus.ACTIVE)
    archived_at = models.DateTimeField(null=True, blank=True)
    archived_reason = models.CharField(max_length=255, blank=True)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['tenant', 'cpf'], name='patients_patient_tenant_cpf_uniq',
                condition=models.Q(cpf__isnull=False),
            ),
        ]
        indexes = [
            models.Index(Lower('full_name'), name='patients_patient_name_idx'),
        ]

    def clean(self):
        if self.cpf and not is_valid_cpf(self.cpf):
            raise ValidationError({'cpf': 'Invalid CPF'})
        if not self.birth_date and not self.birth_date_unknown_reason and not self.estimated_birth_year:
            raise ValidationError({'birth_date': 'Provide a birth date or a reason it is unknown'})

    def __str__(self):
        return self.full_name


class PatientContact(TenantModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='contacts')
    name = models.CharField(max_length=255)
    relationship = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=16, blank=True)
    email = models.EmailField(max_length=254, blank=True)
    verified_phone_at = models.DateTimeField(null=True, blank=True)
    verified_email_at = models.DateTimeField(null=True, blank=True)
    authorized_for_documents = models.BooleanField(default=False)
    sms_enabled = models.BooleanField(default=False)
    email_enabled = models.BooleanField(default=False)
    valid_until = models.DateTimeField(null=True, blank=True)
    legal_authority = models.BooleanField(default=False)
    authority_evidence = models.CharField(max_length=255, blank=True)

    def clean(self):
        if not self.phone and not self.email:
            raise ValidationError('A contact needs a phone or an e-mail')
        if self.authorized_for_documents and not self.relationship:
            raise ValidationError({'relationship': 'A delivery contact needs a registered relationship'})
        if self.legal_authority and not self.authority_evidence:
            raise ValidationError({'authority_evidence': 'Legal authority needs a registered evidence note'})

    def __str__(self):
        return f'{self.name} ({self.relationship or "contact"})'


class ObservationKind(models.TextChoices):
    WEIGHT = 'weight', 'Weight'
    HEIGHT = 'height', 'Height'


class Observation(TenantModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='observations')
    kind = models.CharField(max_length=40, choices=ObservationKind.choices)
    numeric_value = models.DecimalField(max_digits=6, decimal_places=2)
    unit = models.CharField(max_length=16)
    observed_at = models.DateTimeField()
    source = models.CharField(max_length=40, default='manual')

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(fields=['tenant', 'patient', 'kind', 'observed_at'], name='patients_obs_lookup_idx'),
        ]

    def clean(self):
        if self.numeric_value is not None and self.numeric_value <= 0:
            raise ValidationError({'numeric_value': 'Must be positive'})

    def __str__(self):
        return f'{self.kind}={self.numeric_value}{self.unit}'


class PatientCoverage(TenantModel):
    patient = models.ForeignKey(Patient, on_delete=models.PROTECT, related_name='coverages')
    plan = models.ForeignKey(HealthPlan, on_delete=models.PROTECT, related_name='coverages')
    member_number = models.CharField(max_length=60, blank=True)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)

    def clean(self):
        if self.starts_on and self.ends_on and self.ends_on < self.starts_on:
            raise ValidationError({'ends_on': 'End date cannot precede start date'})

    def __str__(self):
        return f'{self.patient_id} -> {self.plan_id}'
