import hashlib

from django.core.exceptions import ValidationError
from django.db import models

from base.models import TenantModel


class EncounterStatus(models.TextChoices):
    DRAFT = 'draft', 'Draft'
    IN_PROGRESS = 'in_progress', 'In progress'
    FINALIZED = 'finalized', 'Finalized'


class ConsanguinityState(models.TextChoices):
    NONE = 'none', 'None'
    SUSPECTED = 'suspected', 'Suspected'
    CONFIRMED = 'confirmed', 'Confirmed'
    NOT_INFORMED = 'not_informed', 'Not informed'


class Encounter(TenantModel):
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='encounters')
    physician_membership = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, related_name='encounters',
    )
    appointment = models.ForeignKey(
        'scheduling.Appointment', on_delete=models.SET_NULL, null=True, blank=True, related_name='encounters',
    )
    occurred_at = models.DateTimeField()
    chief_complaint = models.TextField(max_length=20000, blank=True)
    hpi = models.TextField(max_length=20000, blank=True)
    personal_history = models.TextField(max_length=20000, blank=True)
    family_history = models.TextField(max_length=20000, blank=True)
    consanguinity_state = models.CharField(
        max_length=40, choices=ConsanguinityState.choices, default=ConsanguinityState.NOT_INFORMED,
    )
    consanguinity_details = models.TextField(max_length=2000, blank=True)
    plan_text = models.TextField(max_length=20000, blank=True)
    finalization_justification = models.CharField(max_length=500, blank=True)
    status = models.CharField(max_length=40, choices=EncounterStatus.choices, default=EncounterStatus.DRAFT)
    finalized_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    content_hash = models.CharField(max_length=64, blank=True)

    class Meta(TenantModel.Meta):
        indexes = [
            models.Index(fields=['tenant', 'patient', 'occurred_at'], name='clinical_encounter_lookup_idx'),
        ]

    def clean(self):
        if self.status == EncounterStatus.FINALIZED and not self.finalized_at:
            raise ValidationError({'finalized_at': 'Required once finalized'})

    def is_editable(self):
        return self.status != EncounterStatus.FINALIZED

    def compute_content_hash(self):
        payload = '|'.join([
            self.chief_complaint, self.hpi, self.personal_history, self.family_history,
            self.consanguinity_state, self.consanguinity_details, self.plan_text,
        ])
        return hashlib.sha256(payload.encode()).hexdigest()

    def __str__(self):
        return f'{self.patient_id} @ {self.occurred_at}'


class DiagnosisCertainty(models.TextChoices):
    SUSPECTED = 'suspected', 'Suspected'
    CONFIRMED = 'confirmed', 'Confirmed'
    REFUTED = 'refuted', 'Refuted'


class EncounterDiagnosis(TenantModel):
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name='diagnoses')
    diagnosis_code = models.ForeignKey(
        'catalogs.DiagnosisCode', on_delete=models.PROTECT, null=True, blank=True, related_name='+',
    )
    code_snapshot = models.CharField(max_length=20, blank=True)
    description_snapshot = models.TextField(max_length=4000, blank=True)
    certainty = models.CharField(max_length=40, choices=DiagnosisCertainty.choices)
    rank = models.PositiveSmallIntegerField(default=1)
    physician_note = models.TextField(max_length=2000, blank=True)

    def clean(self):
        if self.diagnosis_code_id and not self.code_snapshot:
            self.code_snapshot = self.diagnosis_code.code
            self.description_snapshot = self.diagnosis_code.description

    def __str__(self):
        return f'{self.code_snapshot} ({self.certainty})'


class ExaminationDomain(models.TextChoices):
    COGNITIVE = 'cognitive', 'Cognitive'
    STRENGTH = 'strength', 'Strength'
    TONE = 'tone', 'Tone'
    SENSORY_SUPERFICIAL = 'sensory_superficial', 'Superficial sensibility'
    SENSORY_DEEP = 'sensory_deep', 'Deep sensibility'
    REFLEX_MYOTATIC = 'reflex_myotatic', 'Myotatic reflexes'
    REFLEX_CUTANEOUS = 'reflex_cutaneous', 'Cutaneous reflexes'
    COORDINATION_AXIAL = 'coordination_axial', 'Axial coordination'
    COORDINATION_APPENDICULAR = 'coordination_appendicular', 'Appendicular coordination'
    GAIT = 'gait', 'Gait and balance'
    CRANIAL_NERVE = 'cranial_nerve', 'Cranial nerve'


class ExaminationState(models.TextChoices):
    NOT_ASSESSED = 'not_assessed', 'Not assessed'
    NOT_INFORMED = 'not_informed', 'Not informed'
    NORMAL = 'normal', 'Normal'
    ALTERED = 'altered', 'Altered'


class Side(models.TextChoices):
    LEFT = 'left', 'Left'
    RIGHT = 'right', 'Right'
    BILATERAL = 'bilateral', 'Bilateral'
    NOT_APPLICABLE = 'not_applicable', 'Not applicable'


class ExaminationFinding(TenantModel):
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name='examination_findings')
    domain = models.CharField(max_length=40, choices=ExaminationDomain.choices)
    item_code = models.CharField(max_length=60)
    side = models.CharField(max_length=40, choices=Side.choices, default=Side.NOT_APPLICABLE)
    body_site = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=40, choices=ExaminationState.choices, default=ExaminationState.NOT_ASSESSED)
    numeric_value = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)
    qualifier = models.CharField(max_length=255, blank=True)
    note = models.TextField(max_length=2000, blank=True)
    schema_version = models.CharField(max_length=40, default='1')

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['tenant', 'encounter', 'item_code', 'side', 'body_site'],
                name='clinical_finding_unique_item',
            ),
        ]

    def __str__(self):
        return f'{self.domain}/{self.item_code}/{self.side}={self.state}'


class ReviewAction(models.TextChoices):
    PENDING = 'pending', 'Pending'
    ACCEPTED = 'accepted', 'Accepted'
    EDITED = 'edited', 'Edited'
    REJECTED = 'rejected', 'Rejected'


class CarryForwardItem(TenantModel):
    target_encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name='carry_forward_items')
    source_encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name='+')
    field_path = models.CharField(max_length=100)
    source_version_hash = models.CharField(max_length=64)
    copied_value = models.JSONField(default=dict, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        'tenancy.Membership', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
    )
    review_action = models.CharField(max_length=40, choices=ReviewAction.choices, default=ReviewAction.PENDING)

    class Meta(TenantModel.Meta):
        constraints = TenantModel.Meta.constraints + [
            models.UniqueConstraint(
                fields=['tenant', 'target_encounter', 'field_path'],
                name='clinical_carryforward_unique_field',
            ),
        ]

    def __str__(self):
        return f'{self.field_path}: {self.source_encounter_id} -> {self.target_encounter_id}'


class ClinicalAmendment(TenantModel):
    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name='amendments')
    author = models.ForeignKey('tenancy.Membership', on_delete=models.PROTECT, related_name='+')
    reason = models.CharField(max_length=255)
    text = models.TextField(max_length=20000)
    authored_at = models.DateTimeField()

    def __str__(self):
        return f'Amendment on {self.encounter_id} by {self.author_id}'
