"""
DS-260 — Luồng 1 vs nguồn đối chiếu + worksheet khách khai.

Luồng 1 (variant=standard): file mẫu chuẩn — Passport, Birth certificate,
JUDICIAL CERTIFICATE, Marriage certificate.

Nguồn đối chiếu (variant=exception, hậu tố _new): người khai upload để đối chiếu.
Worksheet DS-260 (ds260_customer_form): form khách điền đầy đủ.

Khi hai nguồn khác nhau → Conflict; người dùng chọn giá trị → DS-260 dùng giá trị đã chọn.
Mặc định (chưa xung đột / chưa chọn): ưu tiên Luồng 1 (standard).
"""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ApplicantDocRecord, Conflict, ConflictStatus, ProfileField
from app.services.doc_record_sync import list_doc_records

# Luồng 1 — file mẫu chuẩn
LUONG1_DOC_TYPES: frozenset[str] = frozenset(
    {
        "passport",
        "birth_certificate",
        "judicial_certificate",
        "marriage_certificate",
    }
)

DS260_CONFLICT_PREFIX = "ds260."
WORKSHEET_CONFLICT_SEGMENT = "document_vs_worksheet"
DS260_MANUAL_SEGMENT = "manual"

# DS-260 mapping keys compared: official (Luồng 1 resolved) vs ds260_customer_form
WORKSHEET_COMPARE_KEYS: frozenset[str] = frozenset(
    {
        "applicant_name",
        "date_of_birth",
        "gender",
        "nationality",
        "place_of_birth",
        "passport_number",
        "passport_issue_date",
        "passport_expiration_date",
        "current_marital_status",
        "current_address",
        "primary_phone",
        "email",
    }
)

# Giá trị "chính thức" so với worksheet — override mapping.document khi cần.
# Address/contact trên worksheet; nguồn đối chiếu thường là Passport_new.
WORKSHEET_OFFICIAL_DOC_OVERRIDES: dict[str, str] = {
    "current_address": "passport",
    "primary_phone": "passport",
    "email": "passport",
}

_DATE_COMPARE_KEYS = frozenset(
    {
        "date_of_birth",
        "passport_issue_date",
        "passport_expiration_date",
    }
)


def ds260_conflict_field_key(doc_type: str, source_field: str) -> str:
    return f"{DS260_CONFLICT_PREFIX}{doc_type}.{source_field}"


def worksheet_conflict_field_key(mapping_key: str) -> str:
    return f"{DS260_CONFLICT_PREFIX}{WORKSHEET_CONFLICT_SEGMENT}.{mapping_key}"


def ds260_manual_field_key(mapping_key: str, member_id: str | None = None) -> str:
    if member_id:
        return f"{DS260_CONFLICT_PREFIX}{DS260_MANUAL_SEGMENT}.{member_id}.{mapping_key}"
    return f"{DS260_CONFLICT_PREFIX}{DS260_MANUAL_SEGMENT}.{mapping_key}"


def is_ds260_manual_field_key(field_key: str) -> bool:
    return field_key.startswith(f"{DS260_CONFLICT_PREFIX}{DS260_MANUAL_SEGMENT}.")


def is_ds260_conflict_field(field_key: str) -> bool:
    return field_key.startswith(DS260_CONFLICT_PREFIX) and not is_ds260_manual_field_key(field_key)


def conflict_type_from_field_key(field_key: str) -> str:
    if f".{WORKSHEET_CONFLICT_SEGMENT}." in field_key:
        return "document_vs_worksheet"
    return "document_vs_exception"


def parse_ds260_conflict_key(field_key: str) -> tuple[str, str] | None:
    if not is_ds260_conflict_field(field_key):
        return None
    rest = field_key[len(DS260_CONFLICT_PREFIX) :]
    if rest.startswith(f"{WORKSHEET_CONFLICT_SEGMENT}."):
        return WORKSHEET_CONFLICT_SEGMENT, rest[len(WORKSHEET_CONFLICT_SEGMENT) + 1 :]
    doc_type, _, source_field = rest.partition(".")
    if doc_type and source_field:
        return doc_type, source_field
    return None


def _norm_value(val: str) -> str:
    return re.sub(r"\s+", " ", (val or "").strip().upper())


def _norm_gender(val: str) -> str:
    u = _norm_value(val)
    if u in {"M", "MALE", "NAM"}:
        return "MALE"
    if u in {"F", "FEMALE", "NU", "NỮ"}:
        return "FEMALE"
    return u


def norm_conflict_value(mapping_key: str, val: str) -> str:
    """Normalize for comparison — dates to ISO, gender canonical, else uppercase trim."""
    if not (val or "").strip():
        return ""
    if mapping_key in _DATE_COMPARE_KEYS:
        from app.services.ds260_dates import parse_full_date

        parsed = parse_full_date(val)
        if parsed:
            return parsed.isoformat()
    if mapping_key == "gender":
        return _norm_gender(val)
    return _norm_value(val)


