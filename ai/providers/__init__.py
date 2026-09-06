from django.conf import settings

from .anthropic_provider import get_chat_model as _anthropic_chat_model
from .base import ProviderUnavailable
from .openai_provider import get_chat_model as _openai_chat_model
from .openrouter import get_chat_model as _openrouter_chat_model

_GETTERS = {
    'openrouter': _openrouter_chat_model,
    'openai': _openai_chat_model,
    'anthropic': _anthropic_chat_model,
}


def get_chat_model(provider=None):
    """Provider selection is always explicit (an argument or
    settings.AI_PROVIDER) -- switching provider is a deliberate config
    change, never a silent fallback that could widen the data policy
    (RT-04: "troca de provedor é explícita e não amplia política de dados").
    """
    provider = provider or settings.AI_PROVIDER
    getter = _GETTERS.get(provider)
    if getter is None:
        raise ProviderUnavailable(f'Unknown AI provider: {provider}')
    return getter()


__all__ = ['get_chat_model', 'ProviderUnavailable']
