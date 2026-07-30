"""Đối chiếu cấu hình + lỗi OCR giữa máy local và container Docker.

Chạy CÙNG script ở hai nơi rồi so output, để tách "khác code" khỏi "khác môi trường".

    # trong container
    docker exec immigration-ai-backend python scripts/diag_ocr.py

    # trên máy dev (từ thư mục backend)
    .venv/Scripts/python.exe scripts/diag_ocr.py

Không in ra API key, chỉ in tiền tố và độ dài để so sánh.
Thêm --live để gọi thử OpenAI (1 request nhỏ, vài chục token).
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import async_session  # noqa: E402
from app.models.entities import ApiUsageLog, Document  # noqa: E402


def _mask(secret: str) -> str:
    """Đủ để so hai nơi có cùng key không, không đủ để dùng lại key."""
    secret = (secret or "").strip()
    if not secret:
        return "(TRỐNG)"
    return f"{secret[:9]}... (dài {len(secret)})"


def show_config() -> None:
    print("=" * 60)
    print("CẤU HÌNH HIỆU LỰC")
    print("=" * 60)
    print(f"  openai_model            = {settings.openai_model!r}")
    print(f"  openai_base_url         = {settings.openai_base_url!r}")
    print(f"  openai_api_key          = {_mask(settings.openai_api_key)}")
    print(f"  vision_model            = {settings.vision_model!r}")
    print(f"  ocr_model (thực dùng)   = {settings.ocr_model!r}")
    print(f"  ocr_base_url            = {settings.ocr_base_url!r}")
    print(f"  ocr_api_key             = {_mask(settings.ocr_api_key)}")
    print(f"  ocr_worksheet_rows      = {settings.ocr_worksheet_rows}")
    print(f"  ocr_worksheet_cols      = {settings.ocr_worksheet_cols}")
    print(f"  ocr_max_images_per_req  = {settings.ocr_max_images_per_request}")
    db_url = settings.resolved_database_url
    print(f"  database                = {db_url.split('://', 1)[0]}://...")


def show_versions() -> None:
    print()
    print("=" * 60)
    print("THƯ VIỆN (khác phiên bản giữa 2 nơi là nghi phạm)")
    print("=" * 60)
    print(f"  python  = {sys.version.split()[0]}")
    for name in ("openai", "httpx", "httpcore", "fitz", "PIL"):
        try:
            mod = __import__(name)
            version = getattr(mod, "__version__", None) or getattr(
                mod, "version", "?"
            )
            print(f"  {name:8}= {version}")
        except Exception as exc:  # pragma: no cover - chỉ để chẩn đoán
            print(f"  {name:8}= KHÔNG IMPORT ĐƯỢC ({type(exc).__name__}: {exc})")


async def show_errors() -> None:
    print()
    print("=" * 60)
    print("LỖI ĐÃ GHI TRONG DB")
    print("=" * 60)
    async with async_session() as session:
        docs = (
            await session.execute(
                select(Document.original_filename, Document.status, Document.error_message)
                .where(Document.error_message.is_not(None))
                .order_by(Document.uploaded_at.desc())
                .limit(5)
            )
        ).all()
        print(f"-- documents có error_message: {len(docs)}")
        for filename, doc_status, error in docs:
            print(f"   [{doc_status}] {filename}")
            print(f"       {error!r}")

        logs = (
            await session.execute(
                select(
                    ApiUsageLog.created_at,
                    ApiUsageLog.operation,
                    ApiUsageLog.model,
                    ApiUsageLog.error_message,
                )
                .where(ApiUsageLog.success.is_(False))
                .order_by(ApiUsageLog.created_at.desc())
                .limit(5)
            )
        ).all()
        print(f"-- api_usage_logs thất bại: {len(logs)}")
        for created, operation, model, error in logs:
            print(f"   {created} {operation} ({model})")
            print(f"       {error!r}")


async def live_call() -> None:
    """Gọi thật qua ĐÚNG client mà OCR dùng — bắt được lỗi mà httpx trần không thấy."""
    print()
    print("=" * 60)
    print("GỌI THỬ QUA OCR CLIENT (async, giống hệt đường OCR chạy)")
    print("=" * 60)
    from app.services.llm_client import get_ocr_client

    client = get_ocr_client()
    try:
        # Không truyền max_tokens: một số model (gpt-5.x) từ chối tham số này và
        # lỗi 400 đó sẽ che mất thứ ta đang muốn đo là kết nối.
        response = await client.chat.completions.create(
            model=settings.ocr_model,
            messages=[{"role": "user", "content": "reply with OK"}],
        )
        print(f"  THÀNH CÔNG: {response.choices[0].message.content!r}")
    except Exception as exc:
        print(f"  THẤT BẠI: {type(exc).__name__}: {exc}")
        cause = exc.__cause__
        while cause is not None:
            print(f"     do: {type(cause).__name__}: {cause}")
            cause = cause.__cause__


async def main() -> None:
    show_config()
    show_versions()
    try:
        await show_errors()
    except Exception as exc:
        print(f"  (không đọc được DB: {type(exc).__name__}: {exc})")
    if "--live" in sys.argv:
        await live_call()


if __name__ == "__main__":
    asyncio.run(main())
