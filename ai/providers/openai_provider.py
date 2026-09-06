from django.conf import settings
from langchain_openai import ChatOpenAI

from .base import ProviderUnavailable

REQUEST_TIMEOUT_SECONDS = 60


def get_chat_model():
    """No hardcoded fallback model name: settings.AI_MODEL is the single
    explicit identifier for whichever provider is selected -- switching
    provider without also reviewing the model identifier is a
    configuration mistake this deliberately does not paper over.
    """
    if not settings.AI_ENABLED:
        raise ProviderUnavailable('AI_ENABLED=False')
    if not settings.OPENAI_API_KEY:
        raise ProviderUnavailable('OPENAI_API_KEY not configured')
    return ChatOpenAI(model=settings.AI_MODEL, api_key=settings.OPENAI_API_KEY, timeout=REQUEST_TIMEOUT_SECONDS)
