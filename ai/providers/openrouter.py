from django.conf import settings
from langchain_openai import ChatOpenAI

from .base import ProviderUnavailable

# OpenRouter is OpenAI-API-compatible (langchain_openai talks to it via
# base_url); "z-ai/glm-5.3-flash" (settings.AI_MODEL) is the explicit
# default model identifier -- never resolved implicitly by the provider.
BASE_URL = 'https://openrouter.ai/api/v1'
REQUEST_TIMEOUT_SECONDS = 60

# Known baseline limitations of this route, documented per S11-T02's
# acceptance ("identificador, streaming/tools e limitações de schema
# documentados"): OpenRouter proxies many upstream models, so structured
# JSON-mode / tool-calling support varies per underlying model and is not
# guaranteed to match OpenAI's native behavior 1:1 -- this is why
# ai/graphs.py parses and validates the raw text response against the
# Pydantic schema itself, rather than relying on provider-side structured
# output/function-calling enforcement.


def get_chat_model():
    if not settings.AI_ENABLED:
        raise ProviderUnavailable('AI_ENABLED=False')
    if not settings.OPENROUTER_API_KEY:
        raise ProviderUnavailable('OPENROUTER_API_KEY not configured')
    return ChatOpenAI(
        model=settings.AI_MODEL, api_key=settings.OPENROUTER_API_KEY, base_url=BASE_URL,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
