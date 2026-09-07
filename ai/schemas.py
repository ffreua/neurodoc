"""Contrato de saída da IA.

Nada que o modelo devolve entra no sistema sem passar por um destes
esquemas. Isso não é só validação de tipo: é onde ficam as regras que o
prontuário não pode deixar de cumprir.

Duas dessas regras merecem ser lidas antes de mexer aqui:

- **hipótese não tem probabilidade numérica** (RF-11.05). A prioridade é
  qualitativa — `higher`, `intermediate`, `lower`, `insufficient_evidence` —
  e o PRD é explícito: "não é probabilidade nem nível validado de acurácia".
  Um percentual saído de um modelo de linguagem dentro de um prontuário
  parece medida e não é; seria lido como calibrado sem nunca ter sido
  validado. O validador recusa qualquer texto em formato de percentual.
- **faixa de referência vem do laudo.** Na extração de exame laboratorial o
  modelo transcreve a referência impressa no documento; ele não pode
  inventá-la nem trazer de memória, porque ela varia com laboratório,
  método, idade e sexo. Sem referência no laudo, o analito fica sem
  classificação em vez de ser chamado de normal.
"""

import re
from enum import StrEnum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = 'v1'

_NUMERIC_PROBABILITY_PATTERN = re.compile(
    r'\d+(\.\d+)?\s*%'
    r'|\bprobabilidade\s+de\s+\d+'
    r'|\b\d+(\.\d+)?\s*(?:de|em)\s*\d+\s*(?:de\s*)?chance'
    r'|\bchance\s+de\s+\d+',
    re.IGNORECASE,
)

MEDICAL_REVIEW_NOTICE = (
    'Conteúdo gerado por IA. Requer avaliação médica antes de qualquer uso clínico.'
)


def _reject_numeric_probability(text):
    if _NUMERIC_PROBABILITY_PATTERN.search(text or ''):
        raise ValueError(
            f'Saída da IA não pode carregar probabilidade numérica: {text!r}'
        )
    return text


class SourceReference(BaseModel):
    type: str
    id: str
    version_or_hash: str


# --------------------------------------------------------------------------
# Resumo clínico (RF-11.05)
# --------------------------------------------------------------------------

class ClinicalSummaryArtifact(BaseModel):
    """Resumo de apoio à revisão médica; hipóteses aqui são texto qualitativo."""

    summary: str = Field(min_length=1, max_length=8000)
    qualitative_hypotheses: list[str] = Field(default_factory=list)
    missing_information: str = ''
    limitations: str = Field(min_length=1)
    source_refs: list[SourceReference] = Field(default_factory=list)
    medical_review_notice: str = MEDICAL_REVIEW_NOTICE

    @field_validator('qualitative_hypotheses')
    @classmethod
    def no_numeric_probability(cls, value):
        for item in value:
            _reject_numeric_probability(item)
        return value


# --------------------------------------------------------------------------
# Apoio ao raciocínio diagnóstico (PRD 14.4)
# --------------------------------------------------------------------------

class HypothesisPriority(StrEnum):
    """As quatro faixas admitidas pelo PRD, e nada além disso.

    `insufficient_evidence` não é a menor delas: é a saída honesta quando o
    caso não sustenta ordenação nenhuma — e é ela que o modelo deve usar em
    vez de forçar um ranking.
    """

    HIGHER = 'higher'
    INTERMEDIATE = 'intermediate'
    LOWER = 'lower'
    INSUFFICIENT_EVIDENCE = 'insufficient_evidence'


PRIORITY_LABELS = {
    HypothesisPriority.HIGHER: 'Prioridade maior',
    HypothesisPriority.INTERMEDIATE: 'Prioridade intermediária',
    HypothesisPriority.LOWER: 'Prioridade menor',
    HypothesisPriority.INSUFFICIENT_EVIDENCE: 'Evidência insuficiente',
}

#: Tom contextual de cada faixa, nos mesmos nomes que `base.templatetags.nd`
#: usa no resto do sistema. `lower` é `dark` — o cinza claro do tema — e não
#: `secondary`, que no Duralux não define fundo nenhum e faria a faixa
#: parecer texto solto em vez de crachá.
PRIORITY_TONES = {
    HypothesisPriority.HIGHER: 'primary',
    HypothesisPriority.INTERMEDIATE: 'info',
    HypothesisPriority.LOWER: 'dark',
    HypothesisPriority.INSUFFICIENT_EVIDENCE: 'warning',
}

#: Categoria do exame sugerido em português. O esquema usa o termo em inglês
#: porque é o que o modelo devolve e o que o PRD fixa; a tela é em português.
STEP_CATEGORY_LABELS = {
    'laboratory': 'Laboratorial',
    'imaging': 'Imagem',
    'neurophysiology': 'Neurofisiologia',
    'genetics': 'Genética',
    'other': 'Outro',
}


