"""Filter danh sách hồ sơ theo năm (ranh giới năm chuẩn xác)."""

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.applicants import _apply_year_filter
from app.database import Base
from app.models.entities import Applicant, User, UserRole


async def _setup(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'flt.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def test_apply_year_filter(tmp_path):
    async def scenario():
        engine, Session = await _setup(tmp_path)
        uid = uuid.uuid4()
        async with Session() as db:
            db.add(User(id=uid, email="t@t.com", hashed_password="x", role=UserRole.user))
            db.add_all([
                Applicant(id=uuid.uuid4(), user_id=uid, display_name="A2025-DEC",
                          created_at=datetime(2025, 12, 31, 23, 0, tzinfo=timezone.utc)),
                Applicant(id=uuid.uuid4(), user_id=uid, display_name="A2026-JAN",
                          created_at=datetime(2026, 1, 1, 0, 30, tzinfo=timezone.utc)),
                Applicant(id=uuid.uuid4(), user_id=uid, display_name="A2026-JUN",
                          created_at=datetime(2026, 6, 15, tzinfo=timezone.utc)),
                Applicant(id=uuid.uuid4(), user_id=uid, display_name="A2027-JAN",
                          created_at=datetime(2027, 1, 1, 0, 0, tzinfo=timezone.utc)),
            ])
            await db.commit()

            q = _apply_year_filter(select(Applicant), 2026)
            names = sorted(a.display_name for a in (await db.execute(q)).scalars())
            assert names == ["A2026-JAN", "A2026-JUN"]

            # year=None → không lọc
            allq = _apply_year_filter(select(Applicant), None)
            assert len((await db.execute(allq)).scalars().all()) == 4
        await engine.dispose()

    asyncio.run(scenario())
