from django.conf import settings
from langchain_anthropic import ChatAnthropic

from .base import ProviderUnavailable

REQUEST_TIMEOUT_SECONDS = 60


def get_chat_model():
    if not settings.AI_ENABLED:
        raise ProviderUnavailable('AI_ENABLED=False')
    if not settings.ANTHROPIC_API_KEY:
        raise ProviderUnavailable('ANTHROPIC_API_KEY not configured')
    return ChatAnthropic(
        model=settings.AI_MODEL, api_key=settings.ANTHROPIC_API_KEY, timeout=REQUEST_TIMEOUT_SECONDS,
    )
