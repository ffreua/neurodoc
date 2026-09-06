import re

from pydantic import BaseModel, Field, field_validator

SCHEMA_VERSION = 'v1'

_NUMERIC_PROBABILITY_PATTERN = re.compile(r'\d+(\.\d+)?\s*%|\bprobabilidade\s+de\s+\d+', re.IGNORECASE)


class SourceReference(BaseModel):
    type: str
    id: str
    version_or_hash: str


class ClinicalSummaryArtifact(BaseModel):
    """RF-11.05: hypotheses are qualitative text, never a calibrated
    numeric probability -- enforced structurally (the field is a list of
    strings) and by content (no percentage-shaped substring allowed).
    """

    summary: str = Field(min_length=1, max_length=8000)
    qualitative_hypotheses: list[str] = Field(default_factory=list)
    missing_information: str = ''
    limitations: str = Field(min_length=1)
    source_refs: list[SourceReference] = Field(default_factory=list)
    medical_review_notice: str = (
        'Conteúdo gerado por IA. Requer avaliação médica antes de qualquer uso clínico.'
    )

    @field_validator('qualitative_hypotheses')
    @classmethod
    def no_numeric_probability(cls, value):
        for item in value:
            if _NUMERIC_PROBABILITY_PATTERN.search(item):
                raise ValueError(f'Hypothesis must not carry a numeric probability: {item!r}')
        return value
