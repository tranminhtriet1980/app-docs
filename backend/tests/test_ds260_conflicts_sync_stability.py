"""sync_ds260_doc_conflicts phải upsert theo field_key, không xoá-hết-rồi-tạo-lại.

Sự cố báo lỗi: bấm resolve một conflict đang hiển thị trên Review → 404 "Conflict not
found". Nguyên nhân: mỗi lần sync (chạy lại sau MỖI file OCR xong) xoá toàn bộ Conflict
đang mở rồi tạo lại — id mới random mỗi lần, nên id đã fetch về UI thành "mồ côi" nếu có
một lần sync khác chạy chen giữa lúc người dùng bấm resolve. Test này khoá lại: sync 2 lần
liên tiếp với cùng dữ liệu phải trả về CÙNG MỘT conflict id.
"""

import asyncio
import json
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.entities import ApplicantDocRecord, Applicant, Conflict, ConflictStatus, User
from app.services.ds260_conflicts import sync_ds260_doc_conflicts


def _run(coro):
    return asyncio.run(coro)


async def _setup(tmp_path, name):
    db_file = tmp_path / f"{name}.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_worksheet_mismatch(session, applicant_id):
    application = ApplicantDocRecord(
        id=uuid.uuid4(),
        applicant_id=applicant_id,
        doc_type="application_form",
        variant="standard",
        source_document_id=uuid.uuid4(),
        form_data=json.dumps({"job_title": "Manager"}),
        raw_data=json.dumps({"job_title": "Manager"}),
    )
    ds260 = ApplicantDocRecord(
        id=uuid.uuid4(),
        applicant_id=applicant_id,
        doc_type="ds260_customer_form",
        variant="exception",
        source_document_id=uuid.uuid4(),
        form_data=json.dumps({"job_title": "Staff"}),
        raw_data=json.dumps({"job_title": "Staff"}),
    )
    session.add_all([application, ds260])
    await session.commit()


def test_sync_twice_keeps_same_conflict_id(tmp_path):
    async def scenario():
        engine, Session = await _setup(tmp_path, "stable")
        async with Session() as session:
            user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@t.local", hashed_password="x")
            applicant = Applicant(id=uuid.uuid4(), user_id=user.id, display_name="NGUYEN VAN A")
            session.add_all([user, applicant])
            await session.flush()
            await _seed_worksheet_mismatch(session, applicant.id)

            await sync_ds260_doc_conflicts(session, applicant.id)
            await session.commit()
            from sqlalchemy import select

            first = (
                await session.execute(
                    select(Conflict).where(
                        Conflict.applicant_id == applicant.id,
                        Conflict.status == ConflictStatus.open,
                    )
                )
            ).scalars().all()
            assert len(first) == 1
            first_id = first[0].id

            # Chạy sync lần 2 — mô phỏng finalize_applicant_after_ocr chạy lại sau khi
            # một file KHÁC xử lý xong, dữ liệu conflict không đổi.
            await sync_ds260_doc_conflicts(session, applicant.id)
            await session.commit()

            second = (
                await session.execute(
                    select(Conflict).where(
                        Conflict.applicant_id == applicant.id,
                        Conflict.status == ConflictStatus.open,
                    )
                )
            ).scalars().all()
            assert len(second) == 1
            assert second[0].id == first_id, "conflict id phải giữ nguyên giữa 2 lần sync"
        await engine.dispose()

    _run(scenario())


async def _seed_address_from_date_mismatch(session, applicant_id):
    """Same current_address on both sides (golden-source match), but the worksheet's
    address_from_date is after the Application form's date_signed — WP4 plausibility rule."""
    application = ApplicantDocRecord(
        id=uuid.uuid4(),
        applicant_id=applicant_id,
        doc_type="application_form",
        variant="standard",
        source_document_id=uuid.uuid4(),
        form_data=json.dumps({"current_address": "123 LE LOI", "date_signed": "01/06/2020"}),
        raw_data=json.dumps({"current_address": "123 LE LOI", "date_signed": "01/06/2020"}),
    )
    ds260 = ApplicantDocRecord(
        id=uuid.uuid4(),
        applicant_id=applicant_id,
        doc_type="ds260_customer_form",
        variant="exception",
        source_document_id=uuid.uuid4(),
        form_data=json.dumps({"current_address": "123 LE LOI", "address_from_date": "01/2021"}),
        raw_data=json.dumps({"current_address": "123 LE LOI", "address_from_date": "01/2021"}),
    )
    session.add_all([application, ds260])
    await session.commit()


def test_sync_twice_keeps_same_conflict_id_for_address_from_date(tmp_path):
    async def scenario():
        engine, Session = await _setup(tmp_path, "stable_address_from_date")
        async with Session() as session:
            user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@t.local", hashed_password="x")
            applicant = Applicant(id=uuid.uuid4(), user_id=user.id, display_name="NGUYEN VAN A")
            session.add_all([user, applicant])
            await session.flush()
            await _seed_address_from_date_mismatch(session, applicant.id)

            await sync_ds260_doc_conflicts(session, applicant.id)
            await session.commit()
            from sqlalchemy import select

            first = (
                await session.execute(
                    select(Conflict).where(
                        Conflict.applicant_id == applicant.id,
                        Conflict.field_key == "ds260.document_vs_worksheet.address_from_date",
                        Conflict.status == ConflictStatus.open,
                    )
                )
            ).scalars().all()
            assert len(first) == 1
            first_id = first[0].id

            await sync_ds260_doc_conflicts(session, applicant.id)
            await session.commit()

            second = (
                await session.execute(
                    select(Conflict).where(
                        Conflict.applicant_id == applicant.id,
                        Conflict.field_key == "ds260.document_vs_worksheet.address_from_date",
                        Conflict.status == ConflictStatus.open,
                    )
                )
            ).scalars().all()
            assert len(second) == 1
            assert second[0].id == first_id, "conflict id phải giữ nguyên giữa 2 lần sync"
        await engine.dispose()

    _run(scenario())


def test_sync_removes_conflict_once_values_match(tmp_path):
    async def scenario():
        engine, Session = await _setup(tmp_path, "resolved_away")
        async with Session() as session:
            from sqlalchemy import select

            user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@t.local", hashed_password="x")
            applicant = Applicant(id=uuid.uuid4(), user_id=user.id, display_name="NGUYEN VAN A")
            session.add_all([user, applicant])
            await session.flush()
            await _seed_worksheet_mismatch(session, applicant.id)

            await sync_ds260_doc_conflicts(session, applicant.id)
            await session.commit()

            # Sửa lại record cho khớp nhau — không còn mâu thuẫn.
            records = (
                await session.execute(
                    select(ApplicantDocRecord).where(ApplicantDocRecord.applicant_id == applicant.id)
                )
            ).scalars().all()
            for r in records:
                r.form_data = json.dumps({"job_title": "Manager"})
                r.raw_data = json.dumps({"job_title": "Manager"})
            await session.commit()

            await sync_ds260_doc_conflicts(session, applicant.id)
            await session.commit()

            open_conflicts = (
                await session.execute(
                    select(Conflict).where(
                        Conflict.applicant_id == applicant.id,
                        Conflict.status == ConflictStatus.open,
                    )
                )
            ).scalars().all()
            assert open_conflicts == []
        await engine.dispose()

    _run(scenario())
