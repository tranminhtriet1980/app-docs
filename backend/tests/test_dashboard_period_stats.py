"""Thống kê dashboard: số hồ sơ tuần/tháng/năm + theo người phụ trách."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.entities import Applicant, User, UserRole
from app.services.overview_stats import build_period_responsible_stats


async def _setup(tmp_path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{(tmp_path / 'stats.db').as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _appl(user_id, when):
    return Applicant(id=uuid.uuid4(), user_id=user_id, display_name="X", created_at=when)


def test_period_and_responsible_stats(tmp_path):
    async def scenario():
        engine, Session = await _setup(tmp_path)
        now = datetime.now(timezone.utc)
        year_start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        last_year = year_start - timedelta(days=10)
        u1, u2 = uuid.uuid4(), uuid.uuid4()
        async with Session() as db:
            db.add_all([
                User(id=u1, email="triet@t.com", hashed_password="x", role=UserRole.admin, full_name="Triet Tran"),
                User(id=u2, email="khanh@t.com", hashed_password="x", role=UserRole.user),
            ])
            db.add_all([
                _appl(u1, now), _appl(u1, now),   # 2 hồ sơ hôm nay (u1)
                _appl(u2, now),                   # 1 hồ sơ hôm nay (u2)
                _appl(u1, last_year),             # năm ngoái → ngoài "năm nay"
            ])
            await db.commit()

            # Scope toàn bộ (view quản lý)
            alls = await build_period_responsible_stats(db, user_id=None)
            assert alls["applicants_this_week"] == 3
            assert alls["applicants_this_month"] == 3
            assert alls["applicants_this_year"] == 3   # loại hồ sơ năm ngoái
            by = {r["name"]: r for r in alls["by_responsible"]}
            assert by["Triet Tran"]["week"] == 2 and by["Triet Tran"]["year"] == 2
            # u2 không có full_name → hiển thị theo email
            assert by["khanh@t.com"]["week"] == 1 and by["khanh@t.com"]["year"] == 1

            # Scope theo 1 người
            mine = await build_period_responsible_stats(db, user_id=u1)
            assert mine["applicants_this_year"] == 2
            assert len(mine["by_responsible"]) == 1
            assert mine["by_responsible"][0]["name"] == "Triet Tran"
        await engine.dispose()

    asyncio.run(scenario())
