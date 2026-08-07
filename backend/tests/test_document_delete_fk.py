"""Xoá document không được vướng khoá ngoại từ api_usage_logs / profile_fields.

Sự cố prod 30/07/2026: nút xoá tài liệu ném
`ForeignKeyViolationError ... api_usage_logs_document_id_fkey`.
Bug tồn tại từ lúc chuyển SQLite→Postgres và KHÔNG lộ ra ở local, vì SQLite mặc định
không ép khoá ngoại. Test này bật `PRAGMA foreign_keys=ON` để SQLite hành xử như
Postgres — bỏ `_detach_document_references` đi là test đỏ ngay.
"""

import asyncio
import uuid

import pytest
from sqlalchemy import event, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.api.documents import _detach_document_references
from app.database import Base
from app.models.entities import (
    ApiUsageLog,
    Applicant,
    Conflict,
    ConflictStatus,
    Document,
    ProfileField,
    User,
)


def _run(coro):
    return asyncio.run(coro)


async def _setup(tmp_path, name):
    db_file = tmp_path / f"{name}.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")

    # Mặc định SQLite bỏ qua khoá ngoại; bật lên để tái hiện hành vi Postgres.
    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn, _record):  # pragma: no cover - hook của driver
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed(session):
    """Một document đã chạy OCR: có log token và có profile field lấy từ nó."""
    user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@t.local", hashed_password="x")
    applicant = Applicant(id=uuid.uuid4(), user_id=user.id, display_name="NGUYEN VAN A")
    document = Document(
        id=uuid.uuid4(),
        applicant_id=applicant.id,
        original_filename="01_1 GKS.pdf",
        file_path="uploads/x/01_1 GKS.pdf",
        mime_type="application/pdf",
        file_size=1234,
    )
    usage = ApiUsageLog(
        id=uuid.uuid4(),
        document_id=document.id,
        applicant_id=applicant.id,
        operation="document.extract",
        model="gpt-4.1",
        total_tokens=22000,
    )
    field = ProfileField(
        id=uuid.uuid4(),
        applicant_id=applicant.id,
        field_key="applicant_full_name",
        field_value="NGUYEN VAN A",
        source_document_id=document.id,
    )
    conflict = Conflict(
        id=uuid.uuid4(),
        applicant_id=applicant.id,
        field_key="ds260.identity_outlier.identity.full_name.x",
        value_a="NGUYEN VAN A",
        document_a_id=document.id,
        value_b="NGUYEN VAN B",
        status=ConflictStatus.open,
    )
    # Flush theo tầng: FK được ép nên hàng cha phải nằm trong DB trước hàng con.
    session.add_all([user, applicant])
    await session.flush()
    session.add(document)
    await session.flush()
    session.add_all([usage, field, conflict])
    await session.commit()
    return document, usage, field, conflict


def test_delete_document_detaches_references(tmp_path):
    """Xoá được, và log token vẫn còn — chỉ mất liên kết tới document."""

    async def scenario():
        engine, Session = await _setup(tmp_path, "detach")
        async with Session() as session:
            document, usage, field, conflict = await _seed(session)

            await _detach_document_references(session, document.id)
            await session.delete(document)
            await session.flush()
            await session.commit()

            assert (
                await session.scalar(select(Document).where(Document.id == document.id))
            ) is None

            # Số liệu token là dữ liệu đối soát chi phí — phải giữ, chỉ gỡ liên kết.
            kept_usage = await session.get(ApiUsageLog, usage.id)
            assert kept_usage is not None
            assert kept_usage.document_id is None
            assert kept_usage.total_tokens == 22000

            # Giá trị hồ sơ vẫn đúng, chỉ mất dấu vết xuất xứ.
            kept_field = await session.get(ProfileField, field.id)
            assert kept_field is not None
            assert kept_field.source_document_id is None
            assert kept_field.field_value == "NGUYEN VAN A"

            # Conflict (vd. identity_outlier) vẫn còn, chỉ mất liên kết document nguồn.
            kept_conflict = await session.get(Conflict, conflict.id)
            assert kept_conflict is not None
            assert kept_conflict.document_a_id is None
            assert kept_conflict.value_a == "NGUYEN VAN A"
        await engine.dispose()

    _run(scenario())


def test_delete_without_detach_violates_fk(tmp_path):
    """Chốt chặn: bỏ bước gỡ liên kết thì DB có ép khoá ngoại sẽ nổ.

    Nếu test này ngừng đỏ nghĩa là FK không còn được ép và test trên mất giá trị.
    """

    async def scenario():
        engine, Session = await _setup(tmp_path, "violate")
        async with Session() as session:
            document, _usage, _field, _conflict = await _seed(session)

            await session.delete(document)
            with pytest.raises(IntegrityError):
                await session.flush()
            await session.rollback()
        await engine.dispose()

    _run(scenario())
