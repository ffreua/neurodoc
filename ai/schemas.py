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

from pydantic import BaseModel, Field, field_validator, model_validator

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


def _como_texto(valor):
    """Converte para texto o que o modelo mandou noutra forma, ou devolve igual.

    Três conversões, e nenhuma delas inventa conteúdo:

    - **lista de escalares vira texto** juntado por `; `. É a que motivou
      isto: em 05/10/2026 uma leitura de laudo inteira foi descartada
      porque `unreadable_sections` — o campo onde o modelo diz o que **não**
      conseguiu ler — voltou como `[]` em vez de `""`. O nome é plural, o
      prompt não declarava o tipo, e o modelo respondeu "nada ficou
      ilegível" em forma de lista. Trinta e um analitos lidos corretamente
      foram para o lixo por causa disso.
    - **`None` vira texto vazio.** `null` e `""` dizem a mesma coisa num
      campo de texto livre, e só um deles passava.
    - **número vira texto** em campo declarado como texto: `collected_on`
      com a data escrita sem aspas é a ocorrência provável.

    Lista com objeto dentro **não** é convertida: `str(dict)` produziria
    um `repr` de Python dentro do prontuário, e aí a diferença entre o que
    o laudo diz e o que o sistema mostra deixaria de ser cosmética. Isso
    segue reprovando, que é o certo.
    """
    if valor is None:
        return ''
    if isinstance(valor, bool):
        return valor
    if isinstance(valor, (int, float)):
        return str(valor)
    if isinstance(valor, (list, tuple)):
        if not all(isinstance(item, (str, int, float)) and not isinstance(item, bool)
                   for item in valor):
            return valor
        partes = [str(item).strip() for item in valor]
        return '; '.join(parte for parte in partes if parte)
    return valor


class ArtifactModel(BaseModel):
    """Base de todo esquema de saída: aceita a forma, continua exigindo o conteúdo.

    A distinção é a razão de este `model_validator` existir e de ele parar
    onde para. **Forma** é se o campo veio como lista, número ou nulo —
    decisão de serialização do modelo, sobre a qual não temos contrato
    executável (não usamos saída estruturada em toda tarefa, e mesmo com
    ela o provedor pode ignorar). **Conteúdo** é o que o prontuário não
    pode deixar de cumprir: faixa de referência vinda do laudo,
    probabilidade numérica recusada, marcador de desidentificação que não
    pode chegar ao papel.

    Normalizar a forma e manter o conteúdo sob a mesma guarda de antes é o
    único arranjo que não troca um defeito por outro: descartar a extração
    inteira por causa de um `[]` custa o trabalho todo, e relaxar o
    conteúdo custaria o motivo de os esquemas existirem. Os
    `field_validator` rodam em modo `after`, isto é, **depois** desta
    conversão — nenhum deles deixou de valer.

    Vale para os esquemas aninhados também (`ExtractedAnalyte`,
    `ReportSection`): o campo fora de forma costuma estar dentro da lista,
    não ao lado dela.
    """

    @model_validator(mode='before')
    @classmethod
    def _normalizar_campos_de_texto(cls, data):
        if not isinstance(data, dict):
            return data
        ajustado = None
        for nome, campo in cls.model_fields.items():
            # Só o campo declarado exatamente como `str`. `Optional[float]`,
            # `Literal[True]` e as listas de objetos ficam de fora: ali uma
            # conversão silenciosa esconderia divergência real.
            if campo.annotation is not str or nome not in data:
                continue
            convertido = _como_texto(data[nome])
            if convertido is data[nome]:
                continue
            if ajustado is None:
                ajustado = dict(data)
            ajustado[nome] = convertido
        return data if ajustado is None else ajustado


class SourceReference(ArtifactModel):
    type: str
    id: str
    version_or_hash: str


# --------------------------------------------------------------------------
# Resumo clínico (RF-11.05)
# --------------------------------------------------------------------------

