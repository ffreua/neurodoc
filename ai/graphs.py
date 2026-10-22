"""Chamada ao modelo e validação da resposta, por tipo de tarefa.

O grafo tem dois nós de propósito: chamar o modelo e validar a saída contra
o esquema Pydantic. Não existe um terceiro nó que "entrega ao usuário" —
resposta inválida ou longa demais nunca chega a um estado que possa ser
confundido com artefato válido, e quem chama (`ai.services`) confere
`state['error']` antes de gravar qualquer coisa.

Os prompts ficam aqui junto do esquema que validam. Mudar um sem o outro é o
jeito mais fácil de quebrar a extração, e ter os dois na mesma tela é o que
evita isso.
"""

import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from .schemas import (
    ClinicalSummaryArtifact, DiagnosticSupportArtifact, PatientReportArtifact,
)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_OUTPUT_CHARS = 20000

PROMPT_VERSION = 'v3'

_JSON_ONLY = (
    'Responda apenas com um objeto JSON válido, sem texto, comentário ou cerca de código '
    'fora do JSON.'
)

SUMMARY_PROMPT = """Você é um assistente que organiza informações administrativas e clínicas \
já autorizadas e desidentificadas para apoio à revisão médica. NUNCA invente dados que não \
estejam no contexto abaixo. Escreva TODOS os valores textuais em português brasileiro (pt-BR), \
mesmo quando o contexto ou os nomes das chaves JSON estiverem em outro idioma. {json_only} \
Campos: "summary" (string), \
"qualitative_hypotheses" (lista de strings, NUNCA com percentuais ou probabilidades \
numéricas), "missing_information" (string), "limitations" (string), "source_refs" (lista de \
objetos com "type", "id", "version_or_hash").

Contexto (já desidentificado):
{context}
"""

DIAGNOSTIC_SUPPORT_PROMPT = """Você apoia o raciocínio diagnóstico de um médico neurologista \
a partir do caso desidentificado abaixo. Você NÃO faz diagnóstico e NÃO prescreve: organiza \
hipóteses para o médico avaliar.

Regras que não admitem exceção:
1. Use somente o que está no contexto. Não complete o caso com dado que não está lá.
2. NUNCA dê probabilidade, percentual, chance ou nível de acurácia. A ordenação é \
qualitativa e "priority" só pode ser "higher", "intermediate", "lower" ou \
"insufficient_evidence".
3. Se o caso não sustenta ordenação, use "insufficient_evidence" e diga em \
"missing_information" o que falta. Preferir uma lista honestamente inconclusiva a uma \
lista ordenada sem base.
4. Cada hipótese deve trazer o que a apoia E o que a contraria no caso; se não há nada \
que a contrarie no material disponível, deixe a lista vazia em vez de inventar.
5. Em "suggested_next_steps", sugira exame ou avaliação que efetivamente muda a conduta, \
com a razão em "rationale". Não liste bateria genérica.

{json_only} Campos: "hypotheses" (lista de objetos com "label", "priority", \
"supporting_evidence" [lista de strings], "contradictory_evidence" [lista de strings], \
"missing_information", "uncertainty_note"), "suggested_next_steps" (lista de objetos com \
"label", "category" entre "laboratory"/"imaging"/"neurophysiology"/"genetics"/"other", \
"rationale", "addresses_hypotheses" [lista de strings]), "missing_information" (string), \
"limitations" (string), "requires_physician_review" (sempre true), "disclaimer" (string).

Caso (já desidentificado):
{context}
"""

REPORT_PROMPT = """Você redige o RASCUNHO de um relatório médico. O autor é o médico: ele vai ler, corrigir e assinar o que você escrever, e é ele quem responde pelo documento. Seu trabalho é organizar o que está no prontuário abaixo na forma de um relatório.

Destinatário: {destinatario}.
{orientacao}

Pedido do médico, que manda sobre tudo que vem depois: {pedido}

Seções esperadas (use-as como estrutura; omita a que o prontuário não sustenta, e acrescente outra se o pedido do médico pedir): {secoes}

Regras que não admitem exceção:
1. Use somente o que está no prontuário. Não complete, não deduza e não acrescente achado, data, exame ou conduta que não esteja lá. O que faltar vai em "informacao_faltante" — nunca no corpo do relatório.
2. NUNCA escreva [PACIENTE], [NOME_MAE], [CPF], [TELEFONE] ou [EMAIL]. Escreva "o paciente" ou "a paciente". A identificação é impressa pelo sistema no cabeçalho do documento e não é assunto seu — um marcador desses sobrevive até o papel que o paciente entrega na perícia.
3. Toda data que você citar tem de estar no prontuário. Se o prontuário não diz quando algo começou, diga que o registro mais antigo é de tal data — não estime.
4. Escreva em português brasileiro, em prosa corrida, no registro de um relatório médico: nem tópicos telegráficos, nem abreviação de prontuário. Quem lê do outro lado pode não ser médico.
5. Não prescreva, não indique tratamento novo e não afirme prognóstico que o prontuário não sustente.
6. Não conclua sobre incapacidade, aptidão, direito a benefício, cobertura ou qualquer decisão que caiba ao destinatário. Você descreve o quadro; quem decide é quem recebe.
7. Diagnóstico refutado está listado à parte no contexto e **não é** diagnóstico do paciente. Só o mencione se for útil dizer o que foi investigado e afastado, e deixando claro que foi afastado.

{json_only} Campos: "titulo" (string), "secoes" (lista de objetos com "titulo" e "texto"), "periodo_coberto" (string dizendo de que data a que data o prontuário lido vai), "informacao_faltante" (string), "limitations" (string), "requires_physician_review" (sempre true), "disclaimer" (string).

Prontuário (já desidentificado):
{context}
"""


