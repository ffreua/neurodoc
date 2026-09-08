"""Provedores de IA que a clínica pode escolher, e como falar com cada um.

O que varia entre provedores é menos do que parece: quase todos expõem a
mesma API da OpenAI em outro endereço, o que permite usar um cliente só
para OpenRouter, NVIDIA, Groq, Mistral, DeepSeek, xAI, Together, Gemini e
qualquer servidor local compatível. A Anthropic é a exceção — API própria,
cabeçalho de autenticação próprio, e por isso um ramo próprio aqui.

A escolha do modelo **não** é escrita à mão. Depois que a chave é gravada,
`list_models` pergunta ao provedor o que ele oferece e a tela mostra a
lista. Digitar identificador de modelo é a forma mais comum de a IA falhar
em produção: o nome está certo hoje, o provedor o aposenta, e o erro só
aparece quando alguém pede um resumo no meio de um atendimento.
"""

import httpx

#: Curto porque isto roda dentro de uma requisição de tela, com o gestor
#: esperando. Provedor lento é resultado — não é motivo para segurar a
#: página até o navegador desistir.
REQUEST_TIMEOUT_SECONDS = 20

#: Teto de modelos guardados. OpenRouter lista mais de trezentos; a tela
#: precisa de uma lista escolhível, não do catálogo inteiro.
MAX_MODELS = 400

OPENAI_COMPATIBLE = 'openai'
ANTHROPIC_NATIVE = 'anthropic'


class ProviderProbeFailed(Exception):
    """A chave não foi aceita, ou o provedor não respondeu.

    Mensagem legível para a tela — nunca o corpo cru da resposta, que pode
    trazer de volta parte da requisição, chave inclusive.
    """


#: `kind` diz qual cliente usar; `base_url` é o endereço padrão, que o
#: campo "endereço da API" pode sobrescrever para servidor próprio.
PROVIDERS = {
    'openrouter': {
        'label': 'OpenRouter',
        'kind': OPENAI_COMPATIBLE,
        'base_url': 'https://openrouter.ai/api/v1',
        'key_url': 'https://openrouter.ai/keys',
        'note': 'Um contrato só para modelos de vários fabricantes. É o padrão '
                'desta instalação.',
    },
    'openai': {
        'label': 'OpenAI',
        'kind': OPENAI_COMPATIBLE,
        'base_url': 'https://api.openai.com/v1',
        'key_url': 'https://platform.openai.com/api-keys',
        'note': '',
    },
    'anthropic': {
        'label': 'Anthropic (Claude)',
        'kind': ANTHROPIC_NATIVE,
        'base_url': 'https://api.anthropic.com/v1',
        'key_url': 'https://console.anthropic.com/settings/keys',
        'note': '',
    },
    'nvidia': {
        'label': 'NVIDIA NIM',
        'kind': OPENAI_COMPATIBLE,
        'base_url': 'https://integrate.api.nvidia.com/v1',
        'key_url': 'https://build.nvidia.com/',
        'note': '',
    },
    'google': {
        'label': 'Google Gemini',
        'kind': OPENAI_COMPATIBLE,
        'base_url': 'https://generativelanguage.googleapis.com/v1beta/openai',
        'key_url': 'https://aistudio.google.com/apikey',
        'note': 'Usa o endereço compatível com a API da OpenAI.',
    },
    'groq': {
        'label': 'Groq',
        'kind': OPENAI_COMPATIBLE,
        'base_url': 'https://api.groq.com/openai/v1',
        'key_url': 'https://console.groq.com/keys',
        'note': '',
    },
    'mistral': {
        'label': 'Mistral',
        'kind': OPENAI_COMPATIBLE,
        'base_url': 'https://api.mistral.ai/v1',
        'key_url': 'https://console.mistral.ai/api-keys',
        'note': '',
    },
    'deepseek': {
        'label': 'DeepSeek',
        'kind': OPENAI_COMPATIBLE,
        'base_url': 'https://api.deepseek.com/v1',
        'key_url': 'https://platform.deepseek.com/api_keys',
        'note': '',
    },
    'xai': {
        'label': 'xAI (Grok)',
        'kind': OPENAI_COMPATIBLE,
        'base_url': 'https://api.x.ai/v1',
        'key_url': 'https://console.x.ai/',
        'note': '',
    },
    'custom': {
        'label': 'Outro provedor compatível com a API da OpenAI',
        'kind': OPENAI_COMPATIBLE,
        'base_url': '',
        'key_url': '',
        'note': 'Para servidor próprio (Ollama, vLLM, LM Studio) ou provedor não '
                'listado. Exige informar o endereço da API.',
    },
}

#: Ordem da lista na tela. OpenRouter primeiro por ser o padrão; `custom`
#: por último porque é a saída para quem não achou o seu.
PROVIDER_CHOICES = [
    (key, PROVIDERS[key]['label'])
    for key in (
        'openrouter', 'openai', 'anthropic', 'nvidia', 'google',
        'groq', 'mistral', 'deepseek', 'xai', 'custom',
    )
]


def resolve_base_url(provider, override=''):
    override = (override or '').strip().rstrip('/')
    if override:
        return override
    return PROVIDERS.get(provider, {}).get('base_url', '')


def provider_kind(provider):
    return PROVIDERS.get(provider, {}).get('kind', OPENAI_COMPATIBLE)


