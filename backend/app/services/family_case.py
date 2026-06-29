"""Bộ hồ sơ gia đình — nhiều người, một lần upload, xuất DS-260 theo từng thành viên."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Applicant, ApplicantDocRecord, CaseMember, PersonRole

_MEMBER_FILE_PREFIX = re.compile(r"^(\d{2})_(\d+)(?:[\s\-_.]|$)", re.I)
_MEMBER_NUMBER_PREFIX = re.compile(r"^(\d{2})[\s\-_.]+", re.I)

# Thứ tự file chuẩn: _1 GKS · _2 HC · _3 ly hôn · _4 lý lịch
_DOC_TYPE_FILE_SLOT: dict[str, int] = {
    "birth_certificate": 1,
    "birth_certificate_child": 1,
    "passport": 2,
    "divorce": 3,
    "judicial_certificate": 4,
}


@dataclass(frozen=True)
class MemberContext:
    id: uuid.UUID
    display_name: str
    role: str


async def load_case_members(db: AsyncSession, applicant_id: uuid.UUID) -> list[CaseMember]:
    result = await db.execute(
        select(CaseMember)
        .where(CaseMember.applicant_id == applicant_id)
        .order_by(CaseMember.sort_order, CaseMember.created_at)
    )
    return list(result.scalars().all())


async def resolve_member_context(
    db: AsyncSession,
    applicant: Applicant,
    member_id: uuid.UUID | None,
) -> MemberContext | None:
    members = await load_case_members(db, applicant.id)
    if not members and not applicant.is_family_bundle:
        return MemberContext(
            id=applicant.id,
            display_name=applicant.display_name,
            role=PersonRole.principal.value,
        )
    if not members:
        return None

    chosen: CaseMember | None = None
    if member_id:
        chosen = next((m for m in members if m.id == member_id), None)
    if not chosen:
        chosen = next((m for m in members if m.role == PersonRole.principal.value), members[0])
    return MemberContext(id=chosen.id, display_name=chosen.display_name, role=chosen.role)


async def create_case_members(
    db: AsyncSession,
    applicant_id: uuid.UUID,
    members: list[dict[str, str]],
) -> list[CaseMember]:
    rows: list[CaseMember] = []
    for idx, item in enumerate(members):
        role = item.get("role") or PersonRole.principal.value
        name = (item.get("display_name") or "").strip()
        if not name:
            continue
        row = CaseMember(
            applicant_id=applicant_id,
            role=role,
            display_name=name,
            sort_order=idx,
        )
        db.add(row)
        rows.append(row)
    await db.flush()
    return rows


def _norm_member_name(name: str) -> str:
    return " ".join((name or "").upper().split())


async def append_case_members(
    db: AsyncSession,
    applicant_id: uuid.UUID,
    members: list[dict[str, str]],
) -> list[CaseMember]:
    """Thêm vợ/con vào hồ sơ đã có — không xóa thành viên cũ, bỏ qua trùng tên."""
    existing = await load_case_members(db, applicant_id)
    if not existing:
        return []

    existing_names = {_norm_member_name(m.display_name) for m in existing}
    has_spouse = any(m.role == PersonRole.spouse.value for m in existing)
    max_order = max((m.sort_order for m in existing), default=-1)
    added: list[CaseMember] = []

    for item in members:
        role = item.get("role") or PersonRole.child.value
        name = (item.get("display_name") or "").strip()
        if not name:
            continue
        if role == PersonRole.principal.value:
            continue
        if role == PersonRole.spouse.value and has_spouse:
            continue
        norm = _norm_member_name(name)
        if norm in existing_names:
            continue
        max_order += 1
        row = CaseMember(
            applicant_id=applicant_id,
            role=role,
            display_name=name,
            sort_order=max_order,
        )
        db.add(row)
        added.append(row)
        existing_names.add(norm)
        if role == PersonRole.spouse.value:
            has_spouse = True

    await db.flush()
    return added


def member_context_to_dict(
    ctx: MemberContext | None,
    *,
    member_number: str | None = None,
) -> dict[str, Any] | None:
    if not ctx:
        return None
    out: dict[str, Any] = {"id": str(ctx.id), "display_name": ctx.display_name, "role": ctx.role}
    if member_number:
        out["member_number"] = member_number
    return out


def format_member_number(index: int) -> str:
    """Số thứ tự thành viên hiển thị: 01, 02, 03…"""
    return f"{max(1, index):02d}"


def member_number_map(members: list[CaseMember]) -> dict[uuid.UUID, str]:
    """
    CaseMember.id → mã cố định theo vai trò:
    01 chủ hồ sơ · 02 phối ngẫu · 03+ các con · rồi đến cháu nội/ngoại ·
    rồi đến anh/chị/em được bảo lãnh (bỏ qua 02 nếu không có vợ/chồng).
    """
    ordered = sorted(members, key=lambda m: (m.sort_order, m.created_at))
    result: dict[uuid.UUID, str] = {}
    principal = next((m for m in ordered if m.role == PersonRole.principal.value), None)
    spouse = next((m for m in ordered if m.role == PersonRole.spouse.value), None)
    children = [m for m in ordered if m.role == PersonRole.child.value]
    grandchildren = [m for m in ordered if m.role == PersonRole.grandchild.value]
    siblings = [m for m in ordered if m.role == PersonRole.sibling.value]

    if principal:
        result[principal.id] = "01"
    if spouse:
        result[spouse.id] = "02"
    for i, child in enumerate(children):
        result[child.id] = format_member_number(3 + i)
    # Cháu nội/ngoại rồi đến anh/chị/em đứng sau các con — số cố định theo cây gia phả.
    next_num = 3 + len(children)
    for i, grandchild in enumerate(grandchildren):
        result[grandchild.id] = format_member_number(next_num + i)
    next_num += len(grandchildren)
    for i, sibling in enumerate(siblings):
        result[sibling.id] = format_member_number(next_num + i)

    for m in ordered:
        if m.id in result:
            continue
        used = {int(v) for v in result.values()}
        n = 1
        while n in used:
            n += 1
        result[m.id] = format_member_number(n)
    return result


def member_by_number(members: list[CaseMember]) -> dict[int, CaseMember]:
    numbers = member_number_map(members)
    out: dict[int, CaseMember] = {}
    for m in members:
        num_str = numbers.get(m.id)
        if num_str:
            out[int(num_str)] = m
    return out


def infer_file_slot_from_doc_type(doc_type: str | None) -> int | None:
    if not doc_type:
        return None
    return _DOC_TYPE_FILE_SLOT.get(doc_type)


def _next_free_file_slot(used: set[int], start: int = 5) -> int:
    n = start
    while n in used:
        n += 1
    return n


def _label_for_member(
    member_number: str,
    *,
    file_idx: int | None,
    doc_type: str | None,
) -> str:
    slot = file_idx if file_idx is not None else infer_file_slot_from_doc_type(doc_type)
    return format_member_file_label(member_number, slot)


@dataclass(frozen=True)
class DocumentLabelInput:
    document_id: uuid.UUID
    filename: str
    registry_doc_type: str | None
    doc_record: ApplicantDocRecord | None
    uploaded_at: datetime


def _resolve_member_identity(
    *,
    filename: str,
    registry_doc_type: str | None,
    doc_record: ApplicantDocRecord | None,
    members: list[CaseMember],
    numbers: dict[uuid.UUID, str],
    by_num: dict[int, CaseMember],
) -> tuple[str | None, str | None, int | None, str | None]:
    """Returns (member_number, display_name, explicit_file_idx, doc_type)."""
    doc_type = registry_doc_type or (doc_record.doc_type if doc_record else None)
    prefix_num, file_idx = parse_member_file_prefix(filename)

    if prefix_num and prefix_num in by_num:
        m = by_num[prefix_num]
        return numbers[m.id], m.display_name, file_idx, doc_type

    if doc_record:
        from app.services.ds260_mapping import _names_same_person

        ocr_name = _person_name_from_doc_record(doc_record)
        if ocr_name:
            for m in members:
                if _names_same_person(ocr_name, m.display_name):
                    return numbers[m.id], m.display_name, file_idx, doc_type

    shared = frozenset({"divorce", "marriage_certificate", "ds260_customer_form"})
    if doc_type in shared:
        principal = next((m for m in members if m.role == PersonRole.principal.value), members[0])
        return numbers[principal.id], principal.display_name, file_idx, doc_type

    # Hồ sơ đơn (chỉ 1 người) — gán mặc định 01_x theo loại giấy
    if len(members) == 1:
        m = members[0]
        return numbers[m.id], m.display_name, file_idx, doc_type

    return None, None, file_idx, doc_type


def synthetic_principal_member(applicant: Applicant) -> CaseMember:
    """Hồ sơ chưa khai báo thành viên — coi chủ hồ sơ là 01."""
    return CaseMember(
        id=uuid.uuid5(uuid.NAMESPACE_OID, f"synthetic-principal-{applicant.id}"),
        applicant_id=applicant.id,
        role=PersonRole.principal.value,
        display_name=applicant.display_name,
        sort_order=0,
    )


def members_for_document_labeling(
    applicant: Applicant | None,
    members: list[CaseMember],
) -> list[CaseMember]:
    if members:
        return members
    if applicant:
        return [synthetic_principal_member(applicant)]
    return []


def _assign_file_slots(
    grouped: dict[str, list[tuple[str, uuid.UUID, int | None, str | None, datetime]]],
) -> dict[uuid.UUID, tuple[str, str, str]]:
    out: dict[uuid.UUID, tuple[str, str, str]] = {}
    for num, docs in grouped.items():
        display_name = docs[0][0]
        ordered = sorted(docs, key=lambda row: row[4])
        used: set[int] = set()
        for _name, doc_id, explicit_idx, doc_type, _uploaded_at in ordered:
            if explicit_idx is not None:
                slot = explicit_idx
            else:
                standard = infer_file_slot_from_doc_type(doc_type)
                if standard is not None and standard not in used:
                    slot = standard
                else:
                    slot = _next_free_file_slot(used)
            used.add(slot)
            out[doc_id] = (num, display_name, format_member_file_label(num, slot))
    return out


def parse_member_file_prefix(filename: str) -> tuple[int | None, int | None]:
    """
    Đọc prefix tên file: ``01_1`` (chủ hồ sơ, file 1), ``02_3``, ``04_2``, hoặc ``01 - Passport``.
    Returns (member_index, file_index) — file_index None nếu không có số file.
    """
    stem = Path(filename or "").stem.strip()
    match = _MEMBER_FILE_PREFIX.match(stem)
    if match:
        person = int(match.group(1))
        file_idx = int(match.group(2))
        if 1 <= person <= 99 and 1 <= file_idx <= 99:
            return person, file_idx
    match = _MEMBER_NUMBER_PREFIX.match(stem)
    if match:
        person = int(match.group(1))
        if 1 <= person <= 99:
            return person, None
    return None, None


def parse_member_number_from_filename(filename: str) -> int | None:
    """Chỉ số người (01, 02…) — tương thích code cũ."""
    person, _file = parse_member_file_prefix(filename)
    return person


def format_member_file_label(member_number: str, file_index: int | None) -> str:
    """Nhãn hiển thị: 01_1, 02_3 hoặc 01 nếu không có số file."""
    if file_index is not None:
        return f"{member_number}_{file_index}"
    return member_number


def _person_name_from_doc_record(rec: ApplicantDocRecord) -> str:
    from app.services.ds260_mapping import _resolve_from_record

    if rec.doc_type == "birth_certificate_child":
        return _resolve_from_record(rec, "child_full_name", ("full_name", "name"))
    return _resolve_from_record(rec, "full_name", ("name",))


def resolve_document_member_labels_batch(
    *,
    items: list[DocumentLabelInput],
    members: list[CaseMember],
) -> dict[uuid.UUID, tuple[str | None, str | None, str | None]]:
    """Gán mã người + mã file (_1…_4 chuẩn, _5+ cho file thêm)."""
    if not members:
        return {item.document_id: (None, None, None) for item in items}

    numbers = member_number_map(members)
    by_num = member_by_number(members)
    grouped: dict[str, list[tuple[str, uuid.UUID, int | None, str | None, datetime]]] = {}
    result: dict[uuid.UUID, tuple[str | None, str | None, str | None]] = {}

    for item in items:
        num, name, explicit_idx, doc_type = _resolve_member_identity(
            filename=item.filename,
            registry_doc_type=item.registry_doc_type,
            doc_record=item.doc_record,
            members=members,
            numbers=numbers,
            by_num=by_num,
        )
        if not num or not name:
            result[item.document_id] = (None, None, None)
            continue
        grouped.setdefault(num, []).append(
            (name, item.document_id, explicit_idx, doc_type, item.uploaded_at)
        )

    for doc_id, triple in _assign_file_slots(grouped).items():
        result[doc_id] = triple
    return result


def resolve_document_member_label(
    *,
    filename: str,
    registry_doc_type: str | None,
    doc_record: ApplicantDocRecord | None,
    members: list[CaseMember],
) -> tuple[str | None, str | None, str | None]:
    """Một file — ưu tiên gọi batch khi có nhiều file cùng hồ sơ."""
    doc_id = uuid.uuid4()
    return resolve_document_member_labels_batch(
        items=[
            DocumentLabelInput(
                document_id=doc_id,
                filename=filename,
                registry_doc_type=registry_doc_type,
                doc_record=doc_record,
                uploaded_at=datetime.min,
            )
        ],
        members=members,
    ).get(doc_id, (None, None, None))


def case_member_out_dict(member: CaseMember, member_number: str) -> dict[str, Any]:
    return {
        "id": member.id,
        "role": member.role,
        "display_name": member.display_name,
        "sort_order": member.sort_order,
        "member_number": member_number,
    }


def serialize_case_members(members: list[CaseMember]) -> list[dict[str, Any]]:
    ordered = sorted(members, key=lambda m: (m.sort_order, m.created_at))
    numbers = member_number_map(members)
    return [case_member_out_dict(m, numbers[m.id]) for m in ordered]


async def find_spouse_member_in_case(
    db: AsyncSession,
    applicant_id: uuid.UUID,
    current: MemberContext,
) -> CaseMember | None:
    if current.role not in (PersonRole.principal.value, PersonRole.spouse.value):
        return None
    members = await load_case_members(db, applicant_id)
    for m in members:
        if m.id == current.id:
            continue
        if m.role == PersonRole.spouse.value:
            return m
    return None


def pick_child_birth_cert_for_person(
    records: list[ApplicantDocRecord],
    person_name: str,
) -> ApplicantDocRecord | None:
    from app.services.ds260_mapping import _names_same_person, _resolve_from_record

    matched: list[ApplicantDocRecord] = []
    for rec in records:
        if rec.doc_type not in ("birth_certificate_child", "birth_certificate"):
            continue
        if rec.doc_type == "birth_certificate_child":
            name = _resolve_from_record(rec, "child_full_name", ("full_name", "name"))
        else:
            name = _resolve_from_record(rec, "full_name", ("name", "child_full_name"))
        if name and _names_same_person(name, person_name):
            matched.append(rec)
    if not matched:
        return None
    # Ưu tiên birth_certificate_child; trong cùng loại lấy bản mới nhất
    def _sort_key(r: ApplicantDocRecord) -> tuple:
        type_rank = 0 if r.doc_type == "birth_certificate_child" else 1
        return (type_rank, r.updated_at or r.id, str(r.id))

    return max(matched, key=_sort_key)


def _resolve_child_parent_name_for_fill(
    child_rec: ApplicantDocRecord | None,
    parent: str,
    members: list[CaseMember] | None,
    role: str = PersonRole.child.value,
) -> str:
    """
    Tên cha/mẹ trên DS-260 con: ưu tiên GKS con.

    - Con (child): fallback chủ hồ sơ (cha) / phối ngẫu (mẹ).
    - Cháu (grandchild): chỉ lấy từ GKS của cháu — cha/mẹ là một thành viên 'con'
      trong hồ sơ, khớp tên ở bước enrich (cây gia phả), không fallback ông/bà.
    """
    from app.services.ds260_mapping import _resolve_from_record

    aliases = ("father_full_name",) if parent == "father" else ("mother_full_name",)
    if child_rec:
        name = _resolve_from_record(child_rec, f"{parent}_name", aliases)
        if name.strip():
            return name.strip()

    if not members or role == PersonRole.grandchild.value:
        return ""

    if parent == "father":
        principal = next((m for m in members if m.role == PersonRole.principal.value), None)
        return (principal.display_name or "").strip() if principal else ""
    spouse = next((m for m in members if m.role == PersonRole.spouse.value), None)
    return (spouse.display_name or "").strip() if spouse else ""


def _fill_child_parent_identity(
    fields_out: list[dict[str, Any]],
    parent: str,
    parent_full_name: str,
    *,
    document_type: str,
    source_field: str,
    record_id: str | None,
    derived: str,
) -> None:
    from app.services.ds260_mapping import _split_vn_person_name

    full = (parent_full_name or "").strip()
    if not full:
        return
    sur, given = _split_vn_person_name(full)
    _force_ds260_field(
        fields_out,
        f"{parent}_full_name",
        full,
        document_type=document_type,
        source_field=source_field,
        record_id=record_id,
        derived=derived,
    )
    if sur:
        _force_ds260_field(
            fields_out,
            f"{parent}_surname",
            sur,
            document_type=document_type,
            source_field=source_field,
            record_id=record_id,
            derived=f"{derived}_split",
        )
    if given:
        _force_ds260_field(
            fields_out,
            f"{parent}_given_names",
            given,
            document_type=document_type,
            source_field=source_field,
            record_id=record_id,
            derived=f"{derived}_split",
        )
    _force_ds260_field(
        fields_out,
        f"{parent}_is_living",
        "Yes",
        document_type=document_type,
        source_field=source_field,
        record_id=record_id,
        derived=f"{derived}_living",
    )


def enrich_child_member_personal(
    fields_out: list[dict[str, Any]],
    child_rec: ApplicantDocRecord | None,
    passport_rec: ApplicantDocRecord | None,
) -> None:
    from app.services.ds260_mapping import _resolve_from_record, _split_vn_person_name, empty_ds260_field_source

    derived: dict[str, str] = {}
    child_rid = str(child_rec.id) if child_rec else None
    passport_rid = str(passport_rec.id) if passport_rec else None

    if child_rec:
        derived["applicant_name"] = _resolve_from_record(
            child_rec, "child_full_name", ("full_name", "name")
        )
        derived["applicant_name_native"] = derived["applicant_name"]
        derived["date_of_birth"] = _resolve_from_record(
            child_rec, "child_date_of_birth", ("date_of_birth", "dob")
        )
        derived["birth_city"] = _resolve_from_record(
            child_rec, "child_birth_city", ("birth_city",)
        )
        derived["birth_state"] = _resolve_from_record(
            child_rec, "child_birth_state", ("birth_state",)
        )
        derived["birth_country"] = _resolve_from_record(
            child_rec, "child_birth_country", ("birth_country",)
        )
        derived["gender"] = _resolve_from_record(child_rec, "child_gender", ("gender",))
        derived["father_full_name"] = _resolve_from_record(child_rec, "father_name", ())
        derived["mother_full_name"] = _resolve_from_record(child_rec, "mother_name", ())
        pob = _resolve_from_record(
            child_rec, "child_place_of_birth", ("place_of_birth", "child_birth_city")
        )
        if pob:
            derived["place_of_birth"] = pob
        nat = derived.get("birth_country") or ""
        if nat:
            derived["nationality"] = nat
        full = derived.get("applicant_name") or ""
        if full:
            sur, given = _split_vn_person_name(full)
            if sur:
                derived["family_name"] = sur
            if given:
                derived["given_names"] = given

    if passport_rec:
        passport_fields: tuple[tuple[str, str, tuple[str, ...]], ...] = (
            ("applicant_name", "full_name", ("name",)),
            ("applicant_name_native", "full_name_native", ("name_native_language", "native_full_name")),
            ("family_name", "family_name", ("surname", "last_name")),
            ("given_names", "given_names", ("given_name", "first_name")),
            ("date_of_birth", "date_of_birth", ("dob", "birth_date")),
            ("gender", "gender", ("sex",)),
            ("passport_number", "passport_number", ()),
            ("place_of_birth", "place_of_birth", ("birth_place",)),
            ("birth_city", "birth_city", ("city_of_birth",)),
            ("nationality", "nationality", ("country_of_nationality",)),
            ("id_card_number", "id_card_number", ("national_id", "cmnd", "cccd")),
        )
        for key, field, aliases in passport_fields:
            val = _resolve_from_record(passport_rec, field, aliases)
            if key == "applicant_name_native" and not val:
                val = _resolve_from_record(passport_rec, "full_name", ("name",))
            if val:
                derived[key] = val

    key_map = {
        "applicant_name": "applicant_name",
        "applicant_name_native": "applicant_name_native",
        "family_name": "family_name",
        "given_names": "given_names",
        "date_of_birth": "date_of_birth",
        "place_of_birth": "place_of_birth",
        "birth_city": "birth_city",
        "birth_state": "birth_state",
        "birth_country": "birth_country",
        "gender": "gender",
        "nationality": "nationality",
        "id_card_number": "id_card_number",
        "passport_number": "passport_number",
        "father_full_name": "father_full_name",
        "mother_full_name": "mother_full_name",
    }
    passport_only_keys = frozenset({"id_card_number", "passport_number"})

    for field in fields_out:
        key = field.get("key", "")
        mapped = key_map.get(key)
        if not mapped:
            continue
        if not passport_rec and key in passport_only_keys:
            field["value"] = ""
            field["source"] = empty_ds260_field_source()
            continue
        val = (derived.get(mapped) or "").strip()
        if not val:
            continue
        field["value"] = val
        child_source_fields: dict[str, str] = {
            "applicant_name": "child_full_name",
            "applicant_name_native": "child_full_name",
            "family_name": "child_full_name",
            "given_names": "child_full_name",
            "date_of_birth": "child_date_of_birth",
            "place_of_birth": "child_place_of_birth",
            "birth_city": "child_birth_city",
            "birth_state": "child_birth_state",
            "birth_country": "child_birth_country",
            "gender": "child_gender",
            "nationality": "child_birth_country",
            "father_full_name": "father_name",
            "mother_full_name": "mother_name",
        }
        if passport_rec and (key in passport_only_keys or _field_from_passport(passport_rec, mapped)):
            doc_type, rid, src_field = "passport", passport_rid, mapped
        else:
            doc_type, rid, src_field = (
                "birth_certificate_child",
                child_rid,
                child_source_fields.get(key, "child_full_name"),
            )
        field["source"] = {
            **empty_ds260_field_source(),
            "document_type": doc_type,
            "source_field": src_field,
            "record_id": rid,
            "derived": "child_member_personal",
        }


def _field_from_passport(passport_rec: ApplicantDocRecord, mapped: str) -> bool:
    from app.services.ds260_mapping import _resolve_from_record

    checks: dict[str, tuple[str, tuple[str, ...]]] = {
        "applicant_name": ("full_name", ("name",)),
        "applicant_name_native": ("full_name_native", ("name_native_language", "native_full_name")),
        "family_name": ("family_name", ("surname", "last_name")),
        "given_names": ("given_names", ("given_name", "first_name")),
        "date_of_birth": ("date_of_birth", ("dob",)),
        "gender": ("gender", ("sex",)),
        "place_of_birth": ("place_of_birth", ("birth_place",)),
        "birth_city": ("birth_city", ("city_of_birth",)),
        "nationality": ("nationality", ()),
    }
    spec = checks.get(mapped)
    if mapped == "applicant_name_native":
        return bool(
            _resolve_from_record(
                passport_rec, "full_name_native", ("name_native_language", "native_full_name")
            )
            or _resolve_from_record(passport_rec, "full_name", ("name",))
        )
    if not spec:
        return False
    field, aliases = spec
    return bool(_resolve_from_record(passport_rec, field, aliases))


def _force_ds260_field(
    fields_out: list[dict[str, Any]],
    key: str,
    value: str,
    *,
    document_type: str,
    source_field: str,
    record_id: str | None,
    derived: str,
) -> None:
    from app.services.ds260_mapping import empty_ds260_field_source

    for field in fields_out:
        if field.get("key") != key:
            continue
        field["value"] = value
        field["source"] = {
            **empty_ds260_field_source(),
            "document_type": document_type,
            "source_field": source_field,
            "record_id": record_id,
            "derived": derived,
        }
        break


def _fill_empty_parent_ds260_field(
    fields_out: list[dict[str, Any]],
    key: str,
    value: str,
    *,
    document_type: str,
    source_field: str,
    record_id: str | None,
    derived: str,
) -> None:
    if not (value or "").strip():
        return
    for field in fields_out:
        if field.get("key") != key:
            continue
        if (field.get("value") or "").strip():
            return
        field["value"] = value.strip()
        from app.services.ds260_mapping import empty_ds260_field_source

        field["source"] = {
            **empty_ds260_field_source(),
            "document_type": document_type,
            "source_field": source_field,
            "record_id": record_id,
            "derived": derived,
        }
        return


def _enrich_parent_place_from_record(
    fields_out: list[dict[str, Any]],
    parent: str,
    place: str,
    *,
    document_type: str,
    source_field: str,
    record_id: str | None,
    derived: str,
) -> None:
    from app.services.birth_location import (
        derive_birth_state_from_place,
        derive_city_from_place,
        derive_country_from_place,
    )

    if not (place or "").strip():
        return
    city = derive_city_from_place(place) or place.strip()
    state = derive_birth_state_from_place(place) or place.strip()
    country = derive_country_from_place(place)
    _fill_empty_parent_ds260_field(
        fields_out,
        f"{parent}_birth_city",
        city,
        document_type=document_type,
        source_field=source_field,
        record_id=record_id,
        derived=derived,
    )
    _fill_empty_parent_ds260_field(
        fields_out,
        f"{parent}_birth_state",
        state,
        document_type=document_type,
        source_field=source_field,
        record_id=record_id,
        derived=derived,
    )
    if country:
        _fill_empty_parent_ds260_field(
            fields_out,
            f"{parent}_birth_country",
            country,
            document_type=document_type,
            source_field=source_field,
            record_id=record_id,
            derived=derived,
        )


def enrich_child_parent_details_from_case(
    fields_out: list[dict[str, Any]],
    parent: str,
    parent_full_name: str,
    records: list[ApplicantDocRecord],
    members: list[CaseMember],
) -> None:
    """
    Bổ sung ngày sinh / nơi sinh cha-mẹ con từ giấy tờ hồ sơ khi tên trùng
    (hộ chiếu chủ hồ sơ/phối ngẫu, GKS chủ hồ sơ, ly hôn, giấy kết hôn).
    """
    from app.services.ds260_mapping import (
        _names_same_person,
        _resolve_from_record,
        pick_latest_record,
        pick_luong1_pair,
        pick_luong1_pair_for_person,
    )

    if not (parent_full_name or "").strip():
        return

    # Cây gia phả: khớp tên cha/mẹ với BẤT KỲ thành viên nào trong hồ sơ.
    # - Hồ sơ con: cha/mẹ khớp chủ hồ sơ / phối ngẫu.
    # - Hồ sơ cháu: cha/mẹ khớp một thành viên 'con' (nhánh con) → lấy giấy tờ của con đó.
    for member in members:
        if not _names_same_person(parent_full_name, member.display_name):
            continue
        label = member.role

        passport_rec, _ = pick_luong1_pair_for_person(records, "passport", member.display_name)
        if passport_rec:
            rid = str(passport_rec.id)
            dob = _resolve_from_record(passport_rec, "date_of_birth", ("dob", "birth_date"))
            pob = _resolve_from_record(passport_rec, "place_of_birth", ("birth_place",))
            nat = _resolve_from_record(passport_rec, "nationality", ())
            _fill_empty_parent_ds260_field(
                fields_out,
                f"{parent}_date_of_birth",
                dob,
                document_type="passport",
                source_field="date_of_birth",
                record_id=rid,
                derived=f"child_{parent}_from_{label}_passport",
            )
            _enrich_parent_place_from_record(
                fields_out,
                parent,
                pob,
                document_type="passport",
                source_field="place_of_birth",
                record_id=rid,
                derived=f"child_{parent}_from_{label}_passport",
            )
            if nat:
                from app.services.birth_location import format_nationality_country

                country = format_nationality_country(nat)
                if country:
                    _fill_empty_parent_ds260_field(
                        fields_out,
                        f"{parent}_birth_country",
                        country,
                        document_type="passport",
                        source_field="nationality",
                        record_id=rid,
                        derived=f"child_{parent}_from_{label}_passport",
                    )

        # GKS của thành viên đó — chủ hồ sơ dùng birth_certificate, con dùng birth_certificate_child.
        bc = pick_child_birth_cert_for_person(records, member.display_name)
        if bc:
            rid = str(bc.id)
            dob = _resolve_from_record(
                bc, "date_of_birth", ("dob", "child_date_of_birth")
            )
            pob = _resolve_from_record(
                bc, "place_of_birth", ("birth_place", "child_birth_city", "birth_city")
            )
            _fill_empty_parent_ds260_field(
                fields_out,
                f"{parent}_date_of_birth",
                dob,
                document_type=bc.doc_type or "birth_certificate",
                source_field="date_of_birth",
                record_id=rid,
                derived=f"child_{parent}_from_{label}_birth_cert",
            )
            _enrich_parent_place_from_record(
                fields_out,
                parent,
                pob,
                document_type=bc.doc_type or "birth_certificate",
                source_field="place_of_birth",
                record_id=rid,
                derived=f"child_{parent}_from_{label}_birth_cert",
            )

    divorce_rec = pick_latest_record(records, "divorce")
    if divorce_rec:
        rid = str(divorce_rec.id)
        for side in ("husband", "wife"):
            name = _resolve_from_record(divorce_rec, f"{side}_full_name", (f"{side}_name",))
            if not _names_same_person(name, parent_full_name):
                continue
            dob = _resolve_from_record(divorce_rec, f"{side}_date_of_birth", ())
            _fill_empty_parent_ds260_field(
                fields_out,
                f"{parent}_date_of_birth",
                dob,
                document_type="divorce",
                source_field=f"{side}_date_of_birth",
                record_id=rid,
                derived=f"child_{parent}_from_divorce_{side}",
            )

    marriage_rec, marriage_ref = pick_luong1_pair(records, "marriage_certificate")
    for rec in (marriage_rec, marriage_ref):
        if not rec:
            continue
        rid = str(rec.id)
        for side in ("husband", "wife"):
            name = _resolve_from_record(rec, f"{side}_full_name", (f"{side}_name",))
            if not _names_same_person(name, parent_full_name):
                continue
            dob = _resolve_from_record(rec, f"{side}_date_of_birth", ())
            pob = _resolve_from_record(
                rec,
                f"{side}_place_of_birth",
                (f"{side}_birth_city", f"{side}_birth_place"),
            )
            city = _resolve_from_record(rec, f"{side}_birth_city", ())
            _fill_empty_parent_ds260_field(
                fields_out,
                f"{parent}_date_of_birth",
                dob,
                document_type="marriage_certificate",
                source_field=f"{side}_date_of_birth",
                record_id=rid,
                derived=f"child_{parent}_from_marriage_{side}",
            )
            place = pob or city
            _enrich_parent_place_from_record(
                fields_out,
                parent,
                place,
                document_type="marriage_certificate",
                source_field=f"{side}_place_of_birth",
                record_id=rid,
                derived=f"child_{parent}_from_marriage_{side}",
            )
            country = _resolve_from_record(rec, f"{side}_birth_country", ())
            if country:
                _fill_empty_parent_ds260_field(
                    fields_out,
                    f"{parent}_birth_country",
                    country,
                    document_type="marriage_certificate",
                    source_field=f"{side}_birth_country",
                    record_id=rid,
                    derived=f"child_{parent}_from_marriage_{side}",
                )


def enrich_child_parent_section_from_birth_cert(
    fields_out: list[dict[str, Any]],
    child_rec: ApplicantDocRecord,
    parent: str,
) -> None:
    """Điền section cha/mẹ của hồ sơ con từ giấy khai sinh con (birth_certificate_child)."""
    from app.services.ds260_mapping import (
        _resolve_from_record,
        has_parent_info_on_birth_cert,
    )

    doc_type = child_rec.doc_type if child_rec.doc_type in (
        "birth_certificate_child",
        "birth_certificate",
    ) else "birth_certificate_child"
    rid = str(child_rec.id)
    aliases = ("father_full_name",) if parent == "father" else ("mother_full_name",)
    full = _resolve_from_record(child_rec, f"{parent}_name", aliases)
    if not full and not has_parent_info_on_birth_cert(child_rec, parent):
        return

    if full:
        _fill_child_parent_identity(
            fields_out,
            parent,
            full,
            document_type=doc_type,
            source_field=f"{parent}_name",
            record_id=rid,
            derived="child_birth_cert_parent",
        )
    elif has_parent_info_on_birth_cert(child_rec, parent):
        _force_ds260_field(
            fields_out,
            f"{parent}_is_living",
            "Yes",
            document_type=doc_type,
            source_field=f"{parent}_name",
            record_id=rid,
            derived="child_birth_cert_parent_living",
        )


def enrich_child_birth_certificate_section(
    fields_out: list[dict[str, Any]],
    child_rec: ApplicantDocRecord,
) -> None:
    """Điền section GKS của hồ sơ con từ birth_certificate_child."""
    from app.services.ds260_mapping import _resolve_from_record

    doc_type = "birth_certificate_child"
    rid = str(child_rec.id)
    mappings: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("birth_cert_full_name", "child_full_name", ("full_name", "name")),
        ("birth_cert_date_of_birth", "child_date_of_birth", ("date_of_birth", "dob")),
        ("birth_cert_gender", "child_gender", ("gender",)),
        ("birth_cert_father_name", "father_name", ()),
        ("birth_cert_mother_name", "mother_name", ()),
        ("birth_cert_registration_number", "registration_number", ()),
    )
    for ds260_key, src_field, aliases in mappings:
        val = _resolve_from_record(child_rec, src_field, aliases)
        if val:
            _force_ds260_field(
                fields_out,
                ds260_key,
                val,
                document_type=doc_type,
                source_field=src_field,
                record_id=rid,
                derived="child_birth_cert_section",
            )

    place = _resolve_from_record(child_rec, "child_birth_city", ("birth_city", "place_of_birth"))
    if not place:
        city = _resolve_from_record(child_rec, "child_birth_city", ("birth_city",))
        state = _resolve_from_record(child_rec, "child_birth_state", ("birth_state",))
        parts = [p for p in (city, state) if p]
        place = ", ".join(parts) if parts else ""
    if place:
        _force_ds260_field(
            fields_out,
            "birth_cert_place_of_birth",
            place,
            document_type=doc_type,
            source_field="child_birth_city",
            record_id=rid,
            derived="child_birth_cert_section",
        )


def apply_child_sections_from_birth_cert(
    sections_out: list[dict[str, Any]],
    child_rec: ApplicantDocRecord | None,
    *,
    records: list[ApplicantDocRecord] | None = None,
    members: list[CaseMember] | None = None,
    role: str = PersonRole.child.value,
) -> None:
    """
    Ghi đè section cha/mẹ/GKS cho hồ sơ con/cháu — sau enrich_empty để không bị GKS chủ hồ sơ lấn.

    Với cháu (grandchild), cha/mẹ lấy từ GKS của cháu; chi tiết DOB/nơi sinh của cha/mẹ
    được bổ sung từ giấy tờ của thành viên 'con' trùng tên (nhánh con — cây gia phả).
    """
    from app.services.ds260_mapping import (
        _resolve_from_record,
        apply_father_absent_rule,
        apply_mother_absent_rule,
        empty_ds260_field_source,
        enrich_parent_death_from_death_cert,
        pick_latest_record,
    )

    father_name = _resolve_child_parent_name_for_fill(child_rec, "father", members, role)
    mother_name = _resolve_child_parent_name_for_fill(child_rec, "mother", members, role)

    for sec in sections_out:
        if sec["id"] not in ("section_father", "section_mother", "section_birth_certificate"):
            continue
        for field in sec["fields"]:
            field["value"] = ""
            field["source"] = empty_ds260_field_source()

        if sec["id"] == "section_father":
            if child_rec or father_name:
                bc_father_name = ""
                if child_rec:
                    bc_father_name = _resolve_from_record(
                        child_rec, "father_name", ("father_full_name",)
                    )
                if bc_father_name.strip():
                    enrich_child_parent_section_from_birth_cert(sec["fields"], child_rec, "father")
                elif father_name:
                    rid = str(child_rec.id) if child_rec else None
                    _fill_child_parent_identity(
                        sec["fields"],
                        "father",
                        father_name,
                        document_type="case_member",
                        source_field="principal_display_name",
                        record_id=rid,
                        derived="child_father_from_principal_member",
                    )
                if records is not None and members is not None and father_name:
                    enrich_child_parent_details_from_case(
                        sec["fields"], "father", father_name, records, members
                    )
            else:
                apply_father_absent_rule(sec["fields"])
        elif sec["id"] == "section_mother":
            if child_rec or mother_name:
                bc_mother_name = ""
                if child_rec:
                    bc_mother_name = _resolve_from_record(
                        child_rec, "mother_name", ("mother_full_name",)
                    )
                if bc_mother_name.strip():
                    enrich_child_parent_section_from_birth_cert(sec["fields"], child_rec, "mother")
                elif mother_name:
                    rid = str(child_rec.id) if child_rec else None
                    _fill_child_parent_identity(
                        sec["fields"],
                        "mother",
                        mother_name,
                        document_type="case_member",
                        source_field="spouse_display_name",
                        record_id=rid,
                        derived="child_mother_from_spouse_member",
                    )
                if records is not None and members is not None and mother_name:
                    enrich_child_parent_details_from_case(
                        sec["fields"], "mother", mother_name, records, members
                    )
            else:
                apply_mother_absent_rule(sec["fields"])
        elif sec["id"] == "section_birth_certificate" and child_rec:
            enrich_child_birth_certificate_section(sec["fields"], child_rec)
            rid = str(child_rec.id)
            doc_type = child_rec.doc_type if child_rec.doc_type in (
                "birth_certificate_child",
                "birth_certificate",
            ) else "birth_certificate_child"
            for ds_key, name, src_field, derived in (
                (
                    "birth_cert_father_name",
                    father_name,
                    "father_name",
                    "child_bc_father_from_member",
                ),
                (
                    "birth_cert_mother_name",
                    mother_name,
                    "mother_name",
                    "child_bc_mother_from_member",
                ),
            ):
                if not name:
                    continue
                slot = next((f for f in sec["fields"] if f.get("key") == ds_key), None)
                if slot and not (slot.get("value") or "").strip():
                    _force_ds260_field(
                        sec["fields"],
                        ds_key,
                        name,
                        document_type=doc_type,
                        source_field=src_field,
                        record_id=rid,
                        derived=derived,
                    )

    # Giấy báo tử → cha/mẹ của con "đã mất" + năm mất (ghi đè còn-sống mặc định "Yes").
    death_rec = pick_latest_record(records, "death_certificate") if records else None
    if death_rec:
        for sec in sections_out:
            if sec["id"] == "section_father" and father_name:
                enrich_parent_death_from_death_cert(
                    sec["fields"], death_rec, "father", father_name
                )
            elif sec["id"] == "section_mother" and mother_name:
                enrich_parent_death_from_death_cert(
                    sec["fields"], death_rec, "mother", mother_name
                )


def apply_sibling_parent_fallback(
    sections_out: list[dict[str, Any]],
    records: list[ApplicantDocRecord],
    members: list[CaseMember],
    person_name: str,
) -> None:
    """
    Anh/chị/em được bảo lãnh dùng chung cha/mẹ với đương đơn chính (cây gia phả).

    Form anh/chị/em là bản đầy đủ; cha/mẹ ưu tiên lấy từ GKS riêng của họ. Khi GKS
    riêng thiếu tên cha/mẹ, kế thừa cha/mẹ từ GKS của đương đơn chính và bổ sung
    ngày sinh / nơi sinh từ giấy tờ trùng tên trong hồ sơ.
    """
    from app.services.ds260_mapping import (
        _names_same_person,
        _resolve_from_record,
        pick_luong1_pair_for_person,
    )

    principal = next((m for m in members if m.role == PersonRole.principal.value), None)
    if not principal:
        return
    # Chính đương đơn chính thì không cần kế thừa.
    if _names_same_person(person_name, principal.display_name):
        return

    bc, bc_ref = pick_luong1_pair_for_person(records, "birth_certificate", principal.display_name)
    principal_bc = bc or bc_ref
    if not principal_bc:
        return

    aliases = {"father": ("father_full_name",), "mother": ("mother_full_name",)}
    for sec in sections_out:
        parent = (
            "father"
            if sec.get("id") == "section_father"
            else "mother"
            if sec.get("id") == "section_mother"
            else None
        )
        if not parent:
            continue
        slot = next(
            (f for f in sec["fields"] if f.get("key") == f"{parent}_full_name"), None
        )
        # GKS riêng của anh/chị/em đã có cha/mẹ → giữ nguyên, không kế thừa.
        if slot and (slot.get("value") or "").strip():
            continue
        name = _resolve_from_record(principal_bc, f"{parent}_name", aliases[parent])
        if not name.strip():
            continue
        _fill_child_parent_identity(
            sec["fields"],
            parent,
            name,
            document_type=principal_bc.doc_type or "birth_certificate",
            source_field=f"{parent}_name",
            record_id=str(principal_bc.id),
            derived="sibling_parent_from_principal_birth_cert",
        )
        enrich_child_parent_details_from_case(sec["fields"], parent, name, records, members)