#: kind do AIJob -> (prompt, esquema). É o único lugar que amarra um tipo de
#: tarefa ao formato que ele pode devolver.
TASKS = {
    'encounter_summary': (SUMMARY_PROMPT, ClinicalSummaryArtifact),
    'patient_summary': (SUMMARY_PROMPT, ClinicalSummaryArtifact),
    'patient_report': (REPORT_PROMPT, PatientReportArtifact),
    'diagnostic_support': (DIAGNOSTIC_SUPPORT_PROMPT, DiagnosticSupportArtifact),
}


class GraphState(TypedDict):
    prompt: str
    timeout_seconds: int
    raw_response: Optional[str]
    artifact: Optional[dict]
    error: Optional[str]
    #: Por que a saída foi recusada, em termos de *forma* e sem nenhum
    #: valor do laudo. Ver `_diagnostico_de_forma`.
    diagnostics: Optional[dict]


#: Tarefas em que o esquema vai junto do pedido, e não só descrito no
#: prompt. Só as duas de leitura de documento, de propósito: são as que
#: devolvem o objeto mais longo (dezenas de analitos, cada um com sete
#: campos), as que mais erravam a forma, e — o que decide — as duas que
#: nunca tiveram um sucesso. Uma recusa do provedor aqui não pode piorar
#: nada, enquanto ligá-la de saída no resumo e no relatório, que
#: funcionam hoje, arriscaria derrubá-los por um parâmetro.
# Vazio desde a 1.18: as duas tarefas que pediam o esquema ao provedor eram
# as leituras de laudo, que saíram. O mecanismo fica (com o recuo para o
# provedor que recusa o parâmetro) para a próxima tarefa de saída estruturada.
STRUCTURED_OUTPUT_TASKS = frozenset()

#: Como se reconhece "não aceito esse parâmetro" no meio de um erro de
#: provedor. É farejar texto, e é feio; a alternativa é não pedir esquema
#: a ninguém, porque a API compatível com OpenAI não tem como dizer de
#: antemão se o modelo por trás do OpenRouter suporta `json_schema`.
_PARAMETRO_RECUSADO = re.compile(
    r'response_format|json_schema|structured[ _]output|schema is not supported'
    r'|not supported|unsupported|unrecognized|unknown (?:field|parameter)'
    r'|invalid[_ ]request',
    re.IGNORECASE,
)

#: Abaixo disto não vale repetir sem o esquema: sobra tempo para a chamada
#: sair e não para ela voltar, e o médico esperaria o dobro por nada.
_MINIMO_PARA_REPETIR = 10


def _formato_de_resposta(schema):
    """O esquema no formato que a API compatível com OpenAI entende.

    `strict: False` é deliberado. O modo estrito da OpenAI exige
    `additionalProperties: false` em todo objeto e **todos** os campos em
    `required` — o que estes esquemas não são, porque metade dos campos
    tem padrão e existe `Optional[float]` no meio. Gerar uma variante
    estrita a partir deles seria um segundo esquema para manter em
    sincronia com o primeiro, e esquema duplicado diverge. Não estrito o
    provedor trata como forte sugestão de forma, que é exatamente o que
    faltava; o contrato continua sendo o Pydantic, aqui do lado.
    """
    return {
        'type': 'json_schema',
        'json_schema': {
            'name': schema.__name__,
            'schema': schema.model_json_schema(),
            'strict': False,
        },
    }


