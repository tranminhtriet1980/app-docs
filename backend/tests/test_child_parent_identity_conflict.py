"""build_child_parent_identity_conflict_rows — so sánh ngày sinh/quốc gia sinh cha-mẹ khai
trên worksheet CỦA CHÍNH NGƯỜI CON với hồ sơ thật của cha/mẹ đó (khi cha/mẹ CŨNG là case
member trong cùng bộ hồ sơ).

Báo lỗi thực tế 2026-08-05: NGUYEN MINH PHUONG (con, case member) — worksheet của chính
NGUYEN MINH PHUONG khai đầy đủ ngày sinh/nơi sinh cha mẹ, nhưng DS-260 form không hiển thị
(field trống) vì hệ thống chưa từng đọc tới worksheet của chính người con cho mục cha/mẹ, và
cũng chưa từng đối chiếu với hồ sơ thật của mẹ (TRIEU THI DUYEN, đương đơn chính)."""

import asyncio
import json
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.entities import (
    Applicant,
    ApplicantDocRecord,
    CaseMember,
    Conflict,
    ConflictStatus,
    Document,
    DocumentStatus,
    PersonRole,
    User,
)
from app.services.ds260_conflicts import sync_ds260_doc_conflicts


def _run(coro):
    return asyncio.run(coro)


async def _setup(tmp_path, name):
    db_file = tmp_path / f"{name}.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _doc(applicant_id, filename) -> Document:
    return Document(
        id=uuid.uuid4(),
        applicant_id=applicant_id,
        original_filename=filename,
        file_path=f"/tmp/{filename}",
        mime_type="application/pdf",
        file_size=1,
        status=DocumentStatus.extracted,
    )


def _rec(applicant_id, doc: Document, doc_type: str, data: dict, variant: str = "standard") -> ApplicantDocRecord:
    return ApplicantDocRecord(
        id=uuid.uuid4(),
        applicant_id=applicant_id,
        doc_type=doc_type,
        variant=variant,
        source_document_id=doc.id,
        form_data=json.dumps(data),
        raw_data=json.dumps(data),
    )


def test_child_worksheet_mother_dob_conflicts_with_mother_own_passport(tmp_path):
    """Con khai mẹ sinh ngày X trên worksheet của mình; mẹ (đương đơn chính) có hộ chiếu ghi
    ngày sinh Y khác — phải tạo conflict child_parent_identity."""

    async def scenario():
        engine, Session = await _setup(tmp_path, "child_parent_conflict")
        async with Session() as session:
            user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@t.local", hashed_password="x")
            applicant = Applicant(
                id=uuid.uuid4(), user_id=user.id, display_name="TRIEU THI DUYEN", is_family_bundle=True
            )
            session.add_all([user, applicant])
            await session.flush()

            principal = CaseMember(
                id=uuid.uuid4(),
                applicant_id=applicant.id,
                role=PersonRole.principal.value,
                display_name="TRIEU THI DUYEN",
                sort_order=0,
            )
            child = CaseMember(
                id=uuid.uuid4(),
                applicant_id=applicant.id,
                role=PersonRole.child.value,
                display_name="NGUYEN MINH PHUONG",
                sort_order=1,
            )
            session.add_all([principal, child])
            await session.flush()

            # Mẹ (TRIEU THI DUYEN) — hộ chiếu thật của chính mình.
            mother_pp_doc = _doc(applicant.id, "01_2 PASSPORT - TRIEU THI DUYEN.pdf")
            mother_pp_rec = _rec(
                applicant.id, mother_pp_doc, "passport",
                {"full_name": "TRIEU THI DUYEN", "date_of_birth": "1977-08-26"},
            )
            # Con (NGUYEN MINH PHUONG) — worksheet của chính mình khai SAI ngày sinh mẹ.
            child_ws_doc = _doc(applicant.id, "03_6 DS260 - NGUYEN MINH PHUONG.pdf")
            child_ws_rec = _rec(
                applicant.id, child_ws_doc, "ds260_customer_form",
                {
                    "applicant_name": "NGUYEN MINH PHUONG",
                    "mother_surname": "TRIEU",
                    "mother_given_names": "THI DUYEN",
                    "mother_date_of_birth": "1990-01-01",  # SAI so với hộ chiếu thật (1977-08-26)
                },
                variant="exception",
            )
            session.add_all([mother_pp_doc, mother_pp_rec, child_ws_doc, child_ws_rec])
            await session.commit()

            await sync_ds260_doc_conflicts(session, applicant.id)
            await session.commit()

            conflicts = (
                await session.execute(
                    select(Conflict).where(
                        Conflict.applicant_id == applicant.id,
                        Conflict.status == ConflictStatus.open,
                    )
                )
            ).scalars().all()
            cp_conflicts = [c for c in conflicts if "child_parent_identity" in c.field_key]
            assert len(cp_conflicts) == 1, f"Kỳ vọng 1 conflict, thấy: {[c.field_key for c in conflicts]}"
            c = cp_conflicts[0]
            assert "mother" in c.field_key
            assert "date_of_birth" in c.field_key
            values = {c.value_a, c.value_b}
            assert values == {"1977-08-26", "1990-01-01"}
        await engine.dispose()

    _run(scenario())


