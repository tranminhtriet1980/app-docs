"""identity_outlier phải vote RIÊNG cho từng người trong hồ sơ gia đình.

Bug thực tế 2026-08-04: hồ sơ gia đình gộp chung passport của mẹ (TRIEU THI DUYEN) với
passport/lý lịch tư pháp của con (NGUYEN MINH PHUONG) vào MỘT vòng vote ngày sinh — báo
"khác biệt" dù đó là hai người khác nhau, không phải OCR sai.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.entities import (
    Applicant,
    CaseMember,
    Document,
    DocumentStatus,
    ExtractedField,
    PersonRole,
    User,
)
from app.services.identity_conflicts import (
    _group_documents_by_case_member,
    build_identity_outlier_conflict_rows,
    build_identity_outlier_conflict_rows_from_documents,
)


def _member(applicant_id, role, name) -> CaseMember:
    return CaseMember(id=uuid.uuid4(), applicant_id=applicant_id, role=role, display_name=name, sort_order=0)


def _doc(filename: str, document_type: str) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        original_filename=filename,
        registry_doc_type=document_type,
        document_type=document_type,
        uploaded_at=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )


def test_group_by_case_member_splits_docs_of_different_people():
    applicant_id = uuid.uuid4()
    mother = _member(applicant_id, PersonRole.principal.value, "TRIEU THI DUYEN")
    child = _member(applicant_id, PersonRole.child.value, "NGUYEN MINH PHUONG")

    mother_passport = _doc("01_2 PASSPORT - TRIEU THI DUYEN.pdf", "passport")
    child_passport = _doc("03_2 PASSPORT - NGUYEN MINH PHUONG.pdf", "passport")
    child_judicial = _doc("03_4 JUDICIAL CERTIFICATE - NGUYEN MINH PHUONG.pdf", "judicial_certificate")

    groups = _group_documents_by_case_member(
        [mother_passport, child_passport, child_judicial],
        applicant=None,
        members=[mother, child],
    )
    groups_by_ids = [{d.id for d in g} for g in groups]
    assert {mother_passport.id} in groups_by_ids
    assert {child_passport.id, child_judicial.id} in groups_by_ids


def test_group_by_case_member_single_person_stays_one_group():
    """Hồ sơ đơn (không khai báo case member) — vẫn 1 nhóm như hành vi cũ."""
    applicant = Applicant(id=uuid.uuid4(), user_id=uuid.uuid4(), display_name="NGUYEN VAN A")
    docs = [
        _doc("01_2 PASSPORT.pdf", "passport"),
        _doc("01_1 GKS.pdf", "birth_certificate"),
    ]
    groups = _group_documents_by_case_member(docs, applicant=applicant, members=[])
    assert len(groups) == 1
    assert {d.id for d in groups[0]} == {d.id for d in docs}


def test_unassignable_document_excluded_not_mixed():
    """Không xác định được thuộc về ai — loại khỏi vote, không đoán mò gộp vào người khác."""
    applicant_id = uuid.uuid4()
    mother = _member(applicant_id, PersonRole.principal.value, "TRIEU THI DUYEN")
    child = _member(applicant_id, PersonRole.child.value, "NGUYEN MINH PHUONG")
    mystery_doc = _doc("random_scan.pdf", "other")

    groups = _group_documents_by_case_member([mystery_doc], applicant=None, members=[mother, child])
    assert groups == []


def _run(coro):
    return asyncio.run(coro)


def test_build_identity_outlier_conflict_rows_does_not_cross_family_members(tmp_path):
    """End-to-end: trước fix, 2 passport khác ngày sinh của 2 người khác nhau trong CÙNG hồ sơ
    gia đình sẽ bị coi là 'tài liệu lệch' của nhau. Sau fix: mỗi người vote riêng, không đủ
    MIN_TOTAL_VOTES=3 trong nhóm 1-2 tài liệu/người nên không tạo cảnh báo sai."""

    async def scenario():
        db_file = tmp_path / "identity.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{db_file.as_posix()}")
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        Session = async_sessionmaker(engine, expire_on_commit=False)

        async with Session() as session:
            user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@t.local", hashed_password="x")
            applicant = Applicant(id=uuid.uuid4(), user_id=user.id, display_name="TRIEU THI DUYEN", is_family_bundle=True)
            session.add_all([user, applicant])
            await session.flush()

            mother = _member(applicant.id, PersonRole.principal.value, "TRIEU THI DUYEN")
            child = _member(applicant.id, PersonRole.child.value, "NGUYEN MINH PHUONG")
            session.add_all([mother, child])

            def _add_doc(filename, doc_type, dob):
                doc = Document(
                    id=uuid.uuid4(),
                    applicant_id=applicant.id,
                    original_filename=filename,
                    file_path=f"uploads/x/{filename}",
                    mime_type="application/pdf",
                    file_size=100,
                    document_type=doc_type,
                    registry_doc_type=doc_type,
                    status=DocumentStatus.extracted,
                )
                session.add(doc)
                session.add(
                    ExtractedField(
                        id=uuid.uuid4(), document_id=doc.id, field_key="date_of_birth", field_value=dob
                    )
                )
                return doc

            _add_doc("01_2 PASSPORT - TRIEU THI DUYEN.pdf", "passport", "1977-08-26")
            _add_doc("03_2 PASSPORT - NGUYEN MINH PHUONG.pdf", "passport", "2007-01-29")
            _add_doc("03_4 JUDICIAL CERTIFICATE - NGUYEN MINH PHUONG.pdf", "judicial_certificate", "2007-01-29")
            await session.flush()
            await session.commit()

            rows = await build_identity_outlier_conflict_rows(session, applicant.id, {})
            assert rows == []
        await engine.dispose()

    _run(scenario())
