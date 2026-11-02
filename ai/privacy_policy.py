import dataclasses

#: `v2` desde 2026-11-02: a consanguinidade deixou de travar (e de ir).
POLICY_VERSION = 'v2'

# Marcadores de **risco de reidentificação**: doença rara e o que liga uma
# pessoa a uma família identificável (genealogia, herança genética). A
# desidentificação tira nome, CPF, telefone e e-mail; o que ela não tira é a
# combinação rara que aponta para uma família só — e é isso que trava.
#
# A **consanguinidade saiu daqui** em 2026-11-02 (decisão do responsável).
# Ela é dado de saúde, sensível como todo o prontuário, mas sozinha — e
# quase sempre negada ("nega consanguinidade") — não identifica ninguém; e
# travar por ela fechava a IA para 44% dos pacientes migrados do iClin. Em
# vez de travar, ela **não vai** ao provedor: `ai/deidentification.py`
# (`omitir_consanguinidade`) tira o trecho de todo texto enviado, e o campo
# estruturado deixou de entrar no contexto (`ai/services.py`). A lista
# deixou de ser "provisória até a P-06": a P-06 foi encerrada em 2026-09-21.
RARE_DISEASE_MARKERS = (
    'doenca rara', 'doença rara', 'genealogia', 'heranca genetica', 'herança genética',
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
    # `encounter` fica na assinatura por quem chama: a regra que o usava (a
    # consanguinidade confirmada no campo estruturado) saiu em 2026-11-02,
    # junto com o próprio dado, que não vai mais ao provedor.
    haystack = (combined_text or '').lower()
    for marker in RARE_DISEASE_MARKERS:
        if marker in haystack:
            return PolicyDecision(False, f'Marcador de risco de reidentificação detectado: "{marker}".')
    return PolicyDecision(True)
