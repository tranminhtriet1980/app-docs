"""
DS260 mapping: mỗi field DS260 → document_type + source_field.

Fill logic:
  value = documents[document_type][source_field]

Luồng 1 (passport, birth_certificate, judicial_certificate, marriage_certificate):
  - Mặc định lấy từ bản standard (file mẫu).
  - Trường thiếu → lấy từ bản đối chiếu khách upload (_new / exception).
  - Hai bản khác nhau có giá trị → xung đột; user chọn khi đối chiếu.

Không merge field cùng tên giữa passport / birth_certificate / ...
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Applicant, ApplicantDocRecord, ProfileField
from app.services.birth_location import (
    derive_birth_state_from_place,
    derive_city_from_place,
    derive_country_from_place,
)
from app.services.doc_record_sync import list_doc_records
from app.services.ds260_dates import format_partial_ds260_date, parse_full_date
from app.services.document_registry import (
    BIRTH_CERT_CANONICAL_ALIASES,
    RECORDABLE_REGISTRY_BY_CODE,
    REGISTRY_BY_CODE,
    normalize_birth_certificate_raw,
)

MAPPING_PATH = Path(__file__).resolve().parents[2] / "data" / "doc_schemas" / "ds260_mapping.json"

# DS-260 mục 3–5 (địa chỉ, liên lạc, MXH) — form khách khai
CUSTOMER_FORM_DOC_TYPES: frozenset[str] = frozenset(
    {"ds260_customer_form", "address_document", "other", "financial", "employment_letter"}
)


@dataclass(frozen=True)
class Ds260FieldMapping:
    key: str
    label: str
    document: str
    field: str
    aliases: tuple[str, ...] = ()
    derive: str | None = None
    review_hidden: bool = False


@dataclass(frozen=True)
class Ds260Section:
    id: str
    title: str
    subtitle: str
    fields: tuple[Ds260FieldMapping, ...]


@lru_cache(maxsize=1)
def load_ds260_mapping() -> dict[str, Any]:
    with MAPPING_PATH.open(encoding="utf-8") as f:
        return json.load(f)


def load_ds260_sections() -> list[Ds260Section]:
    data = load_ds260_mapping()
    sections: list[Ds260Section] = []
    for sec in data.get("sections", []):
        fields = tuple(
            Ds260FieldMapping(
                key=f["key"],
                label=f["label"],
                document=f["document"],
                field=f["field"],
                aliases=tuple(f.get("aliases") or ()),
                derive=f.get("derive"),
                review_hidden=bool(f.get("review_hidden")),
            )
            for f in sec.get("fields", [])
        )
        sections.append(
            Ds260Section(
                id=sec["id"],
                title=sec["title"],
                subtitle=sec.get("subtitle", ""),
                fields=fields,
            )
        )
    return sections


def _allowed_doc_types_for_field(field_key: str, mapping: Ds260FieldMapping) -> frozenset[str]:
    from app.services.ds260_field_allowed_docs import allowed_doc_types_for_field

    return allowed_doc_types_for_field(field_key, mapping)


def get_field_allowed_docs() -> dict[str, list[str]]:
    from app.services.ds260_field_allowed_docs import field_allowed_docs_public

    return field_allowed_docs_public()


# Public whitelist: field_key → doc types allowed during enrich cross-fill.
FIELD_ALLOWED_DOCS: dict[str, list[str]] = get_field_allowed_docs()


def flatten_ds260_mappings() -> dict[str, Ds260FieldMapping]:
    out: dict[str, Ds260FieldMapping] = {}
    for sec in load_ds260_sections():
        for f in sec.fields:
            out[f.key] = f
    return out



def _resolve_from_record(
    record: ApplicantDocRecord,
    source_field: str,
    aliases: tuple[str, ...],
) -> str:
    form = json.loads(record.form_data or "{}")
    raw = json.loads(record.raw_data or "{}")

    if getattr(record, "doc_type", None) == "birth_certificate":
        raw = normalize_birth_certificate_raw(raw)
        extra = BIRTH_CERT_CANONICAL_ALIASES.get(source_field, ())
        aliases = tuple(dict.fromkeys((*aliases, *extra)))

    if getattr(record, "doc_type", None) == "ds260_customer_form":
        from app.services.ds260_customer_keys import normalize_ds260_customer_raw

        merged: dict[str, str] = {}
        for src in (raw, form):
            for k, v in src.items():
                if v is not None and str(v).strip():
                    merged[k] = str(v).strip()
        merged = normalize_ds260_customer_raw(merged)
        if merged.get(source_field, "").strip():
            return merged[source_field].strip()
        for alias in aliases:
            if merged.get(alias, "").strip():
                return merged[alias].strip()
        eff = (source_field, *aliases, *((source_field,) if source_field not in aliases else ()))
        for alias in dict.fromkeys(eff):
            if merged.get(alias, "").strip():
                return merged[alias].strip()
        return ""

    if form.get(source_field, "").strip():
        return form[source_field].strip()
    if raw.get(source_field, "").strip():
        return raw[source_field].strip()
    for alias in aliases:
        if form.get(alias, "").strip():
            return form[alias].strip()
        if raw.get(alias, "").strip():
            return raw[alias].strip()
    return ""


def _effective_aliases(mapping: Ds260FieldMapping) -> tuple[str, ...]:
    """Alias gồm key DS-260 (form khách upload) + aliases cấu hình."""
    if mapping.key == mapping.field:
        return mapping.aliases
    return tuple(dict.fromkeys((mapping.key, *mapping.aliases)))


_EMPTY_FALLBACK_MARKERS = frozenset(
    {
        "",
        "n/a",
        "na",
        "none",
        "unknown",
        "-",
        "--",
        "...",
        "null",
        "nil",
    }
)


def _is_empty_for_fallback(val: str) -> bool:
    """Coi là thiếu — cho phép lấy từ bản đối chiếu _new."""
    s = (val or "").strip()
    if not s:
        return True
    if s.lower() in _EMPTY_FALLBACK_MARKERS or s.lower() in _PARENT_NA_MARKERS:
        return True
    if re.fullmatch(r"[\s_\-.·…\-]+", s):
        return True
    return False


def _direct_ds260_value(
    record: ApplicantDocRecord | None,
    mapping: Ds260FieldMapping,
) -> tuple[str, str]:
    """Đọc trực tiếp — ưu tiên key DS-260 (vd. applicant_name, passport_issue_date)."""
    if not record:
        return "", mapping.field
    aliases = _effective_aliases(mapping)
    if mapping.key != mapping.field:
        val = _resolve_from_record(record, mapping.key, ())
        if val.strip():
            return val, mapping.key
    val = _resolve_from_record(record, mapping.field, aliases)
    if val.strip():
        return val, mapping.field
    loose, lk = _resolve_loose_from_record(record, mapping)
    if loose.strip():
        return loose, lk
    return "", mapping.field


def _norm_field_key(key: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (key or "").lower())


def _lookup_keys_for_mapping(mapping: Ds260FieldMapping) -> tuple[str, ...]:
    keys = [mapping.field, mapping.key, *_effective_aliases(mapping)]
    try:
        from app.services.field_mapping import CONTACT_AND_SOCIAL_MAP, FIELD_MAP

        for extract_key, profile_key in CONTACT_AND_SOCIAL_MAP.items():
            if extract_key in keys or profile_key.replace("contact.", "").replace("social.", "") in (
                mapping.key,
                mapping.field,
            ):
                keys.extend((extract_key, profile_key))
        for fmap in FIELD_MAP.values():
            for extract_key, profile_key in fmap.items():
                if extract_key in keys or profile_key in keys:
                    keys.extend((extract_key, profile_key))
    except ImportError:
        pass
    return tuple(dict.fromkeys(k for k in keys if k))


def _merged_record_data(record: ApplicantDocRecord) -> dict[str, str]:
    form = json.loads(record.form_data or "{}")
    raw = json.loads(record.raw_data or "{}")
    if record.doc_type == "birth_certificate":
        raw = normalize_birth_certificate_raw(raw)
    merged: dict[str, str] = {}
    for src in (form, raw):
        for k, v in src.items():
            if v is None:
                continue
            s = str(v).strip()
            if s and k not in merged:
                merged[k] = s
    return merged


def _resolve_loose_from_record(
    record: ApplicantDocRecord,
    mapping: Ds260FieldMapping,
) -> tuple[str, str]:
    """Quét mọi key OCR — khớp tên trường DS-260 / profile (contact.phone_primary, …)."""
    merged = _merged_record_data(record)
    if not merged:
        return "", mapping.field
    norms = {_norm_field_key(k): k for k in _lookup_keys_for_mapping(mapping)}
    for raw_key, val in merged.items():
        nk = _norm_field_key(raw_key)
        if nk in norms:
            return val, raw_key
    target = _norm_field_key(mapping.key)
    field_n = _norm_field_key(mapping.field)
    for raw_key, val in merged.items():
        nk = _norm_field_key(raw_key)
        if target and (nk == target or nk.endswith(target) or target in nk):
            return val, raw_key
        if field_n and field_n != target and (nk == field_n or nk.endswith(field_n)):
            return val, raw_key
    return "", mapping.field


def _record_fill_priority(rec: ApplicantDocRecord, mapping: Ds260FieldMapping) -> tuple:
    """
    Thứ tự ưu tiên cross-fill (tier thấp = ưu tiên cao):

    0. Cùng doc_type + standard (Luồng 1 mẫu)
    1. Cùng doc_type + exception (_new)
    2. Luồng 1 khác loại + exception
    3. Luồng 1 khác loại + standard
    4. ds260_customer_form (worksheet khách khai)
    5. Form khách bổ sung khác (address_document, …)
    6. Fallback (mọi nguồn còn lại)

    Giấy tờ chính thức luôn thắng dữ liệu worksheet DS-260.
    """
    from app.services.ds260_conflicts import LUONG1_DOC_TYPES

    same_doc = rec.doc_type == mapping.document
    is_luong1 = rec.doc_type in LUONG1_DOC_TYPES
    is_ds260 = rec.doc_type == "ds260_customer_form"
    is_supplemental = rec.doc_type in CUSTOMER_FORM_DOC_TYPES and not is_ds260

    if same_doc and rec.variant == "standard":
        tier = 0
    elif same_doc and rec.variant == "exception":
        tier = 1
    elif not same_doc and is_luong1 and rec.variant == "exception":
        tier = 2
    elif not same_doc and is_luong1 and rec.variant == "standard":
        tier = 3
    elif is_ds260:
        tier = 4
    elif is_supplemental:
        tier = 5
    else:
        tier = 6

    return (tier, str(rec.updated_at or rec.id))


def _resolve_field_from_record(
    record: ApplicantDocRecord,
    mapping: Ds260FieldMapping,
) -> tuple[str, str]:
    val, sf = _resolve_ds260_field_value(mapping, record)
    if not _is_empty_for_fallback(val):
        return val, sf
    return _resolve_loose_from_record(record, mapping)


def _split_vn_person_name(full_name: str) -> tuple[str, str]:
    parts = [p for p in (full_name or "").strip().split() if p]
    if len(parts) >= 2:
        return parts[0], " ".join(parts[1:])
    if parts:
        return parts[0], ""
    return "", ""


_PARENT_NA_MARKERS = frozenset({"n/a", "na", "none", "unknown", "khong", "không"})

_PARENT_BIRTH_CERT_CONFIG: dict[str, dict[str, Any]] = {
    "father": {
        "section_id": "section_father",
        "surname_key": "father_surname",
        "absent_derived": "no_father_na",
        "section_keys": frozenset(
            {
                "father_surname",
                "father_given_names",
                "father_date_of_birth",
                "father_birth_city",
                "father_birth_state",
                "father_birth_country",
                "father_full_name",
            }
        ),
        "info_fields": (
            ("father_surname", ("father_family_name", "father_last_name")),
            ("father_given_names", ("father_first_name", "father_given_name")),
            ("father_name", ("father_full_name",)),
            ("father_date_of_birth", ("father_dob", "father_birth_date")),
            ("father_birth_city", ("father_city_of_birth",)),
            ("father_place_of_birth", ("father_birth_place",)),
            ("father_birth_state", ()),
            ("father_birth_country", ("father_country",)),
        ),
    },
    "mother": {
        "section_id": "section_mother",
        "surname_key": "mother_surname",
        "absent_derived": "no_mother_na",
        "section_keys": frozenset(
            {
                "mother_surname",
                "mother_given_names",
                "mother_date_of_birth",
                "mother_birth_city",
                "mother_birth_state",
                "mother_birth_country",
                "mother_full_name",
            }
        ),
        "info_fields": (
            ("mother_surname", ("mother_family_name", "mother_last_name")),
            ("mother_given_names", ("mother_first_name", "mother_given_name")),
            ("mother_name", ("mother_full_name",)),
            ("mother_date_of_birth", ("mother_dob", "mother_birth_date")),
            ("mother_birth_city", ("mother_city_of_birth",)),
            ("mother_place_of_birth", ("mother_birth_place",)),
            ("mother_birth_state", ()),
            ("mother_birth_country", ("mother_country",)),
        ),
    },
}


def _is_meaningful_parent_value(value: str) -> bool:
    v = (value or "").strip().lower()
    if not v:
        return False
    if v in _PARENT_NA_MARKERS:
        return False
    if v.replace("/", "").replace(".", "").strip() == "na":
        return False
    return True


def has_parent_info_on_birth_cert(record: ApplicantDocRecord | None, parent: str) -> bool:
    """True nếu giấy khai sinh có thông tin cha/mẹ (OCR/form)."""
    if not record:
        return False
    cfg = _PARENT_BIRTH_CERT_CONFIG[parent]
    for field, aliases in cfg["info_fields"]:
        if _is_meaningful_parent_value(_resolve_from_record(record, field, aliases)):
            return True
    return False


def has_father_info_on_birth_cert(record: ApplicantDocRecord | None) -> bool:
    return has_parent_info_on_birth_cert(record, "father")


def has_mother_info_on_birth_cert(record: ApplicantDocRecord | None) -> bool:
    return has_parent_info_on_birth_cert(record, "mother")


def apply_parent_absent_rule(fields_out: list[dict[str, Any]], parent: str) -> None:
    """
    Giấy khai sinh không có thông tin cha/mẹ:
    - Surnames (HỌ) → N/A
    - Các trường khác → để trống
    """
    cfg = _PARENT_BIRTH_CERT_CONFIG[parent]
    surname_key = cfg["surname_key"]
    section_keys = cfg["section_keys"]
    for field in fields_out:
        key = field.get("key", "")
        if key not in section_keys:
            continue
        if key == surname_key:
            field["value"] = "N/A"
            field["source"]["derived"] = cfg["absent_derived"]
            field["source"]["source_field"] = "birth_certificate"
        else:
            field["value"] = ""


def apply_father_absent_rule(fields_out: list[dict[str, Any]]) -> None:
    apply_parent_absent_rule(fields_out, "father")


def apply_mother_absent_rule(fields_out: list[dict[str, Any]]) -> None:
    apply_parent_absent_rule(fields_out, "mother")


def enrich_parent_is_living(
    fields_out: list[dict[str, Any]],
    bc_rec: ApplicantDocRecord | None,
    parent: str,
) -> None:
    """Có thông tin cha/mẹ trên giấy khai sinh → Còn sống: Yes; không có thông tin → để trống."""
    if not bc_rec or not has_parent_info_on_birth_cert(bc_rec, parent):
        return
    key = f"{parent}_is_living"
    for field in fields_out:
        if field.get("key") != key:
            continue
        field["value"] = "Yes"
        field.setdefault("source", {})
        field["source"]["document_type"] = "birth_certificate"
        field["source"]["source_field"] = key
        field["source"]["derived"] = f"{parent}_living_from_birth_cert"


def _year_from_death_date(val: str) -> str:
    from app.services.ds260_dates import format_partial_ds260_date, parse_full_date

    v = (val or "").strip()
    if not v:
        return ""
    if re.match(r"^\d{4}$", v):
        return v
    d = parse_full_date(v)
    if d:
        return str(d.year)
    partial = format_partial_ds260_date(v)
    if partial and partial.isdigit() and len(partial) == 4:
        return partial
    m = re.search(r"(19|20)\d{2}", v)
    return m.group(0) if m else ""


def enrich_parent_death_from_death_cert(
    fields_out: list[dict[str, Any]],
    death_rec: ApplicantDocRecord | None,
    parent: str,
    parent_full_name: str,
) -> None:
    """Giấy báo tử → năm mất cha/mẹ + is_living = No."""
    if not death_rec or not parent_full_name:
        return
    merged = _merge_raw_dict(death_rec)
    deceased = (merged.get("deceased_full_name") or merged.get("full_name") or "").strip()
    rel = (merged.get("relationship_to_applicant") or "").strip().lower()
    if not _names_match(deceased, parent_full_name) and parent not in rel:
        return
    year = _year_from_death_date(merged.get("date_of_death", ""))
    death_key = f"{parent}_death_year"
    living_key = f"{parent}_is_living"
    for field in fields_out:
        key = field.get("key", "")
        if key == death_key and not (field.get("value") or "").strip() and year:
            field["value"] = year
            field["source"] = {
                "document_type": "death_certificate",
                "source_field": "date_of_death",
                "record_id": str(death_rec.id),
                "derived": f"{parent}_death_from_cert",
            }
        if key == living_key and not (field.get("value") or "").strip():
            field["value"] = "No"
            field["source"] = {
                "document_type": "death_certificate",
                "source_field": "date_of_death",
                "record_id": str(death_rec.id),
                "derived": f"{parent}_not_living_from_death_cert",
            }


def _normalize_person_name_key(name: str) -> str:
    from app.services.birth_location import normalize_location

    return normalize_location(name)


def _names_match(a: str, b: str) -> bool:
    na = _normalize_person_name_key(a)
    nb = _normalize_person_name_key(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    pa = [p for p in na.split() if len(p) > 1]
    pb = [p for p in nb.split() if len(p) > 1]
    if pa and pb and pa[0] == pb[0]:
        return True
    return False


def _names_same_person(a: str, b: str) -> bool:
    """Khớp họ tên đầy đủ — không coi trùng mỗi họ là cùng một người."""
    na = _normalize_person_name_key(a)
    nb = _normalize_person_name_key(b)
    if not na or not nb:
        return False
    return na == nb or na in nb or nb in na


def _pick_spouse_side_from_marriage(
    marriage_rec: ApplicantDocRecord,
    passport_rec: ApplicantDocRecord | None,
    passport_ref: ApplicantDocRecord | None = None,
) -> str:
    """Trả 'husband' hoặc 'wife' — phía còn lại so với chủ hồ sơ trên giấy kết hôn."""
    husband = _resolve_from_record(
        marriage_rec, "husband_full_name", ("husband_name", "husband_full_name")
    )
    wife = _resolve_from_record(marriage_rec, "wife_full_name", ("wife_name", "wife_full_name"))
    applicant = _resolve_from_record_luong1_fallback(
        passport_rec, passport_ref, "full_name", ("name",)
    )
    gender = _resolve_from_record_luong1_fallback(
        passport_rec, passport_ref, "gender", ("sex",)
    ).upper()

    if applicant and husband and _names_match(applicant, husband):
        return "wife"
    if applicant and wife and _names_match(applicant, wife):
        return "husband"
    return ""


def has_applicable_marriage_certificate(
    marriage_rec: ApplicantDocRecord | None,
    marriage_ref: ApplicantDocRecord | None,
    passport_rec: ApplicantDocRecord | None,
    passport_ref: ApplicantDocRecord | None,
) -> bool:
    """Giấy kết hôn chỉ áp dụng khi chủ hồ sơ là một trong hai bên trên giấy."""
    primary = marriage_rec or marriage_ref
    if not primary:
        return False
    return bool(_pick_spouse_side_from_marriage(primary, passport_rec, passport_ref))


@lru_cache(maxsize=1)
def _spouse_section_field_keys() -> frozenset[str]:
    keys: set[str] = set()
    for sec in load_ds260_sections():
        if sec.id == "section_spouse":
            keys.update(f.key for f in sec.fields)
    return frozenset(keys)


def empty_ds260_field_source() -> dict[str, Any]:
    """Source metadata hợp lệ khi trường trống — tránh lỗi validate API."""
    return {
        "document_type": "",
        "source_field": "",
        "document_id": None,
        "document_filename": None,
        "variant": None,
        "record_id": None,
    }


def clear_spouse_section_fields(fields_out: list[dict[str, Any]]) -> None:
    """Xóa toàn bộ trường phối ngẫu khi không có giấy kết hôn hợp lệ."""
    allowed = _spouse_section_field_keys()
    for field in fields_out:
        if field.get("key", "") in allowed:
            field["value"] = ""
            field["source"] = empty_ds260_field_source()


@lru_cache(maxsize=1)
def _child_excluded_section_ids() -> frozenset[str]:
    """Các mục DS-260 không áp dụng cho hồ sơ con (chỉ người lớn)."""
    return frozenset({
        "section_spouse",
        "section_divorce",
        "section_previous_spouse",
        "section_children",
    })


@lru_cache(maxsize=1)
def _child_own_birth_cert_section_ids() -> frozenset[str]:
    """Hồ sơ con — cha/mẹ/GKS lấy từ birth_certificate_child của chính con."""
    return frozenset({"section_father", "section_mother", "section_birth_certificate"})


def clear_child_adult_only_ds260_sections(sections_out: list[dict[str, Any]]) -> None:
    """Hồ sơ con — không điền phối ngẫu, ly hôn, danh sách con, tình trạng hôn nhân."""
    excluded = _child_excluded_section_ids()
    for sec in sections_out:
        if sec["id"] in excluded:
            for field in sec["fields"]:
                field["value"] = ""
                field["source"] = empty_ds260_field_source()
        elif sec["id"] == "section_a_personal":
            for field in sec["fields"]:
                if field.get("key") == "current_marital_status":
                    field["value"] = ""
                    field["source"] = empty_ds260_field_source()


def _spouse_name_from_marriage(
    marriage_rec: ApplicantDocRecord,
    passport_rec: ApplicantDocRecord | None,
) -> str:
    side = _pick_spouse_side_from_marriage(marriage_rec, passport_rec)
    if not side:
        return ""
    spouse_name = _resolve_from_record(
        marriage_rec,
        f"{side}_full_name",
        (f"{side}_name", "spouse_full_name", "spouse_name"),
    )
    if not spouse_name:
        spouse_name = _resolve_from_record(
            marriage_rec,
            "wife_full_name" if side == "wife" else "husband_full_name",
            ("wife_name", "husband_name"),
        )
    return spouse_name


def _occupation_from_profile_map(profile: dict[str, str]) -> dict[str, str]:
    occupation = (profile.get("employment.primary_occupation") or "").strip()
    other = (profile.get("employment.occupation_other_specify") or "").strip()
    out: dict[str, str] = {}
    if occupation:
        out["spouse_occupation"] = occupation
    if other:
        out["spouse_occupation_other"] = other
    return out


def _occupation_from_employment_record(rec: ApplicantDocRecord | None) -> dict[str, str]:
    if not rec:
        return {}
    occupation = _resolve_from_record(rec, "primary_occupation", ("job_title",))
    other = _resolve_from_record(rec, "occupation_other_specify", ())
    out: dict[str, str] = {}
    if occupation:
        out["spouse_occupation"] = occupation
    if other:
        out["spouse_occupation_other"] = other
    return out


def _merge_occupation_fields(*sources: dict[str, str]) -> dict[str, str]:
    merged: dict[str, str] = {}
    for src in sources:
        for key, val in src.items():
            if val and not merged.get(key):
                merged[key] = val
    return merged


def pick_applicant_by_spouse_name(
    candidates: list[Applicant],
    spouse_name: str,
    passport_names: dict[str, str],
) -> Applicant | None:
    if not spouse_name:
        return None
    for cand in candidates:
        if _names_same_person(cand.display_name or "", spouse_name):
            return cand
    for cand in candidates:
        pp_name = passport_names.get(str(cand.id), "")
        if pp_name and _names_same_person(pp_name, spouse_name):
            return cand
    return None


async def find_spouse_applicant(
    db: AsyncSession,
    current: Applicant,
    marriage_rec: ApplicantDocRecord | None,
    passport_rec: ApplicantDocRecord | None,
) -> Applicant | None:
    """Hồ sơ applicant của phối ngẫu (cùng user / dự án, khớp tên trên giấy kết hôn)."""
    if not marriage_rec:
        return None
    spouse_name = _spouse_name_from_marriage(marriage_rec, passport_rec)
    if not spouse_name:
        return None

    q = select(Applicant).where(
        Applicant.user_id == current.user_id,
        Applicant.id != current.id,
        Applicant.deleted_at.is_(None),
    )
    if current.project_name:
        q = q.where(Applicant.project_name == current.project_name)
    result = await db.execute(q)
    candidates = list(result.scalars())
    if not candidates:
        return None

    passport_names: dict[str, str] = {}
    for cand in candidates:
        recs = await list_doc_records(db, cand.id)
        pp = pick_latest_record(recs, "passport")
        if pp:
            passport_names[str(cand.id)] = _resolve_from_record(pp, "full_name", ("name",))

    return pick_applicant_by_spouse_name(candidates, spouse_name, passport_names)


async def read_spouse_occupation_from_applicant(
    db: AsyncSession,
    spouse_applicant_id,
) -> dict[str, str]:
    """Nghề nghiệp phối ngẫu từ DS-260 / profile việc làm của hồ sơ vợ hoặc chồng."""
    keys = ("employment.primary_occupation", "employment.occupation_other_specify")
    result = await db.execute(
        select(ProfileField).where(
            ProfileField.applicant_id == spouse_applicant_id,
            ProfileField.field_key.in_(keys),
        )
    )
    profile = {pf.field_key: (pf.field_value or "").strip() for pf in result.scalars()}
    from_profile = _occupation_from_profile_map(profile)

    recs = await list_doc_records(db, spouse_applicant_id)
    emp_rec = pick_latest_record(recs, "employment_letter")
    from_emp = _occupation_from_employment_record(emp_rec)

    return _merge_occupation_fields(from_profile, from_emp)


async def enrich_spouse_occupation_from_spouse_applicant(
    fields_out: list[dict[str, Any]],
    db: AsyncSession,
    current: Applicant,
    marriage_rec: ApplicantDocRecord | None,
    passport_rec: ApplicantDocRecord | None,
) -> None:
    """Chồng khai → lấy nghề nghiệp vợ từ hồ sơ DS-260 của vợ; vợ khai → lấy của chồng."""
    spouse_app = await find_spouse_applicant(db, current, marriage_rec, passport_rec)
    if not spouse_app:
        return

    derived = await read_spouse_occupation_from_applicant(db, spouse_app.id)
    if not derived:
        return

    for field in fields_out:
        key = field.get("key", "")
        val = (derived.get(key) or "").strip()
        if not val:
            continue
        if (field.get("value") or "").strip():
            continue
        field["value"] = val
        field.setdefault("source", {})
        field["source"]["document_type"] = "spouse_applicant_profile"
        field["source"]["source_field"] = (
            "employment.primary_occupation"
            if key == "spouse_occupation"
            else "employment.occupation_other_specify"
        )
        field["source"]["derived"] = "spouse_occupation_from_spouse_ds260"
        field["source"]["spouse_applicant_id"] = str(spouse_app.id)


def _spouse_field_from_marriage(
    marriage_rec: ApplicantDocRecord | None,
    passport_rec: ApplicantDocRecord | None,
    field_suffix: str,
    *,
    full_name: str = "",
    marriage_ref: ApplicantDocRecord | None = None,
    passport_ref: ApplicantDocRecord | None = None,
) -> str:
    primary = marriage_rec or marriage_ref
    if not primary:
        return ""
    side = _pick_spouse_side_from_marriage(primary, passport_rec, passport_ref)
    if not side:
        return ""
    other = "husband" if side == "wife" else "wife"
    keys = (
        f"spouse_{field_suffix}",
        f"{side}_{field_suffix}",
        f"{other}_{field_suffix}",
    )
    for rec in (marriage_rec, marriage_ref):
        if not rec:
            continue
        for key in keys:
            val = _resolve_from_record(rec, key, ())
            if _is_meaningful_parent_value(val):
                return val
    if field_suffix in {"surname", "given_names"} and full_name:
        sur, given = _split_vn_person_name(full_name)
        return sur if field_suffix == "surname" else given
    return ""


def list_birth_certificate_records(records: list[ApplicantDocRecord]) -> list[ApplicantDocRecord]:
    """Tất cả giấy khai sinh — mỗi file một dòng (chủ hồ sơ, vợ/chồng, …)."""
    typed = [r for r in records if r.doc_type == "birth_certificate"]
    return sorted(typed, key=lambda r: (r.updated_at or r.id, str(r.id)))


def _parse_birth_place_city_state(pob: str) -> tuple[str, str]:
    segments = [s.strip() for s in (pob or "").split(",") if s.strip()]
    if len(segments) >= 2:
        state = re.sub(r"(?i)\s+(city|town|province)$", "", segments[-1]).strip()
        city = re.sub(r"(?i)\s+(city|town|province)$", "", segments[-2]).strip()
        return city, state
    if segments:
        city = derive_city_from_place(segments[0]) or segments[0]
        return city, ""
    return "", ""


def _birth_location_from_birth_cert(rec: ApplicantDocRecord) -> dict[str, str]:
    pob = _resolve_from_record(rec, "place_of_birth", ("birth_place",))
    city = _resolve_from_record(rec, "birth_city", ("city_of_birth",))
    state = _resolve_from_record(rec, "birth_state", ("state_of_birth",))
    country = _resolve_from_record(rec, "birth_country", ("country_of_birth",))
    if not city and pob:
        city, parsed_state = _parse_birth_place_city_state(pob)
        if not state:
            state = parsed_state
    elif not state and pob:
        _, state = _parse_birth_place_city_state(pob)
    if not country and pob:
        country = derive_country_from_place(pob) or ""
    return {"birth_city": city, "birth_state": state, "birth_country": country}


def pick_spouse_birth_certificate(
    marriage_rec: ApplicantDocRecord | None,
    passport_rec: ApplicantDocRecord | None,
    birth_certs: list[ApplicantDocRecord],
) -> ApplicantDocRecord | None:
    """Giấy khai sinh của phối ngẫu — không trùng tên chủ hồ sơ trên giấy kết hôn."""
    if not marriage_rec or not birth_certs:
        return None

    side = _pick_spouse_side_from_marriage(marriage_rec, passport_rec)
    if not side:
        return None
    spouse_name = _resolve_from_record(
        marriage_rec,
        f"{side}_full_name",
        (f"{side}_name", "spouse_full_name", "spouse_name"),
    )
    if not spouse_name:
        spouse_name = _resolve_from_record(
            marriage_rec,
            "wife_full_name" if side == "wife" else "husband_full_name",
            ("wife_name", "husband_name"),
        )

    applicant = ""
    if passport_rec:
        applicant = _resolve_from_record(passport_rec, "full_name", ("name",))

    if spouse_name:
        for rec in birth_certs:
            bc_name = _resolve_from_record(rec, "full_name", ("name",))
            if not bc_name:
                continue
            if applicant and _names_same_person(bc_name, applicant):
                continue
            if _names_same_person(bc_name, spouse_name):
                return rec

    fallback: ApplicantDocRecord | None = None
    for rec in birth_certs:
        bc_name = _resolve_from_record(rec, "full_name", ("name",))
        if not bc_name:
            continue
        if applicant and _names_same_person(bc_name, applicant):
            continue
        if spouse_name and _names_same_person(bc_name, spouse_name):
            return rec
        if fallback is None:
            fallback = rec
    return fallback


def enrich_spouse_birth_place_from_birth_certificate(
    fields_out: list[dict[str, Any]],
    marriage_rec: ApplicantDocRecord | None,
    passport_rec: ApplicantDocRecord | None,
    birth_certs: list[ApplicantDocRecord],
) -> None:
    """Nơi sinh phối ngẫu từ giấy khai sinh vợ/chồng (không phải giấy khai sinh chủ hồ sơ)."""
    spouse_bc = pick_spouse_birth_certificate(marriage_rec, passport_rec, birth_certs)
    if not spouse_bc:
        return

    loc = _birth_location_from_birth_cert(spouse_bc)
    derived = {
        "spouse_birth_city": loc["birth_city"],
        "spouse_birth_state": loc["birth_state"],
        "spouse_birth_country": loc["birth_country"],
    }
    dob = _resolve_from_record(spouse_bc, "date_of_birth", ("dob",))
    if dob:
        derived["spouse_date_of_birth"] = dob

    for field in fields_out:
        key = field.get("key", "")
        val = (derived.get(key) or "").strip()
        if not val:
            continue
        if (field.get("value") or "").strip():
            continue
        field["value"] = val
        field.setdefault("source", {})
        field["source"]["document_type"] = "birth_certificate"
        field["source"]["source_field"] = key
        field["source"]["derived"] = "spouse_birth_from_birth_certificate"
        rec_id = getattr(spouse_bc, "id", None)
        if rec_id is not None:
            field["source"]["record_id"] = str(rec_id)


def enrich_spouse_section_from_marriage(
    fields_out: list[dict[str, Any]],
    marriage_rec: ApplicantDocRecord | None,
    passport_rec: ApplicantDocRecord | None,
    *,
    marriage_ref: ApplicantDocRecord | None = None,
    passport_ref: ApplicantDocRecord | None = None,
) -> None:
    """Điền section phối ngẫu từ giấy kết hôn — chọn vợ/chồng không trùng chủ hồ sơ."""
    primary = marriage_rec or marriage_ref
    if not primary:
        return

    side = _pick_spouse_side_from_marriage(primary, passport_rec, passport_ref)
    if not side:
        return
    spouse_full = _resolve_from_record_luong1_fallback(
        marriage_rec,
        marriage_ref,
        f"{side}_full_name",
        (f"{side}_name", "spouse_full_name", "spouse_name"),
    )
    if not spouse_full:
        spouse_full = _resolve_from_record_luong1_fallback(
            marriage_rec,
            marriage_ref,
            "wife_full_name" if side == "wife" else "husband_full_name",
            ("wife_name", "husband_name"),
        )
    if not spouse_full:
        return

    sur, given = _split_vn_person_name(spouse_full)
    marriage_date = _resolve_from_record_luong1_fallback(
        marriage_rec, marriage_ref, "marriage_date", ("date_of_marriage",)
    )
    marriage_place = _resolve_from_record_luong1_fallback(
        marriage_rec, marriage_ref, "marriage_place", ("marriage_city", "marriage_location")
    )
    marriage_city = _resolve_from_record_luong1_fallback(
        marriage_rec, marriage_ref, "marriage_city", ()
    )
    marriage_country = _resolve_from_record_luong1_fallback(
        marriage_rec, marriage_ref, "marriage_country", ()
    )

    from app.services.birth_location import normalize_location

    city = marriage_city
    if not city and marriage_place:
        segments = [s.strip() for s in marriage_place.split(",") if s.strip()]
        for seg in reversed(segments):
            if marriage_country and seg.lower() == marriage_country.lower():
                continue
            if derive_country_from_place(seg) and normalize_location(seg) == normalize_location(
                derive_country_from_place(seg)
            ):
                continue
            city = derive_city_from_place(seg) or seg
            break

    derived: dict[str, str] = {
        "spouse_full_name": spouse_full,
        "spouse_surname": _spouse_field_from_marriage(
            marriage_rec,
            passport_rec,
            "surname",
            full_name=spouse_full,
            marriage_ref=marriage_ref,
            passport_ref=passport_ref,
        )
        or sur,
        "spouse_given_names": _spouse_field_from_marriage(
            marriage_rec,
            passport_rec,
            "given_names",
            full_name=spouse_full,
            marriage_ref=marriage_ref,
            passport_ref=passport_ref,
        )
        or given,
        "spouse_date_of_birth": _spouse_field_from_marriage(
            marriage_rec,
            passport_rec,
            "date_of_birth",
            marriage_ref=marriage_ref,
            passport_ref=passport_ref,
        ),
        "spouse_birth_city": _spouse_field_from_marriage(
            marriage_rec, passport_rec, "birth_city", marriage_ref=marriage_ref, passport_ref=passport_ref
        ),
        "spouse_birth_state": _spouse_field_from_marriage(
            marriage_rec, passport_rec, "birth_state", marriage_ref=marriage_ref, passport_ref=passport_ref
        )
        or _spouse_field_from_marriage(
            marriage_rec, passport_rec, "place_of_birth", marriage_ref=marriage_ref, passport_ref=passport_ref
        ),
        "spouse_birth_country": _spouse_field_from_marriage(
            marriage_rec, passport_rec, "birth_country", marriage_ref=marriage_ref, passport_ref=passport_ref
        ),
        "spouse_address": _spouse_field_from_marriage(
            marriage_rec, passport_rec, "address", marriage_ref=marriage_ref, passport_ref=passport_ref
        ),
        "spouse_occupation": _spouse_field_from_marriage(
            marriage_rec, passport_rec, "occupation", marriage_ref=marriage_ref, passport_ref=passport_ref
        ),
        "spouse_marriage_date": marriage_date,
        "spouse_marriage_city": city,
        "spouse_marriage_state": _resolve_from_record_luong1_fallback(
            marriage_rec, marriage_ref, "marriage_state", ()
        )
        or derive_birth_state_from_place(marriage_place),
        "spouse_marriage_country": marriage_country or derive_country_from_place(marriage_place),
    }

    for field in fields_out:
        key = field.get("key", "")
        val = (derived.get(key) or "").strip()
        if not val:
            continue
        if (field.get("value") or "").strip():
            continue
        field["value"] = val
        field.setdefault("source", {})
        field["source"]["document_type"] = "marriage_certificate"
        field["source"]["source_field"] = key
        field["source"]["derived"] = "spouse_from_marriage"


def _strip_person_title(name: str) -> str:
    import re

    n = (name or "").strip()
    return re.sub(r"^(MR\.?|MRS\.?|MS\.?|MISS\.?|DR\.?)\s+", "", n, flags=re.I).strip()


def _ex_spouse_field_from_divorce(
    divorce_rec: ApplicantDocRecord,
    passport_rec: ApplicantDocRecord | None,
    field_suffix: str,
    *,
    full_name: str = "",
) -> str:
    side = _pick_spouse_side_from_marriage(divorce_rec, passport_rec)
    keys = (
        f"{side}_{field_suffix}",
        f"spouse_{field_suffix}",
    )
    for key in keys:
        val = _resolve_from_record(divorce_rec, key, ())
        if _is_meaningful_parent_value(val):
            return val
    if field_suffix == "date_of_birth":
        for key in ("wife_date_of_birth", "husband_date_of_birth", "date_of_birth", "dob"):
            val = _resolve_from_record(divorce_rec, key, ())
            if _is_meaningful_parent_value(val):
                return val
    return ""


def enrich_previous_spouse_from_divorce(
    fields_out: list[dict[str, Any]],
    divorce_rec: ApplicantDocRecord | None,
    passport_rec: ApplicantDocRecord | None,
) -> None:
    """Điền section phối ngẫu cũ từ quyết định ly hôn — chọn vợ/chồng không trùng chủ hồ sơ."""
    if not divorce_rec:
        return

    side = _pick_spouse_side_from_marriage(divorce_rec, passport_rec)
    ex_full = _strip_person_title(
        _resolve_from_record(
            divorce_rec,
            f"{side}_full_name",
            (f"{side}_name", "spouse_full_name", "spouse_name"),
        )
    )
    if not ex_full:
        ex_full = _strip_person_title(
            _resolve_from_record(
                divorce_rec,
                "wife_full_name" if side == "wife" else "husband_full_name",
                ("wife_name", "husband_name", "plaintiff_name", "defendant_name"),
            )
        )
    if not ex_full:
        combined = _resolve_from_record(divorce_rec, "spouse_name", ())
        if combined and " AND " in combined.upper():
            parts = [p.strip() for p in re.split(r"\s+AND\s+", combined, flags=re.I) if p.strip()]
            applicant = ""
            if passport_rec:
                applicant = _resolve_from_record(passport_rec, "full_name", ("name",))
            for part in parts:
                if applicant and _names_match(applicant, part):
                    continue
                ex_full = _strip_person_title(part)
                break

    marriage_date = _resolve_from_record(divorce_rec, "marriage_date", ("date_of_marriage",))
    divorce_date = _resolve_from_record(divorce_rec, "divorce_date", ())
    ex_dob = _ex_spouse_field_from_divorce(divorce_rec, passport_rec, "date_of_birth")

    derived: dict[str, str] = {
        "previous_spouses_used": "Yes",
        "previous_spouse_full_name": ex_full,
        "previous_spouse_date_of_birth": ex_dob,
        "previous_marriage_date": marriage_date,
        "previous_divorce_date": divorce_date,
        "divorce_husband_name": _strip_person_title(
            _resolve_from_record(divorce_rec, "husband_full_name", ("husband_name",))
        ),
        "divorce_wife_name": _strip_person_title(
            _resolve_from_record(divorce_rec, "wife_full_name", ("wife_name",))
        ),
        "divorce_document_number": _resolve_from_record(
            divorce_rec, "document_number", ("certificate_number",)
        ),
    }

    for field in fields_out:
        key = field.get("key", "")
        val = (derived.get(key) or "").strip()
        if val:
            field["value"] = val
            field.setdefault("source", {})
            field["source"]["document_type"] = "divorce"
            field["source"]["source_field"] = key
            field["source"]["derived"] = "previous_spouse_from_divorce"


def _canonical_birth_city_from_place(place: str) -> str:
    """Thành phố nơi sinh — bỏ quốc gia ở cuối chuỗi (vd. …, Da Nang City, Vietnam)."""
    from app.services.birth_location import normalize_location

    segments = [s.strip() for s in (place or "").split(",") if s.strip()]
    while len(segments) > 1:
        last = segments[-1]
        country = derive_country_from_place(last)
        if country and normalize_location(last) == normalize_location(country):
            segments.pop()
            continue
        if normalize_location(last) in {"vietnam", "viet nam", "vietnamese"}:
            segments.pop()
            continue
        break
    if segments:
        return segments[-1]
    return derive_city_from_place(place) or place


def _canonical_applicant_birth_place(fields_out: list[dict[str, Any]]) -> str:
    by_key = {f.get("key", ""): f for f in fields_out}
    city = (by_key.get("birth_city", {}).get("value") or "").strip()
    state = (by_key.get("birth_state", {}).get("value") or "").strip()
    pob = (by_key.get("place_of_birth", {}).get("value") or "").strip()
    if city:
        return city
    for raw in (state, pob):
        if raw:
            parsed = _canonical_birth_city_from_place(raw)
            if parsed:
                return parsed
    return ""


def enrich_applicant_birth_city_state_equal(
    fields_out: list[dict[str, Any]],
    passport_rec: ApplicantDocRecord | None,
    *,
    passport_ref: ApplicantDocRecord | None = None,
) -> None:
    """City of Birth và State/Province of Birth — cùng một giá trị (THÔNG TIN CÁ NHÂN)."""
    canonical = _canonical_applicant_birth_place(fields_out)
    if not canonical and (passport_rec or passport_ref):
        city = _resolve_from_record_luong1_fallback(
            passport_rec, passport_ref, "birth_city", ("city_of_birth",)
        )
        pob = _resolve_from_record_luong1_fallback(
            passport_rec, passport_ref, "place_of_birth", ("birth_place",)
        )
        canonical = city or _canonical_birth_city_from_place(pob) or pob
    if not canonical:
        return
    for field in fields_out:
        if field.get("key") not in {"birth_city", "birth_state"}:
            continue
        field["value"] = canonical
        field.setdefault("source", {})
        field["source"]["derived"] = "birth_city_state_equal"


def enrich_marital_status_from_documents(
    fields_out: list[dict[str, Any]],
    divorce_rec: ApplicantDocRecord | None,
) -> None:
    """Có giấy ly hôn → Divorced; không có → Married."""
    status = "Divorced" if divorce_rec else "Married"
    derived = "marital_status_from_divorce" if divorce_rec else "marital_status_default_married"
    doc_type = "divorce" if divorce_rec else "marriage_certificate"
    for field in fields_out:
        if field.get("key") != "current_marital_status":
            continue
        field["value"] = status
        field.setdefault("source", {})
        field["source"]["document_type"] = doc_type
        field["source"]["source_field"] = "marital_status"
        field["source"]["derived"] = derived


def list_child_birth_records(records: list[ApplicantDocRecord]) -> list[ApplicantDocRecord]:
    """Tất cả giấy khai sinh con — mỗi file một dòng (standard + _new)."""
    typed = [r for r in records if r.doc_type == "birth_certificate_child"]
    return sorted(typed, key=lambda r: (r.updated_at or r.id, str(r.id)))


def _child_data_from_record(rec: ApplicantDocRecord) -> dict[str, str]:
    full = _resolve_from_record(rec, "child_full_name", ("full_name", "name"))
    dob = _resolve_from_record(rec, "child_date_of_birth", ("date_of_birth", "dob"))
    pob = _resolve_from_record(rec, "child_place_of_birth", ("place_of_birth",))
    city = _resolve_from_record(rec, "child_birth_city", ("birth_city",))
    state = _resolve_from_record(rec, "child_birth_state", ("birth_state",))
    country = _resolve_from_record(rec, "child_birth_country", ("birth_country",))
    if not city and pob:
        city = derive_city_from_place(pob) or pob
    if not state and pob:
        state = derive_birth_state_from_place(pob) or ""
    if not country and pob:
        country = derive_country_from_place(pob) or ""
    return {
        "full_name": full,
        "date_of_birth": dob,
        "birth_city": city,
        "birth_state": state,
        "birth_country": country,
    }


def _child_dedupe_key(data: dict[str, str]) -> tuple[str, str]:
    name = re.sub(r"\s+", " ", (data.get("full_name") or "").strip().upper())
    dob = (data.get("date_of_birth") or "").strip()
    parsed = parse_full_date(dob)
    if parsed:
        dob = parsed.isoformat()
    else:
        partial = format_partial_ds260_date(dob)
        if partial:
            dob = partial.upper()
        else:
            dob = dob.upper()
    return name, dob


def _merge_raw_dict(rec: ApplicantDocRecord) -> dict[str, str]:
    try:
        form = json.loads(rec.form_data or "{}")
        raw = json.loads(rec.raw_data or "{}")
    except json.JSONDecodeError:
        return {}
    out: dict[str, str] = {}
    for src in (raw, form):
        for k, v in src.items():
            if v is not None and str(v).strip():
                out[k] = str(v).strip()
    return out


def _child_data_from_worksheet(rec: ApplicantDocRecord) -> list[dict[str, str]]:
    """Children declared on DS-260 worksheet (child_1..child_N slots)."""
    merged = _merge_raw_dict(rec)
    children: list[dict[str, str]] = []
    for idx in range(1, 10):
        prefix = f"child_{idx}_"
        full = merged.get(f"{prefix}full_name") or merged.get("child_full_name") if idx == 1 else merged.get(f"{prefix}full_name")
        if idx == 1 and not full:
            full = merged.get("child_full_name", "")
        dob = merged.get(f"{prefix}date_of_birth") or (merged.get("child_date_of_birth") if idx == 1 else "")
        city = merged.get(f"{prefix}birth_city") or (merged.get("child_birth_city") if idx == 1 else "")
        state = merged.get(f"{prefix}birth_state") or (merged.get("child_birth_state") if idx == 1 else "")
        country = merged.get(f"{prefix}birth_country") or (merged.get("child_birth_country") if idx == 1 else "")
        lives = merged.get(f"{prefix}lives_with", "")
        address = merged.get(f"{prefix}current_address") or merged.get(f"{prefix}address", "")
        immigrating = merged.get(f"{prefix}immigrating", "")
        immigrating_future = merged.get(f"{prefix}immigrating_future", "")
        data = {
            "full_name": full or "",
            "date_of_birth": dob or "",
            "birth_city": city or "",
            "birth_state": state or "",
            "birth_country": country or "",
            "lives_with": lives or "",
            "current_address": address or "",
            "immigrating": immigrating or "",
            "immigrating_future": immigrating_future or "",
        }
        if any(data.values()):
            children.append(data)
    return children


def _dedupe_children(
    items: list[tuple[dict[str, str], str, ApplicantDocRecord | None]],
) -> list[tuple[dict[str, str], str, ApplicantDocRecord | None]]:
    """Union birth certs + worksheet; prefer birth_certificate_child on duplicate."""
    priority = {"birth_certificate_child": 0, "ds260_customer_form": 1}
    ranked = sorted(items, key=lambda x: (priority.get(x[1], 9), _child_dedupe_key(x[0])))
    seen: set[tuple[str, str]] = set()
    out: list[tuple[dict[str, str], str, ApplicantDocRecord | None]] = []
    for data, source, rec in ranked:
        key = _child_dedupe_key(data)
        if not key[0] and not key[1]:
            continue
        if key in seen:
            continue
        seen.add(key)
        out.append((data, source, rec))
    return out


def enrich_children_section_from_birth_certs(
    fields_out: list[dict[str, Any]],
    child_records: list[ApplicantDocRecord],
    *,
    all_records: list[ApplicantDocRecord] | None = None,
) -> None:
    """
    Union giấy khai sinh con + worksheet DS-260, dedupe, điền tối đa 3 slot.
    """
    from app.services.ds260_conflicts import pick_latest_by_variant

    items: list[tuple[dict[str, str], str, ApplicantDocRecord | None]] = []
    for rec in child_records:
        data = _child_data_from_record(rec)
        if any(data.values()):
            items.append((data, "birth_certificate_child", rec))

    records = all_records if all_records is not None else child_records
    ws_rec = pick_latest_by_variant(records, "ds260_customer_form", "exception") or pick_latest_record(
        records, "ds260_customer_form"
    )
    ws_declared_count = ""
    if ws_rec:
        ws_merged = _merge_raw_dict(ws_rec)
        ws_declared_count = (ws_merged.get("children_count") or "").strip()
        for data in _child_data_from_worksheet(ws_rec):
            items.append((data, "ds260_customer_form", ws_rec))

    merged = _dedupe_children(items)
    ordered = sorted(
        merged,
        key=lambda x: (
            parse_full_date(x[0].get("date_of_birth", "")) or date.min,
            format_partial_ds260_date(x[0].get("date_of_birth", "")) or "",
            _child_dedupe_key(x[0]),
        ),
    )

    derived: dict[str, str] = {}
    total = len(ordered)
    if total or ws_declared_count:
        derived["children_used"] = "Yes" if (total or ws_declared_count not in {"", "0"}) else ""
        count_num = total
        if ws_declared_count.isdigit():
            count_num = max(count_num, int(ws_declared_count))
        derived["children_count"] = str(count_num) if count_num else ws_declared_count

    for idx, (data, source, rec) in enumerate(ordered[:4], start=1):
        prefix = f"child_{idx}_"
        for suffix, val in (
            ("full_name", data["full_name"]),
            ("date_of_birth", data["date_of_birth"]),
            ("birth_city", data["birth_city"]),
            ("birth_state", data["birth_state"]),
            ("birth_country", data["birth_country"]),
            ("lives_with", data.get("lives_with", "")),
            ("current_address", data.get("current_address", "")),
            ("immigrating", data.get("immigrating", "")),
            ("immigrating_future", data.get("immigrating_future", "")),
        ):
            if val:
                derived[f"{prefix}{suffix}"] = val

    for field in fields_out:
        key = field.get("key", "")
        if not (key.startswith("children_") or re.match(r"^child_\d+_", key)):
            continue
        val = (derived.get(key) or "").strip()
        field["value"] = val
        source_type = "birth_certificate_child"
        derived_tag = "children_from_birth_cert"
        if val and key.startswith("child_"):
            slot = re.match(r"^child_(\d+)_", key)
            if slot:
                slot_idx = int(slot.group(1)) - 1
                if slot_idx < len(ordered[:4]):
                    source_type = ordered[slot_idx][1]
                    derived_tag = (
                        "children_from_worksheet"
                        if source_type == "ds260_customer_form"
                        else "children_from_birth_cert"
                    )
        field["source"] = {
            "document_type": source_type,
            "source_field": key if val else "",
            "document_id": None,
            "document_filename": "",
            "variant": None,
            "record_id": None,
        }
        if val:
            field["source"]["derived"] = derived_tag


def _resolve_parent_birth_cert_fallback(
    mapping: Ds260FieldMapping,
    record: ApplicantDocRecord,
    value: str,
    source_field: str,
    parent: str,
) -> tuple[str, str]:
    if mapping.document != "birth_certificate" or value:
        return value, source_field
    if not has_parent_info_on_birth_cert(record, parent):
        return value, source_field

    name_field = f"{parent}_name"
    place_field = f"{parent}_place_of_birth"
    key = mapping.key

    if key == f"{parent}_surname":
        full = _resolve_from_record(record, name_field, (f"{parent}_full_name",))
        sur, _ = _split_vn_person_name(full)
        if sur:
            return sur, name_field
    elif key == f"{parent}_given_names":
        full = _resolve_from_record(record, name_field, (f"{parent}_full_name",))
        _, given = _split_vn_person_name(full)
        if given:
            return given, name_field
    elif key == f"{parent}_birth_city":
        city = _resolve_from_record(
            record,
            f"{parent}_birth_city",
            (f"{parent}_city_of_birth", f"{parent}_city"),
        )
        if city:
            return city, f"{parent}_birth_city"
        pob = _resolve_from_record(record, place_field, (f"{parent}_birth_place",))
        city = derive_city_from_place(pob)
        if city:
            return city, place_field
    elif key == f"{parent}_birth_state" and not mapping.derive:
        pob = _resolve_from_record(record, place_field, (f"{parent}_birth_place",))
        state = derive_birth_state_from_place(pob)
        if state:
            return state, place_field
    elif key == f"{parent}_birth_country" and not mapping.derive:
        pob = _resolve_from_record(record, place_field, (f"{parent}_birth_place",))
        country = derive_country_from_place(pob)
        if country:
            return country, place_field
    return value, source_field


def _resolve_place_text(record: ApplicantDocRecord | None, field: str, aliases: tuple[str, ...]) -> str:
    if not record:
        return ""
    return _resolve_from_record(record, field, aliases)


def _resolve_ds260_field_value(
    mapping: Ds260FieldMapping,
    record: ApplicantDocRecord | None,
) -> tuple[str, str]:
    """
    Returns (value, effective_source_field).
    Derive rules use mapping.field as source (place_of_birth, father_place_of_birth, …).
    Form khách upload thường dùng mapping.key (applicant_name, passport_issue_date, …).
    """
    aliases = _effective_aliases(mapping)

    if mapping.derive == "copy":
        direct, sf = _direct_ds260_value(record, mapping)
        if direct.strip():
            return direct, sf
        val = _resolve_place_text(record, mapping.field, aliases)
        return derive_birth_state_from_place(val), mapping.field
    if mapping.derive == "country_from_location":
        direct, sf = _direct_ds260_value(record, mapping)
        if direct.strip():
            mapped = derive_country_from_place(direct)
            return mapped or direct, sf
        val = _resolve_place_text(record, mapping.field, aliases)
        country = derive_country_from_place(val)
        if country:
            return country, mapping.field
        if record and mapping.field.endswith("_place_of_birth"):
            prefix = mapping.field.removesuffix("_place_of_birth")
            explicit = _resolve_from_record(
                record,
                f"{prefix}_birth_country",
                (f"{prefix}_country",),
            )
            if explicit:
                mapped = derive_country_from_place(explicit)
                return mapped or explicit, f"{prefix}_country"
        return "", mapping.field
    if mapping.derive == "city_from_place":
        direct, sf = _direct_ds260_value(record, mapping)
        if direct.strip():
            return direct, sf
        val = _resolve_place_text(record, mapping.field, aliases)
        return derive_city_from_place(val), mapping.field

    if record:
        value, source_field = _direct_ds260_value(record, mapping)
        if not value.strip():
            value = _resolve_from_record(record, mapping.field, aliases)
            source_field = mapping.field
        if mapping.document == "birth_certificate":
            for parent in ("father", "mother"):
                if mapping.key.startswith(f"{parent}_"):
                    value, source_field = _resolve_parent_birth_cert_fallback(
                        mapping, record, value, source_field, parent
                    )
                    break
        return value, source_field
    return "", mapping.field


def pick_latest_record(
    records: list[ApplicantDocRecord],
    doc_type: str,
) -> ApplicantDocRecord | None:
    """Một doc_type có thể có nhiều file — lấy bản mới nhất (không phân biệt Luồng 1 / đối chiếu)."""
    typed = [r for r in records if r.doc_type == doc_type]
    if not typed:
        return None
    return max(typed, key=lambda r: (r.updated_at or r.id, str(r.id)))


def pick_luong1_pair(
    records: list[ApplicantDocRecord],
    doc_type: str,
) -> tuple[ApplicantDocRecord | None, ApplicantDocRecord | None]:
    """Luồng 1 (standard) và bản đối chiếu khách upload (_new / exception)."""
    from app.services.ds260_conflicts import pick_latest_by_variant

    return (
        pick_latest_by_variant(records, doc_type, "standard"),
        pick_latest_by_variant(records, doc_type, "exception"),
    )


def pick_luong1_pair_for_person(
    records: list[ApplicantDocRecord],
    doc_type: str,
    person_name: str,
) -> tuple[ApplicantDocRecord | None, ApplicantDocRecord | None]:
    """Chọn passport/GKS khớp tên thành viên — dùng cho bộ hồ sơ gia đình."""
    name = (person_name or "").strip()
    if not name:
        return pick_luong1_pair(records, doc_type)

    typed = [r for r in records if r.doc_type == doc_type]
    matched = [
        r
        for r in typed
        if _names_same_person(_resolve_from_record(r, "full_name", ("name",)) or "", name)
        or (
            doc_type == "birth_certificate_child"
            and _names_same_person(
                _resolve_from_record(r, "child_full_name", ("full_name", "name")) or "", name
            )
        )
    ]
    pool = matched
    if not pool:
        return None, None

    def _latest_variant(variant: str) -> ApplicantDocRecord | None:
        candidates = [r for r in pool if r.variant == variant]
        if not candidates:
            return None
        return max(candidates, key=lambda r: (r.updated_at or r.id, str(r.id)))

    return _latest_variant("standard"), _latest_variant("exception")


def _resolve_from_record_luong1_fallback(
    standard: ApplicantDocRecord | None,
    reference: ApplicantDocRecord | None,
    field: str,
    aliases: tuple[str, ...] = (),
) -> str:
    """Luồng 1 trước; trường thiếu → lấy từ file đối chiếu (_new)."""
    if standard:
        val = _resolve_from_record(standard, field, aliases)
        if val.strip():
            return val
    if reference:
        val = _resolve_from_record(reference, field, aliases)
        if val.strip():
            return val
    return ""


LUONG1_PERSON_SCOPED_DOC_TYPES: frozenset[str] = frozenset(
    {"birth_certificate", "passport", "judicial_certificate"}
)


def _person_name_on_record(rec: ApplicantDocRecord) -> str:
    if rec.doc_type == "birth_certificate_child":
        return _resolve_from_record(rec, "child_full_name", ("full_name", "name")) or ""
    return _resolve_from_record(rec, "full_name", ("name",)) or ""


def _eligible_records_for_field_fill(
    records: list[ApplicantDocRecord],
    person_name: str,
    field_key: str,
) -> list[ApplicantDocRecord]:
    """Hồ sơ gia đình — chỉ lấy giấy tờ đúng người khi điền trống."""
    scoped = {"birth_certificate", "passport", "judicial_certificate"}
    out: list[ApplicantDocRecord] = []
    for rec in records:
        if rec.doc_type == "birth_certificate_child":
            continue
        if rec.doc_type in scoped:
            on_doc = _person_name_on_record(rec)
            if not on_doc or not _names_same_person(on_doc, person_name):
                continue
        if rec.doc_type == "passport" and field_key.startswith(("father_", "mother_")):
            continue
        out.append(rec)
    return out


def resolve_luong1_ds260_field(
    records: list[ApplicantDocRecord],
    doc_type: str,
    mapping: Ds260FieldMapping,
    resolutions: dict[str, str],
    *,
    person_name: str | None = None,
) -> tuple[str, str, ApplicantDocRecord | None, dict[str, Any]]:
    """
    Luồng 1 mặc định; trường thiếu → nguồn đối chiếu DS-260 khách upload (_new).
    Xung đột đã giải quyết → giá trị user chọn.
    """
    from app.services.ds260_conflicts import (
        ds260_conflict_field_key,
        pick_latest_by_variant,
        _norm_value,
    )

    standard = pick_latest_by_variant(records, doc_type, "standard")
    reference = pick_latest_by_variant(records, doc_type, "exception")
    if person_name and doc_type in LUONG1_PERSON_SCOPED_DOC_TYPES:
        standard, reference = pick_luong1_pair_for_person(records, doc_type, person_name)
    extra: dict[str, Any] = {}

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
            val, sf = _resolve_ds260_field_value(mapping, rec)
            if val and _norm_value(val) == _norm_value(chosen):
                return val, sf, rec, extra
        return chosen, mapping.field, standard or reference, {"derived": "conflict_resolution"}

    if standard:
        val, sf = _resolve_ds260_field_value(mapping, standard)
        if not _is_empty_for_fallback(val):
            return val, sf, standard, extra

    if reference:
        val, sf = _resolve_ds260_field_value(mapping, reference)
        if not _is_empty_for_fallback(val):
            return val, sf, reference, {"derived": "reference_fallback"}

    rec = standard or reference
    if rec:
        val, sf = _resolve_ds260_field_value(mapping, rec)
        return val, sf, rec, extra
    return "", mapping.field, None, extra


def resolve_customer_form_field(
    records: list[ApplicantDocRecord],
    doc_type: str,
    mapping: Ds260FieldMapping,
) -> tuple[str, str, ApplicantDocRecord | None, dict[str, Any]]:
    """Form khách khai: standard trước, thiếu → bản _new (exception)."""
    from app.services.ds260_conflicts import pick_latest_by_variant

    standard = pick_latest_by_variant(records, doc_type, "standard")
    reference = pick_latest_by_variant(records, doc_type, "exception")

    if standard:
        val, sf = _resolve_ds260_field_value(mapping, standard)
        if not _is_empty_for_fallback(val):
            return val, sf, standard, {}

    if reference:
        val, sf = _resolve_ds260_field_value(mapping, reference)
        if not _is_empty_for_fallback(val):
            return val, sf, reference, {"derived": "reference_fallback"}

    rec = standard or reference
    if rec:
        val, sf = _resolve_ds260_field_value(mapping, rec)
        return val, sf, rec, {}
    return "", mapping.field, None, {}


def enrich_empty_fields_from_all_doc_records(
    sections_out: list[dict[str, Any]],
    records: list[ApplicantDocRecord],
    filename_map: dict[str, str],
    *,
    person_name: str | None = None,
) -> None:
    """
    Trường còn trống → quét giấy tờ được phép (FIELD_ALLOWED_DOCS).
    Chỉ record có doc_type nằm trong whitelist của field mới được điền.
    Ưu tiên: standard → _new → worksheet DS-260 (_record_fill_priority).
    """
    if not records:
        return

    mappings = flatten_ds260_mappings()

    for sec in sections_out:
        for field in sec["fields"]:
            if not _is_empty_for_fallback(field.get("value") or ""):
                continue
            field_key = field.get("key", "")
            mapping = mappings.get(field_key)
            if not mapping or mapping.document == "spouse_applicant_profile":
                continue

            allowed = _allowed_doc_types_for_field(field_key, mapping)
            eligible = [r for r in records if r.doc_type in allowed]
            if person_name:
                eligible = _eligible_records_for_field_fill(eligible, person_name, field_key)
            if not eligible:
                continue

            ordered = sorted(eligible, key=lambda r: _record_fill_priority(r, mapping))
            for rec in ordered:
                val, source_field = _resolve_field_from_record(rec, mapping)
                if _is_empty_for_fallback(val):
                    continue
                doc_id = str(rec.source_document_id) if rec.source_document_id else None
                derived = "doc_scan_fill"
                if rec.variant == "exception":
                    derived = "reference_cross_fill"
                elif rec.doc_type != mapping.document:
                    derived = "cross_document_fill"
                if rec.doc_type == "ds260_customer_form":
                    derived = "ds260_worksheet_fill"
                field["value"] = val
                field["source"] = {
                    "document_type": rec.doc_type,
                    "source_field": source_field,
                    "document_id": doc_id,
                    "document_filename": filename_map.get(doc_id or "", "") if doc_id else "",
                    "variant": rec.variant,
                    "record_id": str(rec.id),
                    "derived": derived,
                }
                break


def enrich_empty_fields_from_ds260_customer_worksheet(
    sections_out: list[dict[str, Any]],
    records: list[ApplicantDocRecord],
    filename_map: dict[str, str],
) -> None:
    """
    Lấp trống chỉ từ bản DS-260 khách khai — dùng trong test / tool.

    Production: `resolve_ds260_form()` gọi `enrich_empty_fields_from_all_doc_records()`
    để worksheet DS-260 không vượt giấy tờ Luồng 1 (_record_fill_priority tier 4).
    """
    from app.services.ds260_conflicts import pick_latest_by_variant

    ds260_rec = pick_latest_by_variant(records, "ds260_customer_form", "exception") or pick_latest_record(
        records, "ds260_customer_form"
    )
    if not ds260_rec:
        return

    mappings = flatten_ds260_mappings()
    for sec in sections_out:
        for field in sec["fields"]:
            if not _is_empty_for_fallback(field.get("value") or ""):
                continue
            mapping = mappings.get(field.get("key", ""))
            if not mapping or mapping.document == "spouse_applicant_profile":
                continue
            if sec.get("id") == "section_children" and re.match(r"^child_\d+_", field.get("key", "")):
                continue

            val, source_field = _resolve_field_from_record(ds260_rec, mapping)
            if _is_empty_for_fallback(val):
                continue
            doc_id = str(ds260_rec.source_document_id) if ds260_rec.source_document_id else None
            field["value"] = val
            field["source"] = {
                "document_type": "ds260_customer_form",
                "source_field": source_field,
                "document_id": doc_id,
                "document_filename": filename_map.get(doc_id or "", "") if doc_id else "",
                "variant": ds260_rec.variant,
                "record_id": str(ds260_rec.id),
                "derived": "ds260_worksheet_fill",
            }


# Giữ tên cũ cho test / import
enrich_empty_fields_from_reference_records = enrich_empty_fields_from_all_doc_records


SECTION_PRIMARY_DOC: dict[str, str] = {
    "section_judicial": "judicial_certificate",
    "section_divorce": "divorce",
    "section_previous_spouse": "divorce",
    "section_spouse": "marriage_certificate",
    "section_death": "death_certificate",
    "section_military": "military_discharge",
    "section_children": "birth_certificate_child",
}


def _attach_section_fill_stats(
    sections_out: list[dict[str, Any]],
    records: list[ApplicantDocRecord],
    *,
    member_role: str | None = None,
) -> tuple[int, int, int, int]:
    """Returns filled, total, applicable_filled, applicable_total."""
    present_docs = {r.doc_type for r in records}
    has_ref = any(r.variant == "exception" for r in records)
    child_count = len([r for r in records if r.doc_type == "birth_certificate_child"])

    filled = 0
    total = 0
    applicable_filled = 0
    applicable_total = 0
    all_mappings = flatten_ds260_mappings()

    for sec in sections_out:
        sec_filled = 0
        sec_total = 0
        sec_applicable = 0
        sec_applicable_filled = 0
        primary_doc = SECTION_PRIMARY_DOC.get(sec["id"])
        section_active = (not primary_doc) or (primary_doc in present_docs)
        if sec["id"] == "section_spouse":
            m_rec, m_ref = pick_luong1_pair(records, "marriage_certificate")
            p_rec, p_ref = pick_luong1_pair(records, "passport")
            section_active = has_applicable_marriage_certificate(m_rec, m_ref, p_rec, p_ref)
        if member_role == "child" and sec["id"] in _child_excluded_section_ids():
            section_active = False

        for field in sec["fields"]:
            if field.get("review_hidden"):
                continue
            val = (field.get("value") or "").strip()
            total += 1
            sec_total += 1
            if val:
                filled += 1
                sec_filled += 1

            mapping = all_mappings.get(field.get("key", ""))
            applicable = section_active
            if applicable and sec["id"] == "section_children":
                m = re.match(r"^child_(\d+)_", field.get("key", ""))
                if m and int(m.group(1)) > max(child_count, 1):
                    applicable = False
            if applicable and mapping and mapping.document in {"ds260_customer_form", "address_document"}:
                applicable = (
                    "ds260_customer_form" in present_docs
                    or "address_document" in present_docs
                    or has_ref
                )
            if applicable and member_role == "child" and field.get("key") == "current_marital_status":
                applicable = False
            if applicable:
                applicable_total += 1
                sec_applicable += 1
                if val:
                    applicable_filled += 1
                    sec_applicable_filled += 1

        sec["filled_count"] = sec_filled
        sec["total_count"] = sec_total
        sec["applicable_count"] = sec_applicable
        sec["applicable_filled_count"] = sec_applicable_filled
        sec["document_missing"] = bool(primary_doc and primary_doc not in present_docs)

    return filled, total, applicable_filled, applicable_total


def pick_doc_record_for_ds260(
    records: list[ApplicantDocRecord],
    doc_type: str,
    mapping: Ds260FieldMapping,
    resolutions: dict[str, str],
) -> ApplicantDocRecord | None:
    """Luồng 1 (standard) mặc định; nếu user đã chọn khi xung đột → bản khớp giá trị đã chọn."""
    from app.services.ds260_conflicts import (
        ds260_conflict_field_key,
        pick_latest_by_variant,
        _norm_value,
    )

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
            val = _resolve_from_record(rec, mapping.field, mapping.aliases)
            if val and _norm_value(val) == _norm_value(chosen):
                return rec

    if standard:
        return standard
    if reference:
        return reference
    return pick_latest_record(records, doc_type)


def _pick_luong1_record(
    records: list[ApplicantDocRecord],
    doc_type: str,
) -> ApplicantDocRecord | None:
    from app.services.ds260_conflicts import pick_latest_by_variant

    return pick_latest_by_variant(records, doc_type, "standard") or pick_latest_record(
        records, doc_type
    )


async def load_applicant_doc_records_indexed(
    db: AsyncSession,
    applicant_id,
) -> dict[str, ApplicantDocRecord]:
    from app.services.ds260_conflicts import LUONG1_DOC_TYPES

    records = await list_doc_records(db, applicant_id)
    by_type: dict[str, ApplicantDocRecord] = {}
    for doc_type in (*REGISTRY_BY_CODE, "ds260_customer_form"):
        if doc_type in LUONG1_DOC_TYPES:
            rec = _pick_luong1_record(records, doc_type)
        else:
            rec = pick_latest_record(records, doc_type)
        if rec:
            by_type[doc_type] = rec
    return by_type


async def resolve_ds260_form(
    db: AsyncSession,
    applicant_id,
    *,
    member_id: uuid.UUID | None = None,
    filename_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    """
    Resolve toàn bộ DS260 fields từ doc records — không đọc profile merge.
    Với bộ hồ sơ gia đình: truyền member_id để điền DS-260 cho chồng/vợ/con cụ thể.
    """
    import uuid as _uuid

    from app.services.family_case import (
        MemberContext,
        apply_child_sections_from_birth_cert,
        enrich_child_member_personal,
        load_case_members,
        member_number_map,
        member_context_to_dict,
        pick_child_birth_cert_for_person,
        resolve_member_context,
    )

    records = await list_doc_records(db, applicant_id)
    filename_map = filename_map or {}

    from app.services.ds260_conflicts import (
        LUONG1_DOC_TYPES,
        WORKSHEET_COMPARE_KEYS,
        load_ds260_field_resolutions,
        worksheet_conflict_field_key,
    )

    resolutions = await load_ds260_field_resolutions(db, applicant_id)

    app_result = await db.execute(select(Applicant).where(Applicant.id == applicant_id))
    applicant = app_result.scalar_one_or_none()
    member_ctx: MemberContext | None = None
    if applicant:
        mid = member_id
        if isinstance(mid, str):
            mid = _uuid.UUID(mid)
        member_ctx = await resolve_member_context(db, applicant, mid)

    person_name = member_ctx.display_name if member_ctx else (applicant.display_name if applicant else "")
    is_child_member = member_ctx is not None and member_ctx.role == "child"
    child_bc: ApplicantDocRecord | None = None
    if is_child_member:
        child_bc = pick_child_birth_cert_for_person(records, person_name)

    passport_rec, passport_ref = (
        pick_luong1_pair_for_person(records, "passport", person_name)
        if member_ctx
        else pick_luong1_pair(records, "passport")
    )

    sections_out: list[dict[str, Any]] = []
    total = 0

    for sec in load_ds260_sections():
        fields_out: list[dict[str, Any]] = []
        for mapping in sec.fields:
            total += 1
            if is_child_member and (
                sec.id in _child_excluded_section_ids()
                or sec.id in _child_own_birth_cert_section_ids()
                or (sec.id == "section_a_personal" and mapping.key == "current_marital_status")
            ):
                fields_out.append(
                    {
                        "key": mapping.key,
                        "label": mapping.label,
                        "value": "",
                        "review_hidden": mapping.review_hidden,
                        "source": empty_ds260_field_source(),
                    }
                )
                continue
            if sec.id == "section_children" and (
                mapping.key.startswith("children_") or re.match(r"^child_\d+_", mapping.key)
            ):
                rec = None
                value, source_field = "", mapping.field
                src_extra = {}
            else:
                src_extra: dict[str, Any] = {}
                if mapping.document in LUONG1_DOC_TYPES:
                    value, source_field, rec, src_extra = resolve_luong1_ds260_field(
                        records,
                        mapping.document,
                        mapping,
                        resolutions,
                        person_name=person_name if member_ctx else None,
                    )
                elif mapping.document in CUSTOMER_FORM_DOC_TYPES:
                    value, source_field, rec, src_extra = resolve_customer_form_field(
                        records, mapping.document, mapping
                    )
                else:
                    rec = pick_latest_record(records, mapping.document)
                    value, source_field = _resolve_ds260_field_value(mapping, rec)
                if mapping.document == "spouse_applicant_profile":
                    rec = None
                    value, source_field = "", mapping.field
                    src_extra = {}

                if mapping.key in WORKSHEET_COMPARE_KEYS:
                    wk_fk = worksheet_conflict_field_key(mapping.key)
                    chosen = (resolutions.get(wk_fk) or "").strip()
                    if chosen and not is_child_member:
                        apply_ws = True
                        if mapping.key in {
                            "applicant_name",
                            "date_of_birth",
                            "passport_number",
                            "gender",
                        } and person_name and not _names_same_person(chosen, person_name):
                            apply_ws = False
                        if apply_ws:
                            value = chosen
                            source_field = mapping.field
                            src_extra = {"derived": "worksheet_conflict_resolution"}

            doc_id = str(rec.source_document_id) if rec and rec.source_document_id else None
            source_meta: dict[str, Any] = {
                "document_type": mapping.document,
                "source_field": source_field,
                "document_id": doc_id,
                "document_filename": filename_map.get(doc_id or "", "") if doc_id else "",
                "variant": rec.variant if rec else None,
                "record_id": str(rec.id) if rec else None,
            }
            if mapping.derive and "derived" not in src_extra:
                source_meta["derived"] = mapping.derive
            source_meta.update(src_extra)
            fields_out.append(
                {
                    "key": mapping.key,
                    "label": mapping.label,
                    "value": value,
                    "review_hidden": mapping.review_hidden,
                    "source": source_meta,
                }
            )
        if sec.id == "section_father" and not is_child_member:
            if member_ctx and person_name:
                bc_rec, bc_ref = pick_luong1_pair_for_person(
                    records, "birth_certificate", person_name
                )
                bc_rec = bc_rec or bc_ref
            else:
                bc_rec = _pick_luong1_record(records, "birth_certificate")
            if bc_rec and not has_father_info_on_birth_cert(bc_rec):
                apply_father_absent_rule(fields_out)
            enrich_parent_is_living(fields_out, bc_rec, "father")
            death_rec = pick_latest_record(records, "death_certificate")
            father_name = next(
                (f.get("value") or "" for f in fields_out if f.get("key") == "father_full_name"),
                "",
            )
            enrich_parent_death_from_death_cert(fields_out, death_rec, "father", father_name)
        if sec.id == "section_mother" and not is_child_member:
            if member_ctx and person_name:
                bc_rec, bc_ref = pick_luong1_pair_for_person(
                    records, "birth_certificate", person_name
                )
                bc_rec = bc_rec or bc_ref
            else:
                bc_rec = _pick_luong1_record(records, "birth_certificate")
            if bc_rec and not has_mother_info_on_birth_cert(bc_rec):
                apply_mother_absent_rule(fields_out)
            enrich_parent_is_living(fields_out, bc_rec, "mother")
            death_rec = pick_latest_record(records, "death_certificate")
            mother_name = next(
                (f.get("value") or "" for f in fields_out if f.get("key") == "mother_full_name"),
                "",
            )
            enrich_parent_death_from_death_cert(fields_out, death_rec, "mother", mother_name)
        if sec.id == "section_a_personal":
            if not is_child_member:
                divorce_rec = pick_latest_record(records, "divorce")
                enrich_marital_status_from_documents(fields_out, divorce_rec)
            enrich_applicant_birth_city_state_equal(
                fields_out, passport_rec, passport_ref=passport_ref
            )
            if member_ctx and passport_rec:
                _overwrite_section_from_passport(fields_out, passport_rec, passport_ref)
        if sec.id == "section_a_passport" and member_ctx and passport_rec:
            _overwrite_section_from_passport(fields_out, passport_rec, passport_ref)
        if sec.id == "section_judicial" and member_ctx:
            jud_rec, jud_ref = pick_luong1_pair_for_person(
                records, "judicial_certificate", person_name
            )
            if jud_rec or jud_ref:
                _overwrite_section_from_luong1_doc(
                    fields_out, "judicial_certificate", jud_rec, jud_ref
                )
        if sec.id == "section_spouse" and not is_child_member:
            marriage_rec, marriage_ref = pick_luong1_pair(records, "marriage_certificate")
            if has_applicable_marriage_certificate(
                marriage_rec, marriage_ref, passport_rec, passport_ref
            ):
                birth_certs = list_birth_certificate_records(records)
                enrich_spouse_section_from_marriage(
                    fields_out,
                    marriage_rec,
                    passport_rec,
                    marriage_ref=marriage_ref,
                    passport_ref=passport_ref,
                )
                enrich_spouse_birth_place_from_birth_certificate(
                    fields_out, marriage_rec or marriage_ref, passport_rec, birth_certs
                )
                if applicant:
                    await enrich_spouse_occupation_from_spouse_applicant(
                        fields_out, db, applicant, marriage_rec or marriage_ref, passport_rec
                    )
            else:
                clear_spouse_section_fields(fields_out)
        if sec.id == "section_previous_spouse" and not is_child_member:
            divorce_rec = pick_latest_record(records, "divorce")
            enrich_previous_spouse_from_divorce(fields_out, divorce_rec, passport_rec)
        if sec.id == "section_children" and not is_child_member:
            child_recs = list_child_birth_records(records)
            enrich_children_section_from_birth_certs(fields_out, child_recs, all_records=records)
        sections_out.append(
            {
                "id": sec.id,
                "title": sec.title,
                "subtitle": sec.subtitle,
                "fields": fields_out,
            }
        )

    if is_child_member:
        for sec in sections_out:
            enrich_child_member_personal(sec["fields"], child_bc, passport_rec)
            if sec["id"] == "section_a_passport":
                if passport_rec:
                    _overwrite_section_from_passport(sec["fields"], passport_rec, passport_ref)
                else:
                    for field in sec["fields"]:
                        field["value"] = ""
                        field["source"] = empty_ds260_field_source()

    enrich_empty_fields_from_all_doc_records(
        sections_out, records, filename_map, person_name=person_name if member_ctx else None
    )

    if is_child_member and not passport_rec:
        for sec in sections_out:
            if sec["id"] != "section_a_passport":
                continue
            for field in sec["fields"]:
                field["value"] = ""
                field["source"] = empty_ds260_field_source()

    if is_child_member:
        for sec in sections_out:
            if sec["id"] == "section_a_personal":
                enrich_child_member_personal(sec["fields"], child_bc, passport_rec)

    marriage_rec, marriage_ref = pick_luong1_pair(records, "marriage_certificate")
    if not has_applicable_marriage_certificate(
        marriage_rec, marriage_ref, passport_rec, passport_ref
    ):
        for sec in sections_out:
            if sec["id"] == "section_spouse":
                clear_spouse_section_fields(sec["fields"])

    from app.services.ds260_conflicts import (
        apply_ds260_manual_overrides,
        apply_ds260_resolved_conflicts,
        load_ds260_manual_overrides,
    )

    apply_ds260_resolved_conflicts(
        sections_out,
        resolutions,
        person_name=person_name,
        member_role=member_ctx.role if member_ctx else None,
    )
    manual_overrides = await load_ds260_manual_overrides(
        db, applicant_id, member_id=member_ctx.id if member_ctx else None
    )
    if is_child_member:
        clear_child_adult_only_ds260_sections(sections_out)
        case_members = await load_case_members(db, applicant_id)
        apply_child_sections_from_birth_cert(
            sections_out, child_bc, records=records, members=case_members
        )
        if child_bc:
            for sec in sections_out:
                enrich_child_member_personal(sec["fields"], child_bc, passport_rec)

    apply_ds260_manual_overrides(sections_out, manual_overrides)

    from app.services.ds260_dates import format_sections_date_display

    format_sections_date_display(sections_out)

    from app.services.ds260_english_output import format_sections_english_output

    format_sections_english_output(sections_out)

    filled, total, applicable_filled, applicable_total = _attach_section_fill_stats(
        sections_out, records, member_role=member_ctx.role if member_ctx else None
    )

    documents_out: dict[str, dict[str, Any]] = {}
    for doc_type, rec in (await load_applicant_doc_records_indexed(db, applicant_id)).items():
        doc_id = str(rec.source_document_id) if rec.source_document_id else ""
        documents_out[doc_type] = {
            "record_id": str(rec.id),
            "document_id": doc_id,
            "document_filename": filename_map.get(doc_id, ""),
            "variant": rec.variant,
            "form_data": json.loads(rec.form_data or "{}"),
            "raw_data": json.loads(rec.raw_data or "{}"),
            "updated_at": rec.updated_at.isoformat() if rec.updated_at else None,
        }

    member_number: str | None = None
    if member_ctx and applicant:
        case_members = await load_case_members(db, applicant_id)
        nums = member_number_map(case_members)
        member_number = nums.get(member_ctx.id)

    return {
        "version": load_ds260_mapping().get("version", 1),
        "filled_count": filled,
        "total_count": total,
        "applicable_filled_count": applicable_filled,
        "applicable_count": applicable_total,
        "member": member_context_to_dict(member_ctx, member_number=member_number),
        "sections": sections_out,
        "documents": documents_out,
    }


def _overwrite_section_from_luong1_doc(
    fields_out: list[dict[str, Any]],
    doc_type: str,
    standard_rec: ApplicantDocRecord | None,
    reference_rec: ApplicantDocRecord | None,
    *,
    derived: str = "family_member_luong1",
) -> None:
    """Ghi đè field DS-260 từ Luồng 1 đúng loại giấy / đúng người."""
    all_mappings = flatten_ds260_mappings()
    for field in fields_out:
        key = field.get("key", "")
        mapping = all_mappings.get(key)
        if not mapping or mapping.document != doc_type:
            continue
        val = _resolve_from_record_luong1_fallback(
            standard_rec,
            reference_rec,
            mapping.field,
            mapping.aliases,
        )
        if not val:
            continue
        field["value"] = val
        field["source"] = {
            "document_type": doc_type,
            "source_field": mapping.field,
            "derived": derived,
            "record_id": str((standard_rec or reference_rec).id),
        }


def _overwrite_section_from_passport(
    fields_out: list[dict[str, Any]],
    passport_rec: ApplicantDocRecord | None,
    passport_ref: ApplicantDocRecord | None,
) -> None:
    """Ghi đè field cá nhân/hộ chiếu từ passport đúng người (bộ hồ sơ gia đình)."""
    _overwrite_section_from_luong1_doc(
        fields_out,
        "passport",
        passport_rec,
        passport_ref,
        derived="family_member_passport",
    )


def get_extract_keys_for_doc_type(doc_type: str) -> list[str]:
    """Keys allowed for OCR extraction — from document registry schema."""
    if doc_type == "ds260_customer_form":
        from app.services.ds260_customer_keys import build_ds260_customer_extract_keys

        return sorted(build_ds260_customer_extract_keys())

    defn = RECORDABLE_REGISTRY_BY_CODE.get(doc_type)
    if defn:
        return list(dict.fromkeys(defn.extract_keys))
    from app.services.field_mapping import FIELD_MAP

    return list(dict.fromkeys(FIELD_MAP.get(doc_type, {}).keys()))