def _chamar_modelo(chat_model, prompt, timeout_seconds, schema=None):
    """Chama o provedor pedindo o esquema; repete sem ele se for recusado.

    O recuo existe porque "suporta `json_schema`" não é propriedade do
    provedor e sim do modelo por trás dele: o mesmo OpenRouter atende
    modelo que aceita e modelo que devolve 400. Sem o recuo, ligar o
    esquema transformaria "a leitura às vezes sai torta" em "a leitura
    nunca sai", que é pior.

    **Não é troca silenciosa de provedor** (RT-04): é o mesmo provedor, o
    mesmo modelo e o mesmo prompt, sem um parâmetro de formatação que ele
    disse não entender. O que garante a saída continua sendo a validação
    do esquema logo adiante — o `response_format` só diminui a chance de
    chegar torta.

    Devolve `(resposta, esquema_foi_aceito)`.
    """
    if schema is None:
        return _invoke_with_timeout(chat_model, prompt, timeout_seconds), False

    inicio = time.monotonic()
    try:
        vinculado = chat_model.bind(response_format=_formato_de_resposta(schema))
        return _invoke_with_timeout(vinculado, prompt, timeout_seconds), True
    except GraphTimeout:
        # Prazo estourado não é recusa de parâmetro: repetir só gastaria o
        # resto do tempo do médico.
        raise
    except Exception as exc:
        if not _PARAMETRO_RECUSADO.search(str(exc)):
            raise
        restante = timeout_seconds - (time.monotonic() - inicio)
        if restante < _MINIMO_PARA_REPETIR:
            raise
        logger.info(
            'Provedor recusou response_format; repetindo sem esquema',
            extra={'erro': str(exc)[:200]},
        )
        return _invoke_with_timeout(chat_model, prompt, restante), False


def _tipo_json(valor):
    """O nome do tipo JSON de um valor — e só isso, nunca o valor."""
    if valor is None:
        return 'null'
    if isinstance(valor, bool):
        return 'bool'
    if isinstance(valor, (int, float)):
        return 'number'
    if isinstance(valor, str):
        return f'string[{len(valor)}]'
    if isinstance(valor, list):
        return f'list[{len(valor)}]'
    if isinstance(valor, dict):
        return f'object[{len(valor)}]'
    return type(valor).__name__


def _diagnostico_de_forma(data, exc):
    """Por que a saída foi recusada, sem carregar nenhum valor do laudo.

    Este é o ponto da coisa, e ele é uma decisão de privacidade antes de
    ser de engenharia. Guardar a resposta crua do modelo resolveria o
    diagnóstico e criaria um depósito novo de conteúdo clínico — com
    retenção, acesso e exportação próprios para pensar. Mas o que falta
    quando uma extração é recusada não é o conteúdo: é **a forma**. Qual
    campo, que tipo veio, que tipo se esperava.

    É o que teria resolvido o caso de 05/10/2026 em trinta segundos em vez
    de exigir uma sessão de investigação: `unreadable_sections` veio
    `list[0]`, esperava-se `str`. Nenhuma linha disto é dado de paciente,
    e por isso pode aparecer na tela e num pedido de suporte.

    O `input` que o Pydantic põe em cada erro **é** o valor recusado, e
    por isso ele é descartado aqui em vez de repassado.
    """
    erros = []
    for erro in exc.errors():
        erros.append({
            'campo': '.'.join(str(parte) for parte in erro.get('loc', ())),
            'tipo': erro.get('type', ''),
            'mensagem': erro.get('msg', ''),
        })
    forma = {}
    if isinstance(data, dict):
        forma = {chave: _tipo_json(valor) for chave, valor in data.items()}
    return {'etapa': 'validacao_de_esquema', 'forma_recebida': forma, 'erros': erros[:20]}


class GraphTimeout(Exception):
    pass


class UnknownTask(Exception):
    pass


def _invoke_with_timeout(chat_model, prompt, timeout_seconds):
    """Chama o provedor e desiste no prazo -- desiste de verdade.

    O `with ThreadPoolExecutor(...)` que estava aqui parecia fazer isso e
    nao fazia: sair do bloco chama `shutdown(wait=True)`, que **espera a
    thread terminar**. O `GraphTimeout` era levantado no prazo e ficava
    preso no `__exit__` ate o provedor responder, de modo que um limite de
    vinte segundos podia segurar o worker por dois minutos -- e o worker
    tem concorrencia dois.

    A thread em si nao da para matar (nao ha como interromper uma chamada
    de rede de fora, em Python); o que da e parar de esperar por ela.
    `shutdown(wait=False)` faz isso, e a thread morre sozinha quando a
    resposta chegar ou a conexao cair -- por isso o timeout **de rede** do
    provedor continua sendo o que impede a thread de viver para sempre.
    """
    executor = ThreadPoolExecutor(max_workers=1)
    future = executor.submit(chat_model.invoke, prompt)
    try:
        return future.result(timeout=timeout_seconds)
    except FutureTimeoutError as exc:
        raise GraphTimeout(
            f'O provedor de IA não respondeu em {timeout_seconds}s.'
        ) from exc
    finally:
        executor.shutdown(wait=False)


