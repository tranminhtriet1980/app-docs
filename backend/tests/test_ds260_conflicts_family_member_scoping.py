"""sync_ds260_doc_conflicts KHÔNG được so sánh dữ liệu của 2 thành viên khác nhau trong cùng
một bộ hồ sơ gia đình với nhau.

Báo lỗi thực tế 2026-08-05: hồ sơ TRIEU THI DUYEN (chủ hồ sơ) + NGUYEN MINH PHUONG (con) —
conflict "DS-260 3 — ADDRESS · City" so application_form của TRIEU THI DUYEN
("01_7 JOB APPLICATION - TRIEU THI DUYEN.docx", City = LUANDA) với worksheet DS-260 của
NGUYEN MINH PHUONG ("03_6 DS260 - NGUYEN MINH PHUONG.pdf", City = YEN BAI) — 2 NGƯỜI KHÁC
NHAU, không phải cùng một bộ hồ sơ của một người. Đúng ra chỉ được so trong phạm vi tài liệu
của TỪNG NGƯỜI.
"""

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


def test_family_bundle_does_not_cross_compare_between_members(tmp_path):
    """TRIEU THI DUYEN (01, principal) và NGUYEN MINH PHUONG (03, child) — mỗi người có
    application_form + worksheet MÂU THUẪN NỘI BỘ (city khác nhau trong CHÍNH bộ hồ sơ của
    họ). Kỳ vọng: 2 conflict riêng biệt, mỗi cái chỉ chứa dữ liệu của đúng 1 người — KHÔNG có
    conflict nào trộn city của người này với người kia."""

    async def scenario():
        engine, Session = await _setup(tmp_path, "family_scope")
        async with Session() as session:
            user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@t.local", hashed_password="x")
            applicant = Applicant(
                id=uuid.uuid4(),
                user_id=user.id,
                display_name="TRIEU THI DUYEN",
                is_family_bundle=True,
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

            # TRIEU (01) — application_form vs worksheet mâu thuẫn NỘI BỘ (LUANDA vs HO CHI MINH)
            duyen_app_doc = _doc(applicant.id, "01_7 JOB APPLICATION - TRIEU THI DUYEN.docx")
            duyen_ws_doc = _doc(applicant.id, "01_6 DS260 - TRIEU THI DUYEN.pdf")
            duyen_app_rec = _rec(
                applicant.id, duyen_app_doc, "application_form",
                {"address_city": "LUANDA", "address_country": "ANGOLA"},
            )
            duyen_ws_rec = _rec(
                applicant.id, duyen_ws_doc, "ds260_customer_form",
                {"current_city": "HO CHI MINH", "current_country": "ANGOLA"},
                variant="exception",
            )

            # NGUYEN (03) — application_form vs worksheet mâu thuẫn NỘI BỘ (HANOI vs YEN BAI)
            phuong_app_doc = _doc(applicant.id, "03_7 JOB APPLICATION - NGUYEN MINH PHUONG.docx")
            phuong_ws_doc = _doc(applicant.id, "03_6 DS260 - NGUYEN MINH PHUONG.pdf")
            phuong_app_rec = _rec(
                applicant.id, phuong_app_doc, "application_form",
                {"address_city": "HANOI", "address_country": "VIETNAM"},
            )
            phuong_ws_rec = _rec(
                applicant.id, phuong_ws_doc, "ds260_customer_form",
                {"current_city": "YEN BAI", "current_country": "VIETNAM"},
                variant="exception",
            )

            session.add_all(
                [
                    duyen_app_doc, duyen_ws_doc, phuong_app_doc, phuong_ws_doc,
                    duyen_app_rec, duyen_ws_rec, phuong_app_rec, phuong_ws_rec,
                ]
            )
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

            city_conflicts = [c for c in conflicts if "current_city" in c.field_key]
            assert len(city_conflicts) == 2, (
                f"Kỳ vọng đúng 2 conflict city (1/người), thấy {len(city_conflicts)}: "
                f"{[c.field_key for c in city_conflicts]}"
            )

            # KHÔNG được có conflict nào trộn city của người này với người kia.
            for c in city_conflicts:
                pair = {c.value_a, c.value_b}
                assert pair in ({"LUANDA", "HO CHI MINH"}, {"HANOI", "YEN BAI"}), (
                    f"Conflict trộn dữ liệu 2 người khác nhau: {c.field_key} = "
                    f"{c.value_a!r} vs {c.value_b!r}"
                )
                # Đặc biệt: LUANDA (của TRIEU) không được ghép với YEN BAI (của NGUYEN) —
                # đúng bug thực tế trong báo cáo 2026-08-05.
                assert pair != {"LUANDA", "YEN BAI"}
                assert pair != {"HANOI", "HO CHI MINH"}

            # field_key phải mang hậu tố thành viên khác nhau (không ghi đè lẫn nhau).
            field_keys = {c.field_key for c in city_conflicts}
            assert len(field_keys) == 2, "2 conflict phải có field_key khác nhau (không đè nhau)"

        await engine.dispose()

    _run(scenario())


def test_single_applicant_conflict_field_key_unchanged(tmp_path):
    """Hồ sơ 1 người (không phải family bundle) — field_key giữ nguyên định dạng cũ, KHÔNG có
    hậu tố .memberNN — đảm bảo không phá dữ liệu Conflict đã có trong DB trước bản vá."""

    async def scenario():
        engine, Session = await _setup(tmp_path, "single_unchanged")
        async with Session() as session:
            user = User(id=uuid.uuid4(), email=f"{uuid.uuid4()}@t.local", hashed_password="x")
            applicant = Applicant(id=uuid.uuid4(), user_id=user.id, display_name="NGUYEN VAN A")
            session.add_all([user, applicant])
            await session.flush()

            app_doc = _doc(applicant.id, "Application form.docx")
            ws_doc = _doc(applicant.id, "DS260.pdf")
            app_rec = _rec(
                applicant.id, app_doc, "application_form", {"address_city": "DA NANG"}
            )
            ws_rec = _rec(
                applicant.id, ws_doc, "ds260_customer_form",
                {"current_city": "HA NOI"},
                variant="exception",
            )
            session.add_all([app_doc, ws_doc, app_rec, ws_rec])
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
            city_conflicts = [c for c in conflicts if "current_city" in c.field_key]
            assert len(city_conflicts) == 1
            assert city_conflicts[0].field_key == "ds260.document_vs_worksheet.current_city", (
                "Hồ sơ 1 người không được có hậu tố .memberNN trong field_key"
            )
        await engine.dispose()

    _run(scenario())
