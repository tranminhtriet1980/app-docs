"""Chặn tạo hồ sơ trùng: cùng người phụ trách + cùng năm + cùng tên."""

import asyncio
import uuid
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.applicants import _find_duplicate_applicant, _normalize_applicant_name
from app.database import Base
from app.models.entities import Applicant, User, UserRole


def test_normalize_applicant_name():
    assert _normalize_applicant_name("  nguyen   van  a ") == "NGUYEN VAN A"
    assert _normalize_applicant_name("Nguyen Van A") == _normalize_applicant_name("NGUYEN  VAN A")


def _run(coro):
    return asyncio.run(coro)


async def _setup(tmp_path):
    db_file = tmp_path / "dup.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _applicant(user_id, name, year, deleted=False):
    return Applicant(
        id=uuid.uuid4(),
        user_id=user_id,
        display_name=name,
        created_at=datetime(year, 6, 1, tzinfo=timezone.utc),
        deleted_at=datetime(year, 7, 1, tzinfo=timezone.utc) if deleted else None,
    )


def test_find_duplicate_applicant_rules(tmp_path):
    async def scenario():
        engine, Session = await _setup(tmp_path)
        this_year = datetime.now(timezone.utc).year
        u1, u2 = uuid.uuid4(), uuid.uuid4()
        async with Session() as db:
            db.add_all([
                User(id=u1, email="a@t.com", hashed_password="x", role=UserRole.user),
                User(id=u2, email="b@t.com", hashed_password="x", role=UserRole.user),
            ])
            db.add_all([
                _applicant(u1, "NGUYEN VAN A", this_year),
                _applicant(u1, "TRAN THI B", this_year - 1),          # khác năm
                _applicant(u1, "LE VAN C", this_year, deleted=True),  # đã xóa
                _applicant(u2, "PHAM VAN D", this_year),
            ])
            await db.commit()

            # 1) Trùng tên + năm + người tạo (khác hoa/thường, dư khoảng trắng) → chặn
            dup = await _find_duplicate_applicant(
                db, user_id=u1, display_name="  nguyen  van a ", year=this_year
            )
            assert dup is not None and dup.display_name == "NGUYEN VAN A"

            # 2) Cùng tên nhưng KHÁC năm → cho tạo
            assert await _find_duplicate_applicant(
                db, user_id=u1, display_name="TRAN THI B", year=this_year
            ) is None

            # 3) Hồ sơ đã xóa → không tính trùng
            assert await _find_duplicate_applicant(
                db, user_id=u1, display_name="LE VAN C", year=this_year
            ) is None

            # 4) Cùng tên + năm nhưng KHÁC người phụ trách → cho tạo
            assert await _find_duplicate_applicant(
                db, user_id=u1, display_name="PHAM VAN D", year=this_year
            ) is None

            # 5) Tên hoàn toàn mới → cho tạo
            assert await _find_duplicate_applicant(
                db, user_id=u1, display_name="HO BAO CHAU", year=this_year
            ) is None
        await engine.dispose()

    _run(scenario())
