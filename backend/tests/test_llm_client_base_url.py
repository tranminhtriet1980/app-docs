"""Client OpenAI phải bỏ qua biến môi trường OPENAI_BASE_URL rỗng.

Sự cố prod 30/07/2026: compose khai `OPENAI_BASE_URL: ${OPENAI_BASE_URL:-}` nên biến
tồn tại trong container với giá trị RỖNG. SDK chỉ kiểm tra `is None` khi đọc biến này,
nên chuỗi rỗng lọt qua và thành base URL — httpx ném `UnsupportedProtocol`, người dùng
thấy `Connection error.` Mọi lệnh gọi OpenAI chết mà không hề rời khỏi container.
"""

import pytest

from app.services import llm_client
from app.services.llm_client import (
    DEFAULT_OPENAI_BASE_URL,
    get_ocr_client,
    get_openai_client,
)


@pytest.fixture(autouse=True)
def _blank_base_url_env(monkeypatch):
    """Tái hiện container: biến CÓ mặt nhưng rỗng."""
    monkeypatch.setenv("OPENAI_BASE_URL", "")
    monkeypatch.setattr(llm_client.settings, "openai_api_key", "sk-test", raising=False)
    monkeypatch.setattr(llm_client.settings, "openai_base_url", "", raising=False)
    monkeypatch.setattr(llm_client.settings, "ocr_api_key", "", raising=False)
    monkeypatch.setattr(llm_client.settings, "ocr_base_url", "", raising=False)


def test_chat_client_ignores_blank_env_base_url():
    assert str(get_openai_client().base_url).rstrip("/") == DEFAULT_OPENAI_BASE_URL


def test_ocr_client_ignores_blank_env_base_url():
    assert str(get_ocr_client().base_url).rstrip("/") == DEFAULT_OPENAI_BASE_URL


def test_base_url_always_has_scheme():
    """Chốt chặn thẳng vào triệu chứng: thiếu scheme là httpx nổ."""
    for client in (get_openai_client(), get_ocr_client()):
        assert str(client.base_url).startswith("https://")


def test_explicit_base_url_still_wins(monkeypatch):
    """Cấu hình thật vẫn phải được tôn trọng — không phải cứ ép về OpenAI."""
    monkeypatch.setattr(
        llm_client.settings, "openai_base_url", "https://openrouter.ai/api/v1", raising=False
    )
    assert "openrouter.ai" in str(get_openai_client().base_url)


def test_ocr_base_url_overrides_chat(monkeypatch):
    monkeypatch.setattr(
        llm_client.settings, "openai_base_url", "https://openrouter.ai/api/v1", raising=False
    )
    monkeypatch.setattr(
        llm_client.settings, "ocr_base_url", "https://gemini.example/v1", raising=False
    )
    assert "gemini.example" in str(get_ocr_client().base_url)
    assert "openrouter.ai" in str(get_openai_client().base_url)