def pick_latest_by_variant(
    records: list[ApplicantDocRecord],
    doc_type: str,
    variant: str,
) -> ApplicantDocRecord | None:
    typed = [r for r in records if r.doc_type == doc_type and r.variant == variant]
    if not typed:
        return None
    return max(typed, key=lambda r: (r.updated_at or r.id, str(r.id)))


async def load_ds260_manual_overrides(
    db: AsyncSession, applicant_id, *, member_id=None
) -> dict[str, str]:
    """DS-260 mapping key → giá trị chỉnh tay (Review trước export)."""
    prefix = f"{DS260_CONFLICT_PREFIX}{DS260_MANUAL_SEGMENT}."
    result = await db.execute(
        select(ProfileField).where(
            ProfileField.applicant_id == applicant_id,
            ProfileField.field_key.like(f"{prefix}%"),
            ProfileField.is_manual.is_(True),
        )
    )
    member_prefix = f"{prefix}{member_id}." if member_id else None
    legacy_prefix = prefix if member_id else None
    out: dict[str, str] = {}
    for pf in result.scalars():
        val = (pf.field_value or "").strip()
        if not val:
            continue
        key = pf.field_key
        if member_prefix and key.startswith(member_prefix):
            mapping_key = key[len(member_prefix) :]
            if mapping_key:
                out[mapping_key] = val
        elif legacy_prefix and member_id is None and key.startswith(legacy_prefix):
            mapping_key = key[len(legacy_prefix) :]
            if mapping_key and "." not in mapping_key:
                out[mapping_key] = val
        elif not member_id and key.startswith(prefix):
            mapping_key = key[len(prefix) :]
            if mapping_key and "." not in mapping_key:
                out[mapping_key] = val
    return out


def apply_ds260_manual_overrides(
    sections_out: list[dict[str, Any]],
    overrides: dict[str, str],
) -> None:
    if not overrides:
        return
    for sec in sections_out:
        for field in sec.get("fields", []):
            key = field.get("key", "")
            if key not in overrides:
                continue
            field["value"] = overrides[key]
            source = field.setdefault("source", {})
            source["derived"] = "manual_override"


def _mapping_keys_for_document_field(doc_type: str, source_field: str) -> list[str]:
    """OCR field trên giấy tờ → các field key DS-260 dùng nguồn đó."""
    from app.services.ds260_mapping import flatten_ds260_mappings

    keys: list[str] = []
    for mkey, mapping in flatten_ds260_mappings().items():
        if mapping.document != doc_type:
            continue
        if mapping.field == source_field or mkey == source_field:
            keys.append(mkey)
            continue
        if source_field in (mapping.aliases or ()):
            keys.append(mkey)
    return keys


def apply_ds260_resolved_conflicts(
    sections_out: list[dict[str, Any]],
    resolutions: dict[str, str],
    *,
    person_name: str = "",
    member_role: str | None = None,
) -> None:
    """
    Áp giá trị user đã chọn khi giải quyết xung đột — sau enrich, trước chỉnh tay.

    Ưu tiên cao hơn OCR/enrich mặc định; thấp hơn manual_override.
    Bộ hồ sơ gia đình: worksheet conflict chỉ áp chủ hồ sơ / khi tên khớp thành viên.
    """
    if not resolutions:
        return

    from app.services.ds260_mapping import _names_same_person, flatten_ds260_mappings

    mappings = flatten_ds260_mappings()
    chosen_by_field: dict[str, tuple[str, str]] = {}

    for fk, chosen in resolutions.items():
        val = (chosen or "").strip()
        if not val:
            continue
        parsed = parse_ds260_conflict_key(fk)
        if not parsed:
            continue
        seg, suffix = parsed
        if seg not in LUONG1_DOC_TYPES:
            continue
        for mkey in _mapping_keys_for_document_field(seg, suffix):
            chosen_by_field[mkey] = (val, "conflict_resolution")

    identity_keys = frozenset({"applicant_name", "date_of_birth", "passport_number", "gender"})
    for fk, chosen in resolutions.items():
        val = (chosen or "").strip()
        if not val:
            continue
        parsed = parse_ds260_conflict_key(fk)
        if not parsed:
            continue
        seg, suffix = parsed
        if seg == WORKSHEET_CONFLICT_SEGMENT and suffix in mappings:
            if member_role == "child":
                continue
            if (
                suffix in identity_keys
                and person_name
                and not _names_same_person(val, person_name)
            ):
                continue
            chosen_by_field[suffix] = (val, "worksheet_conflict_resolution")

    for sec in sections_out:
        for field in sec.get("fields", []):
            key = field.get("key", "")
            if key not in chosen_by_field:
                continue
            val, derived = chosen_by_field[key]
            field["value"] = val
            src = field.setdefault("source", {})
            src["derived"] = derived