class ClinicalSummaryArtifact(ArtifactModel):
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


class DiagnosticHypothesis(ArtifactModel):
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


class SuggestedNextStep(ArtifactModel):
    """Exame ou avaliação sugerida, com a razão de ser dela.

    `rationale` não é enfeite: o prompt pede exame que **muda a conduta**, e é
    esse campo que permite ao médico julgar se a sugestão faz isso ou se é
    mais uma linha de uma bateria genérica.
    """

    label: str = Field(min_length=1, max_length=300)
    category: Literal['laboratory', 'imaging', 'neurophysiology', 'genetics', 'other'] = 'other'
    rationale: str = Field(default='', max_length=1000)
    addresses_hypotheses: list[str] = Field(default_factory=list, max_length=8)


class DiagnosticSupportArtifact(ArtifactModel):
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

class ExtractedAnalyte(ArtifactModel):
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


class LabExtractionArtifact(ArtifactModel):
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

class ReportTranscriptionArtifact(ArtifactModel):
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


# --------------------------------------------------------------------------
# Relatório do paciente (texto que o médico revisa, edita e assina)
# --------------------------------------------------------------------------

def _reject_deidentification_markers(text):
    """Recusa o rascunho que trouxe marcador de desidentificação.

    É a guarda do defeito mais embaraçoso que este recurso pode produzir: o
    contexto vai ao modelo com o nome trocado por `[PACIENTE]`, e um
    rascunho que repita o marcador viraria, sem mais nenhuma barreira, um
    relatório entregue na perícia dizendo "[PACIENTE] evoluiu com
    hemiparesia".

    Ela mora aqui — no esquema, e não na tela — porque aqui é antes de o
    artefato existir. Um rascunho gravado é um rascunho que alguém pode
    aprovar sem reparar, e a tela de revisão é exatamente onde a vista
    cansada passa batido.
    """
    from .relatorio import marcadores_residuais

    encontrados = marcadores_residuais(text)
    if encontrados:
        raise ValueError(
            'Saída da IA não pode conter marcador de desidentificação '
            f'({", ".join(encontrados)}): escreva "o paciente".'
        )
    return text


class ReportSection(ArtifactModel):
    titulo: str = Field(default='', max_length=200)
    texto: str = Field(default='', max_length=20000)

    @field_validator('titulo', 'texto')
    @classmethod
    def no_markers(cls, value):
        return _reject_deidentification_markers(value)


class PatientReportArtifact(ArtifactModel):
    """Rascunho de relatório médico, em seções.

    **Não há validador de probabilidade numérica aqui, de propósito** — ao
    contrário do resumo e do apoio diagnóstico. Naqueles, um percentual
    saído de um modelo de linguagem se disfarça de medida calibrada. Num
    relatório, o percentual costuma ser do próprio prontuário e é
    informação clínica legítima: "redução de 50% na frequência das crises",
    "fração de ejeção de 55%". Proibi-lo apagaria o dado que o destinatário
    precisa ler.

    `requires_physician_review` é `Literal[True]` pelo motivo de sempre: o
    campo não é uma opinião do modelo sobre o próprio trabalho, é uma
    afirmação do sistema sobre o que este texto é.
    """

    titulo: str = Field(default='Relatório médico', max_length=200)
    secoes: list[ReportSection] = Field(default_factory=list, max_length=20)
    periodo_coberto: str = Field(default='', max_length=200)
    informacao_faltante: str = Field(default='', max_length=4000)
    limitations: str = Field(min_length=1, max_length=2000)
    requires_physician_review: Literal[True] = True
    disclaimer: str = MEDICAL_REVIEW_NOTICE
    source_refs: list[SourceReference] = Field(default_factory=list)

    @field_validator('titulo', 'periodo_coberto', 'informacao_faltante')
    @classmethod
    def no_markers(cls, value):
        return _reject_deidentification_markers(value)
