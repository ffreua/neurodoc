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
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from .schemas import (
    ClinicalSummaryArtifact, DiagnosticSupportArtifact, LabExtractionArtifact,
    PatientReportArtifact, ReportTranscriptionArtifact,
)

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

LAB_EXTRACTION_PROMPT = """Transcreva os resultados do laudo laboratorial abaixo em dados \
estruturados. Você é um transcritor, não um intérprete.

Regras que não admitem exceção:
1. Copie a faixa de referência **do próprio laudo**. Nunca traga faixa de referência de \
memória ou de outro laboratório: ela varia com laboratório, método, idade e sexo.
2. Se o laudo não trouxer faixa para um analito, deixe "reference_low", "reference_high" \
como null e "reference_text" vazio. NÃO invente e NÃO diga se o valor é normal — quem \
classifica é o sistema, comparando com a faixa que veio no papel.
3. Preencha "numeric_value" só quando o resultado for um número; resultado como \
"não reagente" ou "< 0,3" vai apenas em "value_text" (e o operador de comparação fica lá).
4. "value_text" reproduz o resultado como está escrito, com a vírgula decimal do laudo se \
for o caso. "numeric_value" usa ponto decimal.
5. Trecho ilegível ou cortado vai em "unreadable_sections", nomeando o que ficou de fora. \
Não preencha por dedução.

{json_only} Campos: "exam_name", "collected_on" (data como está no laudo), \
"service_name", "analytes" (lista de objetos com "analyte", "value_text", "numeric_value", \
"unit", "reference_low", "reference_high", "reference_text"), "unreadable_sections", \
"limitations", "requires_physician_review" (sempre true), "disclaimer".

Texto do documento (já desidentificado):
{context}
"""

REPORT_TRANSCRIPTION_PROMPT = """Identifique o tipo de exame do documento abaixo e transcreva \
o laudo. Você transcreve, não interpreta e não resume.

Regras que não admitem exceção:
1. "report_text" reproduz a descrição do laudo como está escrita. Não resuma, não reordene \
e não corrija: o detalhe que parece redundante é justamente o que dá sentido ao achado.
2. "conclusion" recebe apenas a conclusão/impressão que o laudo declara. Se o laudo não \
tem conclusão explícita, deixe vazio — não escreva uma.
3. Não acrescente hipótese, correlação clínica ou recomendação que não esteja no documento.
4. "detected_category": "imaging" para tomografia, ressonância, ultrassom, radiografia; \
"neurophysiology" para eletroencefalograma, eletroneuromiografia, potencial evocado, \
polissonografia; "laboratory" para exame de sangue, urina ou liquor; "pathology" para \
anatomia patológica; "genetics" para exame genético; "other" quando não se encaixar.
5. Trecho ilegível vai em "unreadable_sections", nomeando o que ficou de fora.

{json_only} Campos: "detected_category", "exam_name", "performed_on", "service_name", \
"report_text", "conclusion", "unreadable_sections", "limitations", \
"requires_physician_review" (sempre true), "disclaimer".

Texto do documento (já desidentificado):
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
    'lab_extraction': (LAB_EXTRACTION_PROMPT, LabExtractionArtifact),
    'report_transcription': (REPORT_TRANSCRIPTION_PROMPT, ReportTranscriptionArtifact),
}


class GraphState(TypedDict):
    prompt: str
    timeout_seconds: int
    raw_response: Optional[str]
    artifact: Optional[dict]
    error: Optional[str]


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
        raise GraphTimeout(f'Model call exceeded {timeout_seconds}s') from exc
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

    def call_model(state):
        try:
            response = _invoke_with_timeout(chat_model, state['prompt'], state['timeout_seconds'])
        except GraphTimeout as exc:
            return {'error': str(exc)}
        content = response.content if hasattr(response, 'content') else str(response)
        if len(content) > max_output_chars:
            return {'error': f'Response exceeds {max_output_chars} characters (cost/length limit)'}
        return {'raw_response': content}

    def validate_output(state):
        if state.get('error'):
            return {}
        try:
            data = json.loads(_strip_code_fence(state['raw_response']))
            artifact = schema.model_validate(data)
        except (json.JSONDecodeError, ValidationError) as exc:
            return {'error': f'Model output failed schema validation: {exc}'}
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