async def load_ds260_field_resolutions(db: AsyncSession, applicant_id) -> dict[str, str]:
    """field_key ds260.* → resolved_value (chỉ conflict đã giải quyết)."""
    result = await db.execute(
        select(Conflict).where(
            Conflict.applicant_id == applicant_id,
            Conflict.field_key.like(f"{DS260_CONFLICT_PREFIX}%"),
            Conflict.status == ConflictStatus.resolved,
        )
    )
    out: dict[str, str] = {}
    for c in result.scalars():
        if c.resolved_value:
            out[c.field_key] = c.resolved_value.strip()
    return out


async def list_open_ds260_conflicts(db: AsyncSession, applicant_id) -> list[Conflict]:
    result = await db.execute(
        select(Conflict).where(
            Conflict.applicant_id == applicant_id,
            Conflict.field_key.like(f"{DS260_CONFLICT_PREFIX}%"),
            Conflict.status == ConflictStatus.open,
        )
    )
    return list(result.scalars())


async def count_open_ds260_conflicts(db: AsyncSession, applicant_id) -> int:
    conflicts = await list_open_ds260_conflicts(db, applicant_id)
    return len(conflicts)


def _form_dict(rec: ApplicantDocRecord) -> dict[str, str]:
    try:
        data = json.loads(rec.form_data or "{}")
    except json.JSONDecodeError:
        return {}
    return {k: str(v).strip() for k, v in data.items() if v is not None and str(v).strip()}


def _strict_field_value(
    rec: ApplicantDocRecord | None,
    mapping_key: str,
) -> tuple[str, str]:
    """Chỉ key/field/aliases — không loose match (tránh nhầm gender ↔ date_of_birth)."""
    from app.services.ds260_mapping import (
        _effective_aliases,
        _resolve_from_record,
        flatten_ds260_mappings,
    )

    mapping = flatten_ds260_mappings().get(mapping_key)
    if not mapping or not rec:
        return "", mapping_key

    aliases = _effective_aliases(mapping)
    if mapping.key != mapping.field:
        val = _resolve_from_record(rec, mapping.key, ())
        if val.strip():
            return val, mapping.key
    val = _resolve_from_record(rec, mapping.field, aliases)
    if val.strip():
        return val, mapping.field
    return "", mapping.field


def _official_value_for_worksheet_compare(
    records: list[ApplicantDocRecord],
    mapping_key: str,
    resolutions: dict[str, str],
) -> tuple[str, ApplicantDocRecord | None]:
    """Giá trị từ giấy tờ chính thức (Luồng 1 resolved) — strict field match only."""
    from app.services.ds260_mapping import flatten_ds260_mappings, pick_latest_record

    mapping = flatten_ds260_mappings().get(mapping_key)
    if not mapping:
        return "", None

    doc_type = WORKSHEET_OFFICIAL_DOC_OVERRIDES.get(mapping_key, mapping.document)
    standard = pick_latest_by_variant(records, doc_type, "standard")
    reference = pick_latest_by_variant(records, doc_type, "exception")

    conflict_keys = (
        ds260_conflict_field_key(doc_type, mapping.field),
        ds260_conflict_field_key(doc_type, mapping.key),
    )
    for ck in conflict_keys:
        chosen = (resolutions.get(ck) or "").strip()
        if not chosen:
            continue
        for rec in (standard, reference):
            if not rec:
                continue
            val, _ = _strict_field_value(rec, mapping_key)
            if val.strip() and norm_conflict_value(mapping_key, val) == norm_conflict_value(mapping_key, chosen):
                return val, rec
        return chosen, standard or reference

    for rec in (standard, reference):
        if not rec:
            continue
        val, _ = _strict_field_value(rec, mapping_key)
        if val.strip():
            return val, rec

    rec = pick_latest_record(records, doc_type)
    if rec:
        val, _ = _strict_field_value(rec, mapping_key)
        return val, rec
    return "", None


def _worksheet_value(
    records: list[ApplicantDocRecord],
    mapping_key: str,
) -> tuple[str, ApplicantDocRecord | None]:
    from app.services.ds260_mapping import pick_latest_record

    ds260_rec = pick_latest_by_variant(records, "ds260_customer_form", "exception") or pick_latest_record(
        records, "ds260_customer_form"
    )
    if not ds260_rec:
        return "", None
    val, _ = _strict_field_value(ds260_rec, mapping_key)
    return val, ds260_rec


