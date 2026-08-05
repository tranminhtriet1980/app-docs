"""Bộ hồ sơ gia đình: khai báo tên con TRƯỚC (tạo CaseMember), upload file SAU — file phải
được gán ĐÚNG vào thành viên con đã khai báo sẵn, KHÔNG được tạo trùng/không xác định được
người khi tên đã có trong hệ thống. Chỉ khi tên trên tài liệu KHÔNG khớp ai đã khai báo thì
mới để "chưa xác định" (không đoán bừa gán cho người khác — vẫn không tự tạo thành viên mới,
CaseMember chỉ được tạo qua hành động rõ ràng của người dùng, xem create_case_members/
append_case_members trong family_case.py)."""

import asyncio
import json
import uuid

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.entities import (
    Applicant,
    ApplicantDocRecord,
    CaseMember,
    Document,
    DocumentStatus,
    PersonRole,
    User,
)
from app.services.family_case import (
    group_doc_records_by_member,
    resolve_doc_records_member_numbers,
)


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


async def _seed_family(session, *, children_names: list[str]):
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
    session.add(principal)
    children = []
    for i, name in enumerate(children_names):
        c = CaseMember(
            id=uuid.uuid4(),
            applicant_id=applicant.id,
            role=PersonRole.child.value,
            display_name=name,
            sort_order=1 + i,
        )
        session.add(c)
        children.append(c)
    await session.flush()
    return applicant, principal, children


def test_predeclared_child_birth_cert_no_prefix_matches_by_name(tmp_path):
    """Khai báo con "NGUYEN MINH PHUONG" trước (CaseMember). Sau đó upload giấy khai sinh con
    KHÔNG có tiền tố số thứ tự file — chỉ có tên trong nội dung OCR. Phải khớp đúng vào thành
    viên đã khai báo (member_number = '03'), không phải None/không xác định."""

    async def scenario():
        engine, Session = await _setup(tmp_path, "predeclared_bc")
        async with Session() as session:
            applicant, principal, children = await _seed_family(
                session, children_names=["NGUYEN MINH PHUONG"]
            )
            phuong = children[0]

            # Tên file KHÔNG có tiền tố "03_" — chỉ dựa vào tên OCR để khớp.
            bc_doc = _doc(applicant.id, "Birth certificate child.pdf")
            bc_rec = _rec(
                applicant.id, bc_doc, "birth_certificate_child",
                {"child_full_name": "Nguyễn Minh Phương"},  # OCR có dấu, khai báo không dấu
            )
            session.add_all([bc_doc, bc_rec])
            await session.commit()

            numbers = await resolve_doc_records_member_numbers(session, applicant.id, [bc_rec])
            assert numbers.get(id(bc_rec)) == "03", (
                "Giấy khai sinh con phải khớp đúng thành viên đã khai báo trước (member 03), "
                f"nhưng ra: {numbers}"
            )
        await engine.dispose()

    _run(scenario())


def test_predeclared_child_application_form_matches_by_filename_prefix(tmp_path):
    """application_form không có field tên để OCR-match — phải dựa vào tiền tố số file
    ("03_") để khớp đúng thành viên con đã khai báo trước, KHÔNG bị bỏ sót/gán nhầm."""

    async def scenario():
        engine, Session = await _setup(tmp_path, "predeclared_app")
        async with Session() as session:
            applicant, principal, children = await _seed_family(
                session, children_names=["NGUYEN MINH PHUONG"]
            )

            app_doc = _doc(applicant.id, "03_7 JOB APPLICATION - NGUYEN MINH PHUONG.docx")
            app_rec = _rec(
                applicant.id, app_doc, "application_form",
                {"address_city": "HANOI"},
            )
            session.add_all([app_doc, app_rec])
            await session.commit()

            numbers = await resolve_doc_records_member_numbers(session, applicant.id, [app_rec])
            assert numbers.get(id(app_rec)) == "03"
        await engine.dispose()

    _run(scenario())


