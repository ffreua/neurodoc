"""Qual modelo de IA atende esta chamada: o da clínica, senão o da instalação.

Os dois caminhos montam o cliente **pelo catálogo** (`catalog.PROVIDERS`).
Eles não faziam isso: o caminho da clínica passou a usar o catálogo quando
os dez provedores foram cadastrados, e o da instalação ficou preso a um
mapa de três — `openrouter`, `openai`, `anthropic` —, cada um num módulo
próprio que repetia a mesma montagem com outro nome de chave.

O efeito era um defeito silencioso de configuração: `AI_PROVIDER=nvidia`
no `.env` levantava "Unknown AI provider", ainda que a NVIDIA estivesse
no catálogo e funcionasse perfeitamente quando uma clínica a escolhia pela
tela. Quem hospeda o sistema para si — e é para essa pessoa que existe o
padrão da instalação — não alcançava sete dos dez provedores.

Com uma montagem só, acrescentar provedor ao catálogo passa a valer nos
dois caminhos de uma vez, que é o que já se esperava do catálogo.
"""

from django.conf import settings

from .base import ProviderUnavailable
from .catalog import ANTHROPIC_NATIVE, PROVIDERS, provider_kind, resolve_base_url

REQUEST_TIMEOUT_SECONDS = 60

#: Limitação conhecida das rotas compatíveis com a API da OpenAI, e a razão
#: de `ai/graphs.py` validar a resposta contra o schema Pydantic por conta
#: própria: agregadores como o OpenRouter intermediam modelos de vários
#: fabricantes, e o suporte a JSON estruturado e a chamada de ferramenta
#: varia conforme o modelo por baixo — não é garantido que se comporte como
#: o da OpenAI. Depender da imposição do lado do provedor faria a saída
#: inválida passar em silêncio num modelo e falhar em outro.


def _tenant_settings(tenant_id):
    if tenant_id is None:
        return None
    from ai.models import AIProviderSettings

    row = AIProviderSettings.objects.filter(tenant_id=tenant_id).first()
    return row if row is not None and row.is_usable else None


def _build(provider, model, api_key, base_url=''):
    """O cliente de chat, para qualquer provedor do catálogo.

    Quase todos expõem a API da OpenAI em outro endereço, o que permite um
    cliente só com `base_url` trocado. A Anthropic tem API própria e por
    isso um ramo próprio — é a única exceção, e é do catálogo que se
    descobre qual é qual.
    """
    if provider_kind(provider) == ANTHROPIC_NATIVE:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=model, api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS,
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=model, api_key=api_key,
        base_url=resolve_base_url(provider, base_url),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


def _model_from_tenant_settings(row):
    """Cliente montado com a configuração daquela clínica."""
    from base.crypto import SecretUnavailable

    try:
        api_key = row.api_key()
    except SecretUnavailable as exc:
        # Chave que não abre é indisponibilidade, não configuração vazia:
        # tratá-la como ausente faria o sistema chamar o provedor sem
        # credencial e reportar o erro dele em vez do erro real.
        raise ProviderUnavailable(f'Chave de IA da clínica indisponível: {exc}') from exc

    return _build(row.provider, row.model, api_key, row.base_url)


def installation_secret_name(provider):
    """O secret que carrega a chave deste provedor na instalação.

    Derivado do identificador do provedor, e não de um mapa à parte: um
    mapa se desatualiza em relação ao catálogo, e a forma de descobrir isso
    seria a mesma que motivou este módulo — alguém configurando um provedor
    que a tela oferece e o servidor recusa.
    """
    return f'NEURODOC_{provider.upper()}_API_KEY'


