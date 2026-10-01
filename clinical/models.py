import hashlib

from django.core.exceptions import ValidationError
from django.db import models

from base.models import TenantModel


class EncounterStatus(models.TextChoices):
    DRAFT = 'draft', 'Rascunho'
    IN_PROGRESS = 'in_progress', 'Em andamento'
    FINALIZED = 'finalized', 'Finalizado'


class EncounterKind(models.TextChoices):
    """Como este atendimento é escrito. Os dois valem igualmente.

    O estruturado é o prontuário neurológico completo — queixa, história,
    antecedentes, o roteiro de exame com quase 400 itens, escalas. É o que
    se quer numa primeira consulta e numa investigação.

    O texto livre existe porque nem toda consulta é essa. Retorno de
    rotina, ajuste de dose, renovação — o médico com a sala cheia escreve
    um parágrafo, e obrigá-lo a percorrer seis abas para isso faz com que
    ele escreva o parágrafo em outro lugar, fora do prontuário. Um
    prontuário que só aceita o registro completo acaba recebendo menos
    registro, não mais.

    O que **não** muda entre os dois: medicação em uso, hipóteses (CID),
    conduta e os documentos emitidos continuam estruturados e são os
    mesmos campos. É por isso que a conduta, as impressões e o CID de um
    atendimento de texto livre podem ser copiados para um estruturado e
    vice-versa — a cópia é por campo, e o campo é o mesmo.
    """

    STRUCTURED = 'structured', 'Prontuário estruturado'
    FREE_TEXT = 'free_text', 'Texto livre'


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
    #: Hábitos e vícios — tabagismo, álcool, outras substâncias, sono,
    #: atividade física.
    #:
    #: Campo próprio, e não um parágrafo dentro de antecedentes pessoais,
    #: porque em neurologia ele é pergunta de rotina e resposta que muda
    #: conduta: álcool e sono explicam crise, tremor e cefaleia, e a
    #: interação de substância com anticonvulsivante é decisão de
    #: prescrição. Diluído no meio do texto livre, some na releitura.
    habits_history = models.TextField(max_length=20000, blank=True)
    consanguinity_state = models.CharField(
        max_length=40, choices=ConsanguinityState.choices, default=ConsanguinityState.NOT_INFORMED,
    )
    consanguinity_details = models.TextField(max_length=2000, blank=True)
    #: Registro narrativo do exame neurológico no atendimento estruturado.
    #:
    #: Complementa — não substitui — os achados do roteiro. Há descrições
    #: clínicas que perdem sentido quando quebradas em itens, e o médico
    #: precisa poder conservá-las no mesmo bloco do exame.
    neurological_exam_text = models.TextField(max_length=20000, blank=True)
    plan_text = models.TextField(max_length=20000, blank=True)
    #: Como este atendimento é escrito. Ver `EncounterKind`.
    kind = models.CharField(
        max_length=20, choices=EncounterKind.choices, default=EncounterKind.STRUCTURED,
    )
    #: O corpo do atendimento de texto livre.
    #:
    #: Teto alto de propósito: é onde cabe a consulta inteira quando o
    #: médico escolhe escrever corrido, e um limite apertado seria
    #: descoberto no meio de uma consulta, com o texto pronto na tela.
    #: Vazio no atendimento estruturado, onde o mesmo conteúdo está
    #: distribuído entre queixa, história e antecedentes.
    free_text = models.TextField(max_length=100000, blank=True)
    #: Impressões do médico sobre o caso.
    #:
    #: Campo próprio, e não um parágrafo no fim do texto livre, porque é o
    #: que se quer levar para a próxima consulta — como a conduta e as
    #: hipóteses. Diluído no corpo do texto, não haveria o que copiar.
    impressions = models.TextField(max_length=20000, blank=True)
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
            raise ValidationError({'finalized_at': 'Obrigatório para finalizar o atendimento.'})

    def is_editable(self):
        return self.status != EncounterStatus.FINALIZED

    def compute_content_hash(self):
        """Impressão digital do que o médico escreveu neste atendimento.

        Gravada na finalização e mostrada na tela e na trilha de auditoria.
        Campo de texto que fique de fora muda sem que a versão do atendimento
        mude — e no texto livre o campo de fora seria o **corpo inteiro da
        consulta**, que é justamente o que o hash existe para cobrir. Por isso
        `free_text`, `impressions` e `neurological_exam_text` entram aqui.

        Acrescentar campo muda o hash de atendimentos ainda abertos, e não o
        dos já finalizados: aquele valor está gravado em `content_hash` e nada
        o recalcula.
        """
        payload = '|'.join([
            self.chief_complaint, self.hpi, self.personal_history, self.family_history,
            self.habits_history,
            self.consanguinity_state, self.consanguinity_details,
            self.neurological_exam_text, self.plan_text,
            self.free_text, self.impressions,
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
    AXIS_SCALES = 'escalas', 'Escalas funcionais'

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


class MedicationStatus(models.TextChoices):
    IN_USE = 'in_use', 'Em uso'
    SUSPENDED = 'suspended', 'Suspenso'
    FINISHED = 'finished', 'Concluído'


class MedicationRoute(models.TextChoices):
    ORAL = 'oral', 'Oral'
    SUBLINGUAL = 'sublingual', 'Sublingual'
    INTRAVENOUS = 'intravenous', 'Intravenosa'
    INTRAMUSCULAR = 'intramuscular', 'Intramuscular'
    SUBCUTANEOUS = 'subcutaneous', 'Subcutânea'
    TOPICAL = 'topical', 'Tópica'
    INHALED = 'inhaled', 'Inalatória'
    OTHER = 'other', 'Outra'


class Medication(TenantModel):
    """Medicação em uso registrada neste atendimento.

    Pertence ao atendimento, não ao paciente: o prontuário registra o que
    estava em uso **naquela consulta**, e é isso que precisa ficar imutável
    depois de finalizado. A lista da consulta seguinte é trazida pela cópia
    revisada do atendimento anterior (RF-03.04), e não por referência a uma
    lista viva, que mudaria o registro passado.
    """

    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name='medications')
    name = models.CharField(max_length=255)
    dose = models.CharField(max_length=100, blank=True)
    route = models.CharField(max_length=20, choices=MedicationRoute.choices, default=MedicationRoute.ORAL)
    frequency = models.CharField(max_length=100, blank=True)
    started_on = models.DateField(null=True, blank=True)
    indication = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, choices=MedicationStatus.choices, default=MedicationStatus.IN_USE)
    prescriber = models.CharField(max_length=255, blank=True)
    notes = models.TextField(max_length=2000, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ['name']
        indexes = [models.Index(fields=['tenant', 'encounter'], name='clinical_medication_idx')]

    def __str__(self):
        return f'{self.name} {self.dose}'.strip()


class ExamCategory(models.TextChoices):
    LABORATORY = 'laboratory', 'Laboratorial'
    IMAGING = 'imaging', 'Imagem'
    NEUROPHYSIOLOGY = 'neurophysiology', 'Neurofisiologia'
    PATHOLOGY = 'pathology', 'Patologia'
    GENETICS = 'genetics', 'Genética'
    OTHER = 'other', 'Outro'


class ExtractionStatus(models.TextChoices):
    NONE = 'none', 'Sem leitura'
    QUEUED = 'queued', 'Na fila'
    RUNNING = 'running', 'Processando'
    READY = 'ready', 'Rascunho para revisão'
    ACCEPTED = 'accepted', 'Revisado e incorporado'
    REJECTED = 'rejected', 'Rascunho recusado'
    FAILED = 'failed', 'Falhou'
    BLOCKED = 'blocked', 'Bloqueado pela política de privacidade'
    # Os rótulos são lidos atrás do prefixo "IA:" no crachá da tela, por isso
    # nenhum deles repete a sigla.
    DISABLED = 'disabled', 'Desligada'


class ExamResult(TenantModel):
    """Resultado de exame complementar registrado no atendimento.

    O laudo em PDF entra como `documents.Attachment`, então passa pela mesma
    verificação de malware e pelo mesmo controle de download dos demais
    anexos — sem um caminho paralelo para arquivo clínico.

    `report_text` é o laudo como fica no prontuário. Quando a IA lê o PDF, o
    texto **não** é escrito aqui: fica como rascunho no `AIArtifact` até que
    um médico identificado o revise e aceite (RF-11-B).
    """

    encounter = models.ForeignKey(Encounter, on_delete=models.PROTECT, related_name='exam_results')
    patient = models.ForeignKey('patients.Patient', on_delete=models.PROTECT, related_name='exam_results')
    category = models.CharField(max_length=20, choices=ExamCategory.choices, default=ExamCategory.LABORATORY)
    name = models.CharField(max_length=255)
    performed_on = models.DateField(null=True, blank=True)
    service_name = models.CharField(max_length=255, blank=True)
    report_text = models.TextField(max_length=20000, blank=True)
    conclusion = models.TextField(max_length=4000, blank=True)
    attachment = models.ForeignKey(
        'documents.Attachment', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='exam_results',
    )
    extraction_status = models.CharField(
        max_length=20, choices=ExtractionStatus.choices, default=ExtractionStatus.NONE,
    )
    extraction_detail = models.CharField(max_length=255, blank=True)

    class Meta(TenantModel.Meta):
        ordering = ['-performed_on', 'name']
        indexes = [
            models.Index(fields=['tenant', 'encounter'], name='clinical_examresult_enc_idx'),
            models.Index(fields=['tenant', 'patient'], name='clinical_examresult_pat_idx'),
        ]

    @property
    def is_laboratory(self):
        return self.category == ExamCategory.LABORATORY

    @property
    def abnormal_values(self):
        return [value for value in self.lab_values.all() if value.flag in LabValueFlag.out_of_range()]

    def __str__(self):
        return f'{self.name} ({self.performed_on})'


class LabValueFlag(models.TextChoices):
    NORMAL = 'normal', 'Dentro da referência'
    LOW = 'low', 'Abaixo da referência'
    HIGH = 'high', 'Acima da referência'
    ABNORMAL = 'abnormal', 'Fora da referência'
    NO_REFERENCE = 'no_reference', 'Sem referência no laudo'

    @classmethod
    def out_of_range(cls):
        return {cls.LOW, cls.HIGH, cls.ABNORMAL}


class LabValue(TenantModel):
    """Um analito de um exame laboratorial, com a referência do próprio laudo.

    A faixa de referência vem do laudo, nunca de uma tabela interna: ela
    varia com laboratório, método, idade e sexo, e classificar o resultado
    contra a referência de outra origem seria inventar a interpretação.

    Sem faixa informada o resultado fica `no_reference` — o sistema não
    adivinha se está normal.
    """

    exam_result = models.ForeignKey(ExamResult, on_delete=models.CASCADE, related_name='lab_values')
    order = models.PositiveIntegerField(default=0)
    analyte = models.CharField(max_length=200)
    value_text = models.CharField(max_length=100)
    numeric_value = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    unit = models.CharField(max_length=40, blank=True)
    reference_low = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    reference_high = models.DecimalField(max_digits=14, decimal_places=4, null=True, blank=True)
    reference_text = models.CharField(max_length=120, blank=True)
    flag = models.CharField(max_length=20, choices=LabValueFlag.choices, default=LabValueFlag.NO_REFERENCE)
    #: 'manual' ou 'ai' — quem leu o laudo. Valor extraído por IA só chega
    #: aqui depois de revisão médica.
    source = models.CharField(max_length=10, default='manual')

    class Meta(TenantModel.Meta):
        ordering = ['order', 'analyte']
        indexes = [models.Index(fields=['tenant', 'exam_result'], name='clinical_labvalue_idx')]

    def compute_flag(self):
        if self.numeric_value is None:
            return LabValueFlag.NO_REFERENCE
        if self.reference_low is None and self.reference_high is None:
            return LabValueFlag.NO_REFERENCE
        if self.reference_low is not None and self.numeric_value < self.reference_low:
            return LabValueFlag.LOW
        if self.reference_high is not None and self.numeric_value > self.reference_high:
            return LabValueFlag.HIGH
        return LabValueFlag.NORMAL

    @staticmethod
    def _trim(value):
        """Decimal sem os zeros do campo.

        `f'{Decimal("12.0000"):g}'` devolve `12.0000` — ao contrário do float,
        o Decimal preserva as casas que foram declaradas. Sem isto a faixa do
        laudo aparecia como "150000.0000 – 450000.0000".
        """
        text = f'{value:f}'
        if '.' in text:
            text = text.rstrip('0').rstrip('.')
        return text or '0'

    @property
    def reference_display(self):
        if self.reference_text:
            return self.reference_text
        low, high = self.reference_low, self.reference_high
        if low is not None and high is not None:
            return f'{self._trim(low)} – {self._trim(high)}'
        if high is not None:
            return f'até {self._trim(high)}'
        if low is not None:
            return f'a partir de {self._trim(low)}'
        return '—'

    def save(self, *args, **kwargs):
        self.flag = self.compute_flag()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.analyte}: {self.value_text} {self.unit}'.strip()
