from django.conf import settings

from .anthropic_provider import get_chat_model as _anthropic_chat_model
from .base import ProviderUnavailable
from .catalog import ANTHROPIC_NATIVE, PROVIDERS, provider_kind, resolve_base_url
from .openai_provider import get_chat_model as _openai_chat_model
from .openrouter import get_chat_model as _openrouter_chat_model

_GETTERS = {
    'openrouter': _openrouter_chat_model,
    'openai': _openai_chat_model,
    'anthropic': _anthropic_chat_model,
}

REQUEST_TIMEOUT_SECONDS = 60


def _tenant_settings(tenant_id):
    if tenant_id is None:
        return None
    from ai.models import AIProviderSettings

    row = AIProviderSettings.objects.filter(tenant_id=tenant_id).first()
    return row if row is not None and row.is_usable else None


def _model_from_tenant_settings(row):
    """Cliente montado com a configuração daquela clínica.

    Um cliente só para quase todos os provedores: OpenRouter, NVIDIA, Groq,
    Mistral, Gemini e servidor próprio falam a API da OpenAI em endereços
    diferentes, e `langchain_openai` aceita `base_url`. A Anthropic tem API
    própria e por isso um ramo próprio.
    """
    from base.crypto import SecretUnavailable

    try:
        api_key = row.api_key()
    except SecretUnavailable as exc:
        # Chave que não abre é indisponibilidade, não configuração vazia:
        # tratá-la como ausente faria o sistema chamar o provedor sem
        # credencial e reportar o erro dele em vez do erro real.
        raise ProviderUnavailable(f'Chave de IA da clínica indisponível: {exc}') from exc

    if provider_kind(row.provider) == ANTHROPIC_NATIVE:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=row.model, api_key=api_key, timeout=REQUEST_TIMEOUT_SECONDS,
        )

    from langchain_openai import ChatOpenAI

    return ChatOpenAI(
        model=row.model, api_key=api_key,
        base_url=resolve_base_url(row.provider, row.base_url),
        timeout=REQUEST_TIMEOUT_SECONDS,
    )


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
    row = _tenant_settings(tenant_id)
    if row is not None and provider is None:
        if not settings.AI_ENABLED:
            raise ProviderUnavailable('AI_ENABLED=False')
        return _model_from_tenant_settings(row)

    provider = provider or settings.AI_PROVIDER
    getter = _GETTERS.get(provider)
    if getter is None:
        raise ProviderUnavailable(f'Unknown AI provider: {provider}')
    return getter()


def active_provider_label(tenant_id=None):
    """Nome do provedor em uso, para a tela dizer para onde os dados vão."""
    row = _tenant_settings(tenant_id)
    key = row.provider if row is not None else settings.AI_PROVIDER
    return PROVIDERS.get(key, {}).get('label', key)


__all__ = [
    'get_chat_model', 'ProviderUnavailable', 'active_provider_label',
]
