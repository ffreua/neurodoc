import dataclasses

from clinical.models import ConsanguinityState

POLICY_VERSION = 'v1'

# Illustrative, conservative markers -- a genuine clinical/privacy risk
# taxonomy is P-06 territory (base legal, RIPD, anonymization policy) and
# remains unresolved. Until it is, any of these markers fails the request
# closed rather than guess at what is "safe enough" to send externally.
RARE_DISEASE_MARKERS = (
    'doenca rara', 'doença rara', 'genealogia', 'consanguinidade',
    'consanguineo', 'consanguíneo', 'heranca genetica', 'herança genética',
)


@dataclasses.dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    reason: str = ''


def evaluate_privacy_policy(encounter, combined_text):
    """Fail-closed: any recognized residual-risk signal blocks the job
    before any external request is even attempted (status=blocked_privacy),
    never merely "warns and proceeds".
    """
    if encounter is not None and encounter.consanguinity_state == ConsanguinityState.CONFIRMED \
            and encounter.consanguinity_details:
        return PolicyDecision(
            False, 'Consanguinidade confirmada e documentada exige revisão humana antes de qualquer '
                   'envio externo (risco de reidentificação por combinação de dados raros).',
        )
    haystack = (combined_text or '').lower()
    for marker in RARE_DISEASE_MARKERS:
        if marker in haystack:
            return PolicyDecision(False, f'Marcador de risco de reidentificação detectado: "{marker}".')
    return PolicyDecision(True)