def test_child_worksheet_mother_dob_matches_no_conflict(tmp_path):
    """Ngày sinh khớp giữa worksheet con và hộ chiếu mẹ — không tạo conflict thừa."""

    async def scenario():
        engine, Session = await _setup(tmp_path, "child_parent_match")
        async with Session() as session:
            user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@t.local", hashed_password="x")
            applicant = Applicant(
                id=uuid.uuid4(), user_id=user.id, display_name="TRIEU THI DUYEN", is_family_bundle=True
            )
            session.add_all([user, applicant])
            await session.flush()

            principal = CaseMember(
                id=uuid.uuid4(),
                applicant_id=applicant.id,
                role=PersonRole.principal.value,
                display_name="TRIEU THI DUYEN",
                sort_order=0,
            )
            child = CaseMember(
                id=uuid.uuid4(),
                applicant_id=applicant.id,
                role=PersonRole.child.value,
                display_name="NGUYEN MINH PHUONG",
                sort_order=1,
            )
            session.add_all([principal, child])
            await session.flush()

            mother_pp_doc = _doc(applicant.id, "01_2 PASSPORT - TRIEU THI DUYEN.pdf")
            mother_pp_rec = _rec(
                applicant.id, mother_pp_doc, "passport",
                {"full_name": "TRIEU THI DUYEN", "date_of_birth": "1977-08-26"},
            )
            child_ws_doc = _doc(applicant.id, "03_6 DS260 - NGUYEN MINH PHUONG.pdf")
            child_ws_rec = _rec(
                applicant.id, child_ws_doc, "ds260_customer_form",
                {
                    "applicant_name": "NGUYEN MINH PHUONG",
                    "mother_surname": "TRIEU",
                    "mother_given_names": "THI DUYEN",
                    "mother_date_of_birth": "1977-08-26",
                },
                variant="exception",
            )
            session.add_all([mother_pp_doc, mother_pp_rec, child_ws_doc, child_ws_rec])
            await session.commit()

            await sync_ds260_doc_conflicts(session, applicant.id)
            await session.commit()

            conflicts = (
                await session.execute(
                    select(Conflict).where(
                        Conflict.applicant_id == applicant.id,
                        Conflict.status == ConflictStatus.open,
                    )
                )
            ).scalars().all()
            cp_conflicts = [c for c in conflicts if "child_parent_identity" in c.field_key]
            assert cp_conflicts == []
        await engine.dispose()

    _run(scenario())


def test_no_conflict_when_parent_not_a_case_member(tmp_path):
    """Cha/mẹ khai trên worksheet con KHÔNG phải case member nào trong hồ sơ (không có hồ sơ
    thật để đối chiếu) — không tạo conflict (đúng yêu cầu: "thông tin nào không có thì thôi")."""

    async def scenario():
        engine, Session = await _setup(tmp_path, "no_matching_parent")
        async with Session() as session:
            user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@t.local", hashed_password="x")
            applicant = Applicant(
                id=uuid.uuid4(), user_id=user.id, display_name="TRIEU THI DUYEN", is_family_bundle=True
            )
            session.add_all([user, applicant])
            await session.flush()

            principal = CaseMember(
                id=uuid.uuid4(),
                applicant_id=applicant.id,
                role=PersonRole.principal.value,
                display_name="TRIEU THI DUYEN",
                sort_order=0,
            )
            child = CaseMember(
                id=uuid.uuid4(),
                applicant_id=applicant.id,
                role=PersonRole.child.value,
                display_name="NGUYEN MINH PHUONG",
                sort_order=1,
            )
            session.add_all([principal, child])
            await session.flush()

            child_ws_doc = _doc(applicant.id, "03_6 DS260 - NGUYEN MINH PHUONG.pdf")
            child_ws_rec = _rec(
                applicant.id, child_ws_doc, "ds260_customer_form",
                {
                    "applicant_name": "NGUYEN MINH PHUONG",
                    "father_surname": "NGUYEN",
                    "father_given_names": "VAN HUNG",
                    "father_date_of_birth": "1978-02-08",
                },
                variant="exception",
            )
            session.add_all([child_ws_doc, child_ws_rec])
            await session.commit()

            await sync_ds260_doc_conflicts(session, applicant.id)
            await session.commit()

            conflicts = (
                await session.execute(
                    select(Conflict).where(
                        Conflict.applicant_id == applicant.id,
                        Conflict.status == ConflictStatus.open,
                    )
                )
            ).scalars().all()
            cp_conflicts = [c for c in conflicts if "child_parent_identity" in c.field_key]
            assert cp_conflicts == [], "Cha không phải case member — không có gì để đối chiếu"
        await engine.dispose()

    _run(scenario())