def installation_api_key(provider):
    """A chave da instalação para **este** provedor, lida na hora.

    Não vem de `settings.AI_API_KEY`, que é resolvida uma vez na carga do
    processo a partir de `AI_PROVIDER`: com o provedor escolhido no
    console, trocar de provedor passaria a ler a chave do provedor antigo
    até alguém republicar — que é exatamente o ciclo de deploy que o
    console existe para dispensar.

    Vazio em vez de exceção quando o secret não está montado: quem decide
    o que fazer com a falta é quem chama, e o processo `app` **não tem
    nenhuma dessas chaves**, de propósito (§2). Lá a resposta certa é
    "não sei", não "não existe".
    """
    from ops.env import secret

    try:
        return secret(f'{provider.upper()}_API_KEY', required=False)
    except ValueError:
        # `secret()` recusa configuração ambígua (variável e arquivo ao
        # mesmo tempo). Isso é erro de implantação, não de IA: tratá-lo
        # como chave ausente dá a mensagem certa a quem opera o servidor.
        return ''


def _installation_model():
    """O padrão da instalação: provedor, modelo e chave.

    Vale para toda clínica que não configurou a sua. **Provedor e modelo
    vêm do console** (`base.models.InstallationSettings`), não mais do
    `.env` — ver o comentário lá, que conta por que: o modelo do `.env`
    foi aposentado pelo provedor em 2026-08-26, passou a responder `410
    Gone`, e trocá-lo exigia um ciclo de deploy.

    A **chave** continua vindo de secret, e não do console, de propósito:
    ela é credencial, o console roda no processo `app`, e o `app` não
    recebe nenhuma chave de provedor. Quem pode trocar o modelo não
    precisa poder ler a chave.

    A mensagem de erro nomeia o secret que falta, porque "chave não
    configurada" sozinho manda quem opera o servidor procurar em três
    lugares.
    """
    from base.models import InstallationSettings

    provider, model, base_url = InstallationSettings.carregar().ia_da_instalacao()
    if provider not in PROVIDERS:
        conhecidos = ', '.join(sorted(PROVIDERS))
        raise ProviderUnavailable(
            f'O provedor de IA da instalação ({provider!r}) não está no catálogo. '
            f'Conhecidos: {conhecidos}. Escolha outro em /instalacao/operacao/.'
        )
    api_key = installation_api_key(provider)
    if not api_key:
        raise ProviderUnavailable(
            f'Nenhuma chave de IA configurada para o provedor da instalação '
            f'({provider}). Grave o secret {installation_secret_name(provider)}.'
        )
    if not model:
        raise ProviderUnavailable(
            f'Nenhum modelo de IA escolhido para o provedor da instalação '
            f'({provider}). Escolha um em /instalacao/operacao/.'
        )
    return _build(provider, model, api_key, base_url)


def get_chat_model(provider=None, tenant_id=None):
    """O modelo de chat a usar: o da clínica, se ela configurou o seu.

    A ordem é deliberada. A clínica que informou provedor, chave e modelo
    quer que os dados dela vão para **aquele** contrato — cair no provedor
    da instalação seria mandar prontuário para outro lugar sem ninguém ter
    pedido. A configuração da instalação continua valendo para quem não
    configurou a própria, que é o caso de quem hospeda o sistema para si.

    Trocar de provedor segue sendo ato explícito, nunca substituição
    silenciosa quando um falha (RT-04).
    """
    if not settings.AI_ENABLED:
        raise ProviderUnavailable('AI_ENABLED=False')
    row = _tenant_settings(tenant_id)
    if row is not None and provider is None:
        return _model_from_tenant_settings(row)
    if provider is not None:
        # Provedor pedido explicitamente pelo chamador continua usando a
        # credencial da instalação: é assim que ele era atendido antes, e
        # não há chave de clínica para um provedor que ela não escolheu.
        if provider != settings.AI_PROVIDER:
            raise ProviderUnavailable(
                f'Provedor {provider!r} pedido explicitamente, mas a instalação só '
                f'tem credencial para {settings.AI_PROVIDER!r}.'
            )
    return _installation_model()


def active_provider_label(tenant_id=None):
    """Nome do provedor em uso, para a tela dizer para onde os dados vão."""
    row = _tenant_settings(tenant_id)
    key = row.provider if row is not None else settings.AI_PROVIDER
    return PROVIDERS.get(key, {}).get('label', key)


__all__ = [
    'get_chat_model', 'ProviderUnavailable', 'active_provider_label',
    'installation_secret_name',
]