def _strip_code_fence(text):
    """Tira a cerca ```json que alguns modelos insistem em pôr.

    Não é indulgência com formato: a alternativa é descartar uma extração
    correta por causa de três acentos graves, e a validação de esquema
    continua valendo integralmente sobre o conteúdo.
    """
    stripped = (text or '').strip()
    if not stripped.startswith('```'):
        return stripped
    stripped = stripped.split('\n', 1)[-1] if '\n' in stripped else ''
    if stripped.rstrip().endswith('```'):
        stripped = stripped.rstrip()[:-3]
    return stripped.strip()


def build_prompt(kind, context_text, extras=None):
    """Monta o prompt da tarefa.

    `extras` existe para o relatório, que é a única tarefa cujo prompt
    depende de algo além do contexto: a finalidade escolhida e o pedido que
    o médico escreveu. Os demais prompts não têm essas chaves, e `format`
    ignora o que não aparece no texto — por isso o parâmetro é opcional e
    não há um segundo caminho para eles.
    """
    try:
        template, _ = TASKS[kind]
    except KeyError as exc:
        raise UnknownTask(f'Sem prompt para o tipo de tarefa {kind!r}') from exc
    return template.format(context=context_text, json_only=_JSON_ONLY, **(extras or {}))


def build_summary_prompt(context_text):
    return build_prompt('encounter_summary', context_text)


def build_graph(chat_model, kind, max_output_chars=DEFAULT_MAX_OUTPUT_CHARS):
    try:
        _, schema = TASKS[kind]
    except KeyError as exc:
        raise UnknownTask(f'Sem esquema para o tipo de tarefa {kind!r}') from exc

    pede_esquema = kind in STRUCTURED_OUTPUT_TASKS

    def call_model(state):
        try:
            response, _ = _chamar_modelo(
                chat_model, state['prompt'], state['timeout_seconds'],
                schema=schema if pede_esquema else None,
            )
        except GraphTimeout as exc:
            # Marcado à parte do texto do erro: o tempo esgotado é falha
            # **de disponibilidade** do provedor, e é o que autoriza a
            # reserva da instalação a responder (`ai/services.py`). Uma
            # resposta que chegou e foi recusada pela validação não é —
            # trocar de provedor não conserta a forma de uma resposta.
            return {'error': str(exc), 'diagnostics': {
                'etapa': 'chamada_ao_provedor', 'tempo_esgotado': True,
            }}
        content = response.content if hasattr(response, 'content') else str(response)
        if len(content) > max_output_chars:
            return {'error': (
                f'A resposta do modelo passou de {max_output_chars} caracteres e foi '
                'descartada por limite de tamanho.'
            )}
        return {'raw_response': content}

    def validate_output(state):
        if state.get('error'):
            return {}
        bruto = _strip_code_fence(state['raw_response'])
        # As duas recusas são separadas porque dizem coisas diferentes a
        # quem lê: "não veio JSON" é o modelo ignorando a instrução de
        # formato; "não tem o formato esperado" é JSON legítimo com um
        # campo fora de forma -- e só o segundo tem forma para descrever.
        try:
            data = json.loads(bruto)
        except json.JSONDecodeError as exc:
            return {
                'error': 'O modelo não respondeu em JSON; a leitura não pôde ser aproveitada.',
                'diagnostics': {
                    'etapa': 'resposta_nao_e_json',
                    'caracteres_recebidos': len(bruto),
                    'erro': str(exc)[:200],
                },
            }
        try:
            artifact = schema.model_validate(data)
        except ValidationError as exc:
            return {
                'error': 'A resposta do modelo não tem o formato esperado.',
                'diagnostics': _diagnostico_de_forma(data, exc),
            }
        return {'artifact': artifact.model_dump(mode='json')}

    graph = StateGraph(GraphState)
    graph.add_node('call_model', call_model)
    graph.add_node('validate_output', validate_output)
    graph.set_entry_point('call_model')
    graph.add_edge('call_model', 'validate_output')
    graph.add_edge('validate_output', END)
    return graph.compile()


def build_summary_graph(chat_model, max_output_chars=DEFAULT_MAX_OUTPUT_CHARS):
    return build_graph(chat_model, 'encounter_summary', max_output_chars=max_output_chars)