def _friendly_http_error(exc):
    """Transforma a falha HTTP em algo que se leia na tela.

    O corpo da resposta não entra: provedor que devolve eco da requisição
    devolveria a chave junto, e ela iria parar numa mensagem de tela e num
    log.
    """
    status = exc.response.status_code
    if status in (401, 403):
        return 'A chave não foi aceita pelo provedor (401/403). Confira se ela é válida e tem permissão.'
    if status == 404:
        return ('O endereço da API não respondeu como esperado (404). '
                'Confira o endereço, principalmente em provedor próprio.')
    if status == 429:
        return 'O provedor recusou por excesso de requisições (429). Tente de novo em instantes.'
    if status >= 500:
        return f'O provedor respondeu com erro interno ({status}).'
    return f'O provedor recusou a consulta (HTTP {status}).'


def _request(method, url, headers):
    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            response = client.request(method, url, headers=headers)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as exc:
        raise ProviderProbeFailed(_friendly_http_error(exc)) from exc
    except httpx.TimeoutException as exc:
        raise ProviderProbeFailed(
            f'O provedor não respondeu em {REQUEST_TIMEOUT_SECONDS} segundos.',
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderProbeFailed(
            f'Não foi possível falar com o provedor ({exc.__class__.__name__}).',
        ) from exc
    except ValueError as exc:
        raise ProviderProbeFailed(
            'O provedor respondeu algo que não é JSON. Confira o endereço da API.',
        ) from exc


def list_models(provider, api_key, base_url=''):
    """Os modelos que este provedor oferece.

    **Não** serve para validar a chave. O `/models` de vários provedores é
    público — o do OpenRouter devolve o catálogo inteiro sem credencial
    alguma —, então uma resposta com centenas de modelos não diz nada sobre
    a chave enviada. Quem prova a credencial é `probe_model`, que faz uma
    chamada de verdade ao modelo.

    A chave vai junto mesmo assim: nos provedores em que o endpoint é
    autenticado, ela é o que faz a lista refletir o que **aquela conta**
    pode usar, em vez do catálogo público.
    """
    if not api_key:
        raise ProviderProbeFailed('Informe a chave da API antes de consultar os modelos.')
    endpoint = resolve_base_url(provider, base_url)
    if not endpoint:
        raise ProviderProbeFailed('Informe o endereço da API deste provedor.')

    if provider_kind(provider) == ANTHROPIC_NATIVE:
        payload = _request('GET', f'{endpoint}/models', {
            'x-api-key': api_key,
            'anthropic-version': '2023-06-01',
        })
    else:
        payload = _request('GET', f'{endpoint}/models', {
            'Authorization': f'Bearer {api_key}',
        })

    rows = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        raise ProviderProbeFailed(
            'O provedor respondeu sem a lista de modelos. Confira o endereço da API.',
        )
    names = []
    for row in rows:
        identifier = row.get('id') if isinstance(row, dict) else None
        if identifier:
            names.append(str(identifier))
    # Ordenado para a lista da tela não mudar de ordem a cada consulta, o
    # que faria o modelo escolhido "pular de lugar" sem nada ter mudado.
    return sorted(set(names))[:MAX_MODELS]


#: Pergunta fixa e sem conteúdo clínico. O teste prova que o modelo
#: responde; mandar dado de paciente para provar isso seria enviar
#: prontuário a um provedor que ainda não se sabe se funciona.
PROBE_PROMPT = 'Responda apenas com a palavra: ok'


def probe_model(provider, api_key, model, base_url=''):
    """Manda uma pergunta mínima ao modelo escolhido.

    Listar modelos prova a chave; isto prova o **modelo**. São falhas
    diferentes e o gestor precisa distinguir: chave errada e identificador
    de modelo aposentado dão a mesma tela de erro quando alguém pede um
    resumo, e a diferença entre elas é quem precisa resolver.
    """
    if not model:
        raise ProviderProbeFailed('Escolha um modelo antes de testar.')
    endpoint = resolve_base_url(provider, base_url)

    try:
        with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            if provider_kind(provider) == ANTHROPIC_NATIVE:
                response = client.post(
                    f'{endpoint}/messages',
                    headers={'x-api-key': api_key, 'anthropic-version': '2023-06-01'},
                    json={
                        'model': model, 'max_tokens': 16,
                        'messages': [{'role': 'user', 'content': PROBE_PROMPT}],
                    },
                )
                response.raise_for_status()
                blocks = response.json().get('content') or []
                text = ''.join(b.get('text', '') for b in blocks if isinstance(b, dict))
            else:
                response = client.post(
                    f'{endpoint}/chat/completions',
                    headers={'Authorization': f'Bearer {api_key}'},
                    json={
                        'model': model, 'max_tokens': 16,
                        'messages': [{'role': 'user', 'content': PROBE_PROMPT}],
                    },
                )
                response.raise_for_status()
                choices = response.json().get('choices') or []
                text = (choices[0].get('message', {}).get('content') or '') if choices else ''
    except httpx.HTTPStatusError as exc:
        detail = _friendly_http_error(exc)
        if exc.response.status_code in (400, 404):
            detail = (f'O provedor não reconheceu o modelo "{model}". '
                      'Recarregue a lista de modelos e escolha outro.')
        raise ProviderProbeFailed(detail) from exc
    except httpx.TimeoutException as exc:
        raise ProviderProbeFailed(
            f'O modelo não respondeu em {REQUEST_TIMEOUT_SECONDS} segundos.',
        ) from exc
    except httpx.HTTPError as exc:
        raise ProviderProbeFailed(
            f'Não foi possível falar com o provedor ({exc.__class__.__name__}).',
        ) from exc

    return (text or '').strip()[:120]
