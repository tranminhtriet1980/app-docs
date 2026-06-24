"""OpenAI client."""

from openai import AsyncOpenAI

from app.config import settings


def get_openai_client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    return AsyncOpenAI(api_key=settings.openai_api_key)


def is_openai_configured() -> bool:
    return bool(settings.openai_api_key)
