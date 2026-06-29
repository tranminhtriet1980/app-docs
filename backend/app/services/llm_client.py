"""OpenAI client."""

from openai import AsyncOpenAI

from app.config import settings


def get_openai_client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    base_url = (settings.openai_base_url or "").strip()
    if base_url:
        return AsyncOpenAI(api_key=settings.openai_api_key, base_url=base_url)
    return AsyncOpenAI(api_key=settings.openai_api_key)


def get_ocr_client() -> AsyncOpenAI:
    """Client cho OCR tài liệu — dùng key/base_url riêng nếu đặt, ngược lại kế thừa cấu hình chat."""
    api_key = (settings.ocr_api_key or "").strip() or settings.openai_api_key
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    base_url = (settings.ocr_base_url or settings.openai_base_url or "").strip()
    if base_url:
        return AsyncOpenAI(api_key=api_key, base_url=base_url)
    return AsyncOpenAI(api_key=api_key)


def is_openai_configured() -> bool:
    return bool(settings.openai_api_key)
