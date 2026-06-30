"""Copy all data from the local SQLite DB into the Docker PostgreSQL database.

Local dev chạy SQLite (backend/immigration.db), còn Docker prod dùng PostgreSQL,
nên không thể import thẳng file .db. Script này đọc từng bảng từ SQLite rồi ghi
sang Postgres theo đúng thứ tự khóa ngoại (dùng chính models của app, nên kiểu
UUID / Enum / Boolean / Datetime được chuyển đổi chính xác).

CẢNH BÁO: script XÓA sạch dữ liệu hiện có trong Postgres đích trước khi copy.
Chỉ chạy khi muốn thay toàn bộ dữ liệu Postgres bằng dữ liệu SQLite local.

Cách dùng
---------
1) Bật stack Docker (Postgres phải đang chạy):
     docker compose -f docker-compose.prod.yml --env-file .env.production up -d postgres

2) Mở cổng Postgres ra host nếu chưa có (docker-compose.prod.yml mặc định KHÔNG
   publish 5432). Cách nhanh nhất: chạy script NGAY TRONG container backend:
     docker compose -f docker-compose.prod.yml --env-file .env.production cp \
         backend/scripts/migrate_sqlite_to_postgres.py immigration-ai-backend:/tmp/migrate.py
     docker compose -f docker-compose.prod.yml --env-file .env.production cp \
         backend/immigration.db immigration-ai-backend:/app/immigration.db
     docker compose -f docker-compose.prod.yml --env-file .env.production exec backend \
         python /tmp/migrate.py --sqlite /app/immigration.db

   Trong container, biến môi trường POSTGRES_* đã có sẵn nên không cần --pg-url.

3) Hoặc chạy từ host (nếu đã publish cổng 5432) — chỉ rõ chuỗi kết nối:
     python backend/scripts/migrate_sqlite_to_postgres.py \
         --sqlite backend/immigration.db \
         --pg-url postgresql+asyncpg://immigration:PASSWORD@localhost:5432/immigration_ai
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

# Cho phép import package `app` khi chạy script trực tiếp.
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy.ext.asyncio import create_async_engine  # noqa: E402

from app.config import settings  # noqa: E402
from app.database import Base  # noqa: E402
import app.models  # noqa: F401,E402  (đăng ký toàn bộ bảng vào Base.metadata)


def _resolve_pg_url(cli_url: str | None) -> str:
    if cli_url:
        return cli_url
    url = settings.resolved_database_url
    if not url.startswith("postgresql"):
        raise SystemExit(
            "Không tìm thấy chuỗi kết nối PostgreSQL. Truyền --pg-url hoặc đặt POSTGRES_* "
            "(đang resolve ra: %s)" % url
        )
    return url


def _coerce(value):
    """Đổi datetime naive thành UTC để asyncpg (TIMESTAMPTZ) chấp nhận."""
    if isinstance(value, datetime) and value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


async def migrate(sqlite_path: Path, pg_url: str) -> None:
    if not sqlite_path.exists():
        raise SystemExit(f"Không thấy file SQLite: {sqlite_path}")

    src_engine = create_async_engine(f"sqlite+aiosqlite:///{sqlite_path.as_posix()}")
    dst_engine = create_async_engine(pg_url, connect_args={"ssl": False})

    tables = list(Base.metadata.sorted_tables)  # đã sắp theo phụ thuộc khóa ngoại

    try:
        # 1) Tạo schema trên Postgres nếu chưa có.
        async with dst_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # 2) Xóa dữ liệu cũ ở đích (đảo thứ tự để khỏi vướng khóa ngoại).
        async with dst_engine.begin() as conn:
            for table in reversed(tables):
                await conn.execute(table.delete())

        # 3) Copy từng bảng theo thứ tự an toàn khóa ngoại.
        total = 0
        for table in tables:
            async with src_engine.connect() as src:
                rows = (await src.execute(table.select())).mappings().all()
            if not rows:
                print(f"  {table.name}: 0")
                continue
            payload = [{k: _coerce(v) for k, v in row.items()} for row in rows]
            async with dst_engine.begin() as conn:
                await conn.execute(table.insert(), payload)
            total += len(payload)
            print(f"  {table.name}: {len(payload)}")
        print(f"Xong. Đã copy {total} dòng sang PostgreSQL.")
    finally:
        await src_engine.dispose()
        await dst_engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Migrate dữ liệu SQLite -> PostgreSQL")
    parser.add_argument(
        "--sqlite",
        default=str(BACKEND_DIR / "immigration.db"),
        help="Đường dẫn file SQLite (mặc định: backend/immigration.db)",
    )
    parser.add_argument(
        "--pg-url",
        default=None,
        help="Chuỗi kết nối Postgres (postgresql+asyncpg://...). Bỏ trống = lấy từ POSTGRES_*",
    )
    args = parser.parse_args()
    asyncio.run(migrate(Path(args.sqlite), _resolve_pg_url(args.pg_url)))


if __name__ == "__main__":
    main()