def build_worksheet_conflict_rows(
    records: list[ApplicantDocRecord],
    resolutions: dict[str, str],
) -> list[dict[str, Any]]:
    """Detect document_vs_worksheet conflicts (pure — for tests and sync)."""
    ds260_present = any(r.doc_type == "ds260_customer_form" for r in records)
    if not ds260_present:
        return []

    rows: list[dict[str, Any]] = []
    for mapping_key in sorted(WORKSHEET_COMPARE_KEYS):
        fk = worksheet_conflict_field_key(mapping_key)
        if fk in resolutions:
            continue

        official_val, official_rec = _official_value_for_worksheet_compare(records, mapping_key, resolutions)
        worksheet_val, worksheet_rec = _worksheet_value(records, mapping_key)
        if not official_val.strip() or not worksheet_val.strip():
            continue
        if norm_conflict_value(mapping_key, official_val) == norm_conflict_value(mapping_key, worksheet_val):
            continue

        rows.append(
            {
                "field_key": fk,
                "value_a": official_val,
                "document_a_id": official_rec.source_document_id if official_rec else None,
                "value_b": worksheet_val,
                "document_b_id": worksheet_rec.source_document_id if worksheet_rec else None,
            }
        )
    return rows


def _sync_document_exception_conflicts(
    records: list[ApplicantDocRecord],
    resolutions: dict[str, str],
    applicant_id,
) -> list[Conflict]:
    created: list[Conflict] = []
    for doc_type in LUONG1_DOC_TYPES:
        standard = pick_latest_by_variant(records, doc_type, "standard")
        reference = pick_latest_by_variant(records, doc_type, "exception")
        if not standard or not reference:
            continue

        std_form = _form_dict(standard)
        ref_form = _form_dict(reference)
        for key in set(std_form) | set(ref_form):
            val_a = std_form.get(key, "")
            val_b = ref_form.get(key, "")
            if not val_a or not val_b:
                continue
            if _norm_value(val_a) == _norm_value(val_b):
                continue

            fk = ds260_conflict_field_key(doc_type, key)
            if fk in resolutions:
                continue

            created.append(
                Conflict(
                    applicant_id=applicant_id,
                    field_key=fk,
                    value_a=val_a,
                    document_a_id=standard.source_document_id,
                    value_b=val_b,
                    document_b_id=reference.source_document_id,
                    status=ConflictStatus.open,
                )
            )
    return created


async def sync_ds260_doc_conflicts(db: AsyncSession, applicant_id) -> int:
    """
    So sánh:
    1) Luồng 1 (standard) vs đối chiếu (exception) — document_vs_exception
    2) Giá trị Luồng 1 đã resolve vs ds260_customer_form — document_vs_worksheet

    Tạo / cập nhật Conflict mở; giữ conflict đã resolved.
    """
    records = await list_doc_records(db, applicant_id)
    resolutions = await load_ds260_field_resolutions(db, applicant_id)

    open_result = await db.execute(
        select(Conflict).where(
            Conflict.applicant_id == applicant_id,
            Conflict.field_key.like(f"{DS260_CONFLICT_PREFIX}%"),
            Conflict.status == ConflictStatus.open,
        )
    )
    for old in open_result.scalars():
        await db.delete(old)

    created = 0
    for conflict in _sync_document_exception_conflicts(records, resolutions, applicant_id):
        db.add(conflict)
        created += 1

    for row in build_worksheet_conflict_rows(records, resolutions):
        db.add(
            Conflict(
                applicant_id=applicant_id,
                field_key=row["field_key"],
                value_a=row["value_a"],
                document_a_id=row["document_a_id"],
                value_b=row["value_b"],
                document_b_id=row["document_b_id"],
                status=ConflictStatus.open,
            )
        )
        created += 1

    await db.flush()
    return created


def conflict_label_vi(field_key: str) -> str:
    parsed = parse_ds260_conflict_key(field_key)
    if not parsed:
        return field_key
    kind, name = parsed
    if kind == WORKSHEET_CONFLICT_SEGMENT:
        labels = {
            "applicant_name": "Họ và tên",
            "date_of_birth": "Ngày sinh",
            "gender": "Giới tính",
            "nationality": "Quốc tịch",
            "place_of_birth": "Nơi sinh",
            "passport_number": "Số hộ chiếu",
            "passport_issue_date": "Ngày cấp hộ chiếu",
            "passport_expiration_date": "Ngày hết hạn hộ chiếu",
            "current_marital_status": "Tình trạng hôn nhân",
            "current_address": "Địa chỉ hiện tại",
            "primary_phone": "Số điện thoại",
            "email": "Email",
        }
        return f"DS-260 worksheet · {labels.get(name, name)}"
    doc_type, source_field = kind, name
    doc_labels = {
        "passport": "Passport",
        "birth_certificate": "Birth certificate",
        "judicial_certificate": "JUDICIAL CERTIFICATE",
        "marriage_certificate": "Marriage certificate",
    }
    return f"{doc_labels.get(doc_type, doc_type)} · {source_field}"