def test_two_predeclared_children_files_not_mixed_or_duplicated(tmp_path):
    """2 con đã khai báo trước — file của mỗi con phải tách riêng đúng người, KHÔNG gộp/nhầm
    lẫn giữa 2 người (mỗi group chỉ chứa tài liệu của đúng 1 người)."""

    async def scenario():
        engine, Session = await _setup(tmp_path, "two_children")
        async with Session() as session:
            applicant, principal, children = await _seed_family(
                session, children_names=["NGUYEN MINH PHUONG", "NGUYEN VAN AN"]
            )

            phuong_doc = _doc(applicant.id, "03_1 BIRTH CERTIFICATE CHILD - PHUONG.pdf")
            phuong_rec = _rec(
                applicant.id, phuong_doc, "birth_certificate_child",
                {"child_full_name": "NGUYEN MINH PHUONG"},
            )
            an_doc = _doc(applicant.id, "04_1 BIRTH CERTIFICATE CHILD - AN.pdf")
            an_rec = _rec(
                applicant.id, an_doc, "birth_certificate_child",
                {"child_full_name": "NGUYEN VAN AN"},
            )
            session.add_all([phuong_doc, phuong_rec, an_doc, an_rec])
            await session.commit()

            groups = await group_doc_records_by_member(
                session, applicant.id, [phuong_rec, an_rec]
            )
            assert set(groups.keys()) == {"03", "04"}
            assert groups["03"] == [phuong_rec]
            assert groups["04"] == [an_rec]
        await engine.dispose()

    _run(scenario())


def test_file_matching_no_declared_member_stays_unassigned_not_guessed(tmp_path):
    """Tài liệu của một người CHƯA khai báo trong hệ thống — không tự đoán gán cho ai (không
    tạo thành viên mới ngầm, không gán nhầm cho thành viên gần giống tên nhất). Ở lại
    "chưa xác định" để nhân viên xử lý thủ công (thêm thành viên mới qua UI rồi chạy lại)."""

    async def scenario():
        engine, Session = await _setup(tmp_path, "unassigned")
        async with Session() as session:
            applicant, principal, children = await _seed_family(
                session, children_names=["NGUYEN MINH PHUONG"]
            )

            # Tên hoàn toàn khác — không phải PHUONG, không phải TRIEU THI DUYEN — chưa có
            # trong hệ thống. Không có tiền tố số file để gợi ý.
            stranger_doc = _doc(applicant.id, "Birth certificate child.pdf")
            stranger_rec = _rec(
                applicant.id, stranger_doc, "birth_certificate_child",
                {"child_full_name": "LE THI KIM CUC"},
            )
            session.add_all([stranger_doc, stranger_rec])
            await session.commit()

            numbers = await resolve_doc_records_member_numbers(session, applicant.id, [stranger_rec])
            assert id(stranger_rec) not in numbers, (
                "Tài liệu của người chưa khai báo không được tự gán cho thành viên nào "
                f"— nhưng ra: {numbers}"
            )

            groups = await group_doc_records_by_member(session, applicant.id, [stranger_rec])
            assert groups == {}, "Không được tự tạo nhóm/thành viên mới từ tài liệu chưa khớp ai"
        await engine.dispose()

    _run(scenario())


def test_declared_child_not_duplicated_when_multiple_files_uploaded_over_time(tmp_path):
    """Con đã khai báo trước — upload NHIỀU file khác nhau theo thời gian (khai sinh, hộ
    chiếu, application form) — tất cả phải gộp về ĐÚNG 1 nhóm (member 03), không tách thành
    nhiều "người" khác nhau dù file rời rạc, không cùng lúc."""

    async def scenario():
        engine, Session = await _setup(tmp_path, "multi_file_over_time")
        async with Session() as session:
            applicant, principal, children = await _seed_family(
                session, children_names=["NGUYEN MINH PHUONG"]
            )

            bc_doc = _doc(applicant.id, "03_1 BIRTH CERTIFICATE CHILD.pdf")
            bc_rec = _rec(
                applicant.id, bc_doc, "birth_certificate_child",
                {"child_full_name": "NGUYEN MINH PHUONG"},
            )
            pp_doc = _doc(applicant.id, "03_2 PASSPORT.pdf")
            pp_rec = _rec(
                applicant.id, pp_doc, "passport",
                {"full_name": "NGUYEN MINH PHUONG"},
            )
            app_doc = _doc(applicant.id, "03_7 JOB APPLICATION.docx")
            app_rec = _rec(
                applicant.id, app_doc, "application_form",
                {"address_city": "HANOI"},
            )
            session.add_all([bc_doc, bc_rec, pp_doc, pp_rec, app_doc, app_rec])
            await session.commit()

            groups = await group_doc_records_by_member(
                session, applicant.id, [bc_rec, pp_rec, app_rec]
            )
            assert set(groups.keys()) == {"03"}, "Cả 3 file của cùng 1 con phải gộp về 1 nhóm duy nhất"
            assert set(groups["03"]) == {bc_rec, pp_rec, app_rec}
        await engine.dispose()

    _run(scenario())
