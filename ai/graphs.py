import json
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Optional, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import ValidationError

from .schemas import ClinicalSummaryArtifact

DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_MAX_OUTPUT_CHARS = 20000

PROMPT_TEMPLATE = """Você é um assistente que organiza informações administrativas e clínicas \
já autorizadas e desidentificadas para apoio à revisão médica. NUNCA invente dados que não \
estejam no contexto abaixo. Responda apenas com um objeto JSON válido, sem texto fora do JSON, \
com exatamente estes campos: "summary" (string), "qualitative_hypotheses" (lista de strings, \
NUNCA com percentuais ou probabilidades numéricas), "missing_information" (string), \
"limitations" (string), "source_refs" (lista de objetos com "type", "id", "version_or_hash").

Contexto (já desidentificado):
{context}
"""


class GraphState(TypedDict):
    prompt: str
    timeout_seconds: int
    raw_response: Optional[str]
    artifact: Optional[dict]
    error: Optional[str]


class GraphTimeout(Exception):
    pass


def _invoke_with_timeout(chat_model, prompt, timeout_seconds):
    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(chat_model.invoke, prompt)
        try:
            return future.result(timeout=timeout_seconds)
        except FutureTimeoutError as exc:
            raise GraphTimeout(f'Model call exceeded {timeout_seconds}s') from exc


def build_summary_prompt(context_text):
    return PROMPT_TEMPLATE.format(context=context_text)


def build_summary_graph(chat_model, max_output_chars=DEFAULT_MAX_OUTPUT_CHARS):
    """Two nodes only: call the model, then validate its output against the
    Pydantic schema. There is no third "present to user" node here on
    purpose -- an invalid or over-length response never reaches a state
    that could be mistaken for a valid artifact; the caller (ai.services)
    checks `state['error']` before persisting anything.
    """

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
            data = json.loads(state['raw_response'])
            artifact = ClinicalSummaryArtifact.model_validate(data)
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
