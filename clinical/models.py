import hashlib

from django.core.exceptions import ValidationError
from django.db import models

from base.models import TenantModel


class EncounterStatus(models.TextChoices):
    DRAFT = 'draft', 'Rascunho'
    IN_PROGRESS = 'in_progress', 'Em andamento'
    FINALIZED = 'finalized', 'Finalizado'


class ConsanguinityState(models.TextChoices):
    NONE = 'none', 'Ausente'
    SUSPECTED = 'suspected', 'Suspeita'
    CONFIRMED = 'confirmed', 'Confirmada'
    NOT_INFORMED = 'not_informed', 'Não informada'


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
    SUSPECTED = 'suspected', 'Suspeita'
    CONFIRMED = 'confirmed', 'Confirmada'
    REFUTED = 'refuted', 'Refutada'


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
    # Eixos do roteiro estruturado (app `exams`). Convivem com os domínios
    # do catálogo legado abaixo: um achado registrado por roteiro guarda o
    # eixo, um achado do catálogo antigo guarda o domínio antigo, e os dois
    # continuam legíveis lado a lado no mesmo atendimento.
    AXIS_CONSCIOUSNESS = 'consciencia', 'Nível de consciência'
    AXIS_COGNITIVE = 'cognitivo', 'Cognitivo (roteiro)'
    AXIS_SOMATIC = 'somatico', 'Somático'
    AXIS_CRANIAL_NERVES = 'nervos_cranianos', 'Nervos cranianos (roteiro)'

    COGNITIVE = 'cognitive', 'Cognitivo'
    STRENGTH = 'strength', 'Força'
    TONE = 'tone', 'Tônus'
    SENSORY_SUPERFICIAL = 'sensory_superficial', 'Sensibilidade superficial'
    SENSORY_DEEP = 'sensory_deep', 'Sensibilidade profunda'
    REFLEX_MYOTATIC = 'reflex_myotatic', 'Reflexos miotáticos'
    REFLEX_CUTANEOUS = 'reflex_cutaneous', 'Reflexos cutâneos'
    COORDINATION_AXIAL = 'coordination_axial', 'Coordenação axial'
    COORDINATION_APPENDICULAR = 'coordination_appendicular', 'Coordenação apendicular'
    GAIT = 'gait', 'Marcha e equilíbrio'
    CRANIAL_NERVE = 'cranial_nerve', 'Nervos cranianos'


class ExaminationState(models.TextChoices):
    NOT_ASSESSED = 'not_assessed', 'Não avaliado'
    NOT_INFORMED = 'not_informed', 'Não informado'
    NORMAL = 'normal', 'Normal'
    ALTERED = 'altered', 'Alterado'


class Side(models.TextChoices):
    LEFT = 'left', 'Esquerdo'
    RIGHT = 'right', 'Direito'
    BILATERAL = 'bilateral', 'Bilateral'
    NOT_APPLICABLE = 'not_applicable', 'Não se aplica'


class ExaminationFinding(TenantModel):
    """Um item examinado neste atendimento.

    Só existe linha para item de fato registrado — item não avaliado não
    tem linha e, portanto, nunca aparece como normal.

    Dois caminhos convivem: o catálogo legado (`clinical.examination`), em
    que `item_code` é um código curto do catálogo, e o roteiro estruturado
    (`exams`), em que `item_code` é o caminho do nó no roteiro
    (`somatico.motricidade.forca.flexao_cotovelo`) e `template_node` aponta
    para a definição usada.

    Onde o valor fica depende do tipo de entrada do item:

    - `state`  -> `state` (não avaliado / não informado / normal / alterado);
    - `number` -> `numeric_value`;
    - demais   -> `value_json`, com a versão legível em `qualifier`.

    `state` só tem significado clínico em item do tipo `state`; nos outros
    ele permanece no padrão e quem lê deve olhar o valor.
    """

    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name='examination_findings')
    domain = models.CharField(max_length=40, choices=ExaminationDomain.choices)
    item_code = models.CharField(max_length=200)
    template_node = models.ForeignKey(
        'exams.ExamNode', on_delete=models.PROTECT, null=True, blank=True, related_name='findings',
    )
    template_version = models.PositiveIntegerField(null=True, blank=True)
    value_json = models.JSONField(default=dict, blank=True)
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
    PENDING = 'pending', 'Pendente'
    ACCEPTED = 'accepted', 'Aceito'
    EDITED = 'edited', 'Editado'
    REJECTED = 'rejected', 'Rejeitado'


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
