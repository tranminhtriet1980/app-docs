import asyncio
import json
import uuid
import pytest
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
)
from app.services.ds260_conflicts import sync_ds260_doc_conflicts
from app.services.ds260_mapping import resolve_ds260_form


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
        raw_data=json.dumps(data),
        form_data=json.dumps(data),
    )


def test_child_address_sync_when_lives_with_yes(tmp_path):
    async def _test():
        from app.models.entities import User
        engine, Session = await _setup(tmp_path, "sync_yes")
        app_id = uuid.uuid4()
        user_id = uuid.uuid4()
        m_parent_id = uuid.uuid4()
        m_child_id = uuid.uuid4()

        user = User(id=user_id, email="test1@test.com", hashed_password="pw")
        applicant = Applicant(id=app_id, user_id=user_id, display_name="PARENT TEST", is_family_bundle=True)
        m_parent = CaseMember(id=m_parent_id, applicant_id=app_id, role=PersonRole.principal, display_name="PARENT TEST")
        m_child = CaseMember(id=m_child_id, applicant_id=app_id, role=PersonRole.child, display_name="CHILD TEST")

        d1 = _doc(app_id, "01_6 DS260 - PARENT.pdf")
        r1 = _rec(
            app_id,
            d1,
            "ds260_customer_form",
            {
                "applicant_name": "PARENT TEST",
                "current_address": "123 Le Loi Street, Ward 1, District 1",
                "current_city": "Ho Chi Minh",
                "current_state": "N/A",
                "postal_code": "700000",
                "current_country": "Vietnam",
                "children_used": "Yes",
                "children_count": "1",
                "child_1_full_name": "CHILD TEST",
                "child_1_lives_with": "Yes",
            },
            variant="exception",
        )

        d2 = _doc(app_id, "02_6 DS260 - CHILD.pdf")
        r2 = _rec(
            app_id,
            d2,
            "ds260_customer_form",
            {
                "applicant_name": "CHILD TEST",
                "current_address": "999 Old Address, Hanoi",
            },
            variant="exception",
        )

        async with Session() as db:
            db.add_all([user, applicant, m_parent, m_child, d1, d2, r1, r2])
            await db.commit()

            form = await resolve_ds260_form(db, app_id, member_id=str(m_child_id))
            sec_addr = next(s for s in form["sections"] if s["id"] == "section_address")
            field_map = {f["key"]: f["value"] for f in sec_addr["fields"]}
            assert field_map["current_address"] == "123 Le Loi Street, Ward 1, District 1"
            assert field_map["current_city"] == "Ho Chi Minh"

    _run(_test())


def test_child_address_conflict_when_lives_with_no(tmp_path):
    async def _test():
        from app.models.entities import User
        engine, Session = await _setup(tmp_path, "sync_no")
        app_id = uuid.uuid4()
        user_id = uuid.uuid4()
        m_parent_id = uuid.uuid4()
        m_child_id = uuid.uuid4()

        user = User(id=user_id, email="test2@test.com", hashed_password="pw")
        applicant = Applicant(id=app_id, user_id=user_id, display_name="PARENT TEST", is_family_bundle=True)
        m_parent = CaseMember(id=m_parent_id, applicant_id=app_id, role=PersonRole.principal, display_name="PARENT TEST")
        m_child = CaseMember(id=m_child_id, applicant_id=app_id, role=PersonRole.child, display_name="CHILD TEST")

        d1 = _doc(app_id, "01_6 DS260 - PARENT.pdf")
        r1 = _rec(
            app_id,
            d1,
            "ds260_customer_form",
            {
                "applicant_name": "PARENT TEST",
                "current_address": "123 Le Loi Street, Ward 1, District 1",
                "children_used": "Yes",
                "children_count": "1",
                "child_1_full_name": "CHILD TEST",
                "child_1_lives_with": "No",
                "child_1_current_address": "456 Tran Hung Dao, Da Nang",
            },
            variant="exception",
        )

        d2 = _doc(app_id, "02_6 DS260 - CHILD.pdf")
        r2 = _rec(
            app_id,
            d2,
            "ds260_customer_form",
            {
                "applicant_name": "CHILD TEST",
                "current_address": "789 Nguyen Hue, Hue",
            },
            variant="exception",
        )

        async with Session() as db:
            db.add_all([user, applicant, m_parent, m_child, d1, d2, r1, r2])
            await db.commit()

            # 1. Child's form does not sync parent's address, keeps own address
            form = await resolve_ds260_form(db, app_id, member_id=str(m_child_id))
            sec_addr = next(s for s in form["sections"] if s["id"] == "section_address")
            field_map = {f["key"]: f["value"] for f in sec_addr["fields"]}
            assert field_map["current_address"] == "789 Nguyen Hue, Hue"

            # 2. Conflict is created between parent's declared address for child vs child's own declaration
            await sync_ds260_doc_conflicts(db, app_id)
            c_res = await db.execute(select(Conflict).where(Conflict.applicant_id == app_id))
            conflicts = c_res.scalars().all()
            target_c = next((c for c in conflicts if "child_address_not_with_parent" in c.field_key), None)
            assert target_c is not None
            assert target_c.value_a == "456 Tran Hung Dao, Da Nang"
            assert target_c.value_b == "789 Nguyen Hue, Hue"

    _run(_test())