class DiagnosticHypothesis(BaseModel):
    label: str = Field(min_length=1, max_length=300)
    priority: HypothesisPriority
    supporting_evidence: list[str] = Field(default_factory=list, max_length=12)
    contradictory_evidence: list[str] = Field(default_factory=list, max_length=12)
    missing_information: str = Field(default='', max_length=1000)
    uncertainty_note: str = Field(default='', max_length=1000)

    @field_validator('label', 'missing_information', 'uncertainty_note')
    @classmethod
    def no_numeric_probability(cls, value):
        return _reject_numeric_probability(value)

    @property
    def priority_label(self):
        return PRIORITY_LABELS[self.priority]


class SuggestedNextStep(BaseModel):
    """Exame ou avaliação sugerida, com a razão de ser dela.

    `rationale` não é enfeite: o prompt pede exame que **muda a conduta**, e é
    esse campo que permite ao médico julgar se a sugestão faz isso ou se é
    mais uma linha de uma bateria genérica.
    """

    label: str = Field(min_length=1, max_length=300)
    category: Literal['laboratory', 'imaging', 'neurophysiology', 'genetics', 'other'] = 'other'
    rationale: str = Field(default='', max_length=1000)
    addresses_hypotheses: list[str] = Field(default_factory=list, max_length=8)


class DiagnosticSupportArtifact(BaseModel):
    """Hipóteses por prioridade qualitativa + exames sugeridos (PRD 14.4).

    `requires_physician_review` é fixo em `True` e não é negociável pelo
    modelo: RF-11-B exige revisão identificada antes de qualquer conteúdo de
    IA virar conteúdo clínico, e um campo que o modelo pudesse baixar para
    `False` seria um caminho para pular essa revisão.
    """

    hypotheses: list[DiagnosticHypothesis] = Field(default_factory=list, max_length=12)
    suggested_next_steps: list[SuggestedNextStep] = Field(default_factory=list, max_length=15)
    missing_information: str = Field(default='', max_length=4000)
    limitations: str = Field(min_length=1, max_length=4000)
    requires_physician_review: Literal[True] = True
    disclaimer: str = MEDICAL_REVIEW_NOTICE
    source_refs: list[SourceReference] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Leitura de laudo laboratorial
# --------------------------------------------------------------------------

class ExtractedAnalyte(BaseModel):
    """Um analito lido do laudo, com a referência do próprio laudo.

    `reference_low`/`reference_high` ficam `None` quando o documento não
    traz a faixa. O sistema calcula a classificação a partir daí — o modelo
    **não** decide se o valor é normal, porque essa decisão precisa ser
    reproduzível a partir do que está escrito no papel.
    """

    analyte: str = Field(min_length=1, max_length=200)
    value_text: str = Field(min_length=1, max_length=100)
    numeric_value: Optional[float] = None
    unit: str = Field(default='', max_length=40)
    reference_low: Optional[float] = None
    reference_high: Optional[float] = None
    reference_text: str = Field(default='', max_length=120)


class LabExtractionArtifact(BaseModel):
    exam_name: str = Field(default='', max_length=255)
    collected_on: str = Field(default='', max_length=30)
    service_name: str = Field(default='', max_length=255)
    analytes: list[ExtractedAnalyte] = Field(default_factory=list, max_length=200)
    unreadable_sections: str = Field(default='', max_length=2000)
    limitations: str = Field(min_length=1, max_length=2000)
    requires_physician_review: Literal[True] = True
    disclaimer: str = MEDICAL_REVIEW_NOTICE
    source_refs: list[SourceReference] = Field(default_factory=list)


# --------------------------------------------------------------------------
# Transcrição de laudo de imagem / EEG / ENMG
# --------------------------------------------------------------------------

class ReportTranscriptionArtifact(BaseModel):
    """Laudo transcrito, não interpretado.

    `report_text` e `conclusion` devem reproduzir o que está no documento.
    A instrução ao modelo é explícita quanto a não resumir nem completar o
    laudo: o prontuário registra o que o laudo diz, e um resumo silencioso
    apagaria justamente o detalhe que faz o achado significar algo.
    """

    detected_category: Literal[
        'imaging', 'neurophysiology', 'laboratory', 'pathology', 'genetics', 'other'
    ] = 'other'
    exam_name: str = Field(default='', max_length=255)
    performed_on: str = Field(default='', max_length=30)
    service_name: str = Field(default='', max_length=255)
    report_text: str = Field(default='', max_length=20000)
    conclusion: str = Field(default='', max_length=4000)
    unreadable_sections: str = Field(default='', max_length=2000)
    limitations: str = Field(min_length=1, max_length=2000)
    requires_physician_review: Literal[True] = True
    disclaimer: str = MEDICAL_REVIEW_NOTICE
    source_refs: list[SourceReference] = Field(default_factory=list)
