"""OpenAI client."""

from openai import AsyncOpenAI

from app.config import settings

# Endpoint mặc định của OpenAI. Phải truyền TƯỜNG MINH, không được để SDK tự lo.
#
# Khi không nhận base_url, SDK đọc biến môi trường OPENAI_BASE_URL và chỉ kiểm tra
# `is None` — chuỗi RỖNG lọt qua và được dùng làm base URL, khiến httpx ném
# `UnsupportedProtocol: Request URL is missing an 'http://' or 'https://' protocol`,
# nổi lên thành `APIConnectionError: Connection error.`
#
# docker-compose khai `OPENAI_BASE_URL: ${OPENAI_BASE_URL:-}` nên biến LUÔN tồn tại
# trong container dù rỗng ⇒ toàn bộ lệnh gọi OpenAI chết. Sự cố prod 30/07/2026.
DEFAULT_OPENAI_BASE_URL = "https://api.openai.com/v1"


def get_openai_client() -> AsyncOpenAI:
    if not settings.openai_api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    base_url = (settings.openai_base_url or "").strip() or DEFAULT_OPENAI_BASE_URL
    return AsyncOpenAI(api_key=settings.openai_api_key, base_url=base_url)


def get_ocr_client() -> AsyncOpenAI:
    """Client cho OCR tài liệu — dùng key/base_url riêng nếu đặt, ngược lại kế thừa cấu hình chat.

    max_retries cao hơn mặc định (2) vì OCR gửi nhiều ảnh liên tiếp và dễ chạm trần
    tokens-per-minute; SDK tôn trọng header `retry-after` của 429 nên chờ thêm vài nhịp
    là qua. Chỉ giúp khi từng request đã nằm dưới trần — request vượt trần thì retry vô
    ích, phải chia nhỏ (xem ocr_max_images_per_request).
    """
    api_key = (settings.ocr_api_key or "").strip() or settings.openai_api_key
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY not configured")
    base_url = (
        (settings.ocr_base_url or settings.openai_base_url or "").strip()
        or DEFAULT_OPENAI_BASE_URL
    )
    return AsyncOpenAI(api_key=api_key, base_url=base_url, max_retries=5)


def is_openai_configured() -> bool:
    return bool(settings.openai_api_key)
