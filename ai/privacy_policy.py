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


def evaluate_privacy_policy(encounter, combined_text, risco_confirmado=False):
    """Fail-closed: any recognized residual-risk signal blocks the job
    before any external request is even attempted (status=blocked_privacy),
    never merely "warns and proceeds".

    `risco_confirmado` e a unica porta que atravessa esta trava, e ela so
    se abre com um medico tendo lido na tela qual marcador foi encontrado
    e dito que quer prosseguir -- a confirmacao vai para a trilha de
    auditoria com nome e hora.

    Ela existe por um caso que a versao original nao previa: o **relatorio
    que o proprio paciente leva na mao**. A trava nasceu para o que sai
    daqui como analise -- resumo, apoio diagnostico --, onde reidentificar
    alguem por combinacao de dados raros e risco sem contrapartida. Num
    relatorio pedido para a propria pericia, recusar significa negar o
    documento exatamente a quem mais precisa dele: em neurologia, quem vai
    ao INSS e com frequencia quem tem doenca rara.

    O que **nao** muda: a trava segue fechada por padrao, segue valendo
    inteira para as demais tarefas, e nenhuma delas tem como passar `True`
    aqui.
    """
    if risco_confirmado:
        return PolicyDecision(True)
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
