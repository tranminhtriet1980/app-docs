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
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Applicant, ApplicantDocRecord, ProfileField
from app.services.birth_location import (
    derive_birth_state_from_place,
    derive_city_from_place,
    derive_country_from_place,
    extract_city_token,
    looks_like_address_or_facility,
    split_birthplace_city_state,
)
from app.services.doc_record_sync import list_doc_records
from app.services.ds260_dates import format_ds260_display_date, format_partial_ds260_date, parse_full_date
from app.services.ds260_normalize import format_vn_phone_display
from app.services.document_registry import (
    BIRTH_CERT_CANONICAL_ALIASES,
    RECORDABLE_REGISTRY_BY_CODE,
    REGISTRY_BY_CODE,
    normalize_birth_certificate_raw,
)
from app.services.ds260_customer_keys import normalize_ds260_customer_raw

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
    default: str | None = None


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
                default=f.get("default"),
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


def pick_latest_record(
    records: list[ApplicantDocRecord],
    doc_type: str,
) -> ApplicantDocRecord | None:
    """Một doc_type có thể có nhiều file — lấy bản mới nhất (không phân biệt Luồng 1 / đối chiếu)."""
    typed = [r for r in records if r.doc_type == doc_type]
    if not typed:
        return None
    return max(typed, key=lambda r: (r.updated_at or r.id, str(r.id)))


def pick_latest_by_variant(
    records: list[ApplicantDocRecord],
    doc_type: str,
    variant: str,
) -> ApplicantDocRecord | None:
    """Lấy bản ghi mới nhất theo doc_type và variant (standard / exception)."""
    typed = [r for r in records if r.doc_type == doc_type and r.variant == variant]
    if not typed:
        return None
    return max(typed, key=lambda r: (r.updated_at or r.id, str(r.id)))


def _allow_ambiguous_worksheet_key(mapping: "Ds260FieldMapping", raw: dict[str, str], alias: str) -> bool:
    """Chặn document_number/certificate_number của mục khác (ly hôn, lý lịch tư pháp…) trong
    worksheet lọt vào field không liên quan qua so khớp loose — dùng lại guard đã có ở
    ds260_customer_keys cho đúng ngữ cảnh (xem _should_map_document_number_to_passport)."""
    from app.services.ds260_customer_keys import _AMBIGUOUS_DOC_NUMBER_ALIASES, _allow_document_number_for_field

    if alias not in _AMBIGUOUS_DOC_NUMBER_ALIASES:
        return True
    return _allow_document_number_for_field(mapping.key, raw, alias)


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
        from app.services.ds260_customer_keys import (
            _allow_document_number_for_field,
            normalize_ds260_customer_raw,
        )

        merged: dict[str, str] = {}
        for src in (raw, form):
            for k, v in src.items():
                if v is not None and str(v).strip():
                    merged[k] = str(v).strip()
        merged = normalize_ds260_customer_raw(merged)
        if merged.get(source_field, "").strip():
            return merged[source_field].strip()
        for alias in dict.fromkeys((*aliases, source_field)):
            if not _allow_document_number_for_field(source_field, merged, alias):
                continue
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
    is_worksheet = getattr(record, "doc_type", None) == "ds260_customer_form"
    norms = {_norm_field_key(k): k for k in _lookup_keys_for_mapping(mapping)}
    for raw_key, val in merged.items():
        nk = _norm_field_key(raw_key)
        if nk in norms:
            if is_worksheet and not _allow_ambiguous_worksheet_key(mapping, merged, raw_key):
                continue
            return val, raw_key
    # CHỈ so khớp CHÍNH XÁC (không endswith/in) — "current_address" từng khớp NHẦM
    # "child_1_current_address" vì target nằm trọn trong nk như một hậu tố, dẫn tới địa chỉ
    # của CON bị hiển thị làm current_address của chính đương đơn (sự cố thực tế 2026-08-04).
    # _norm_field_key chỉ bỏ ký tự không phải chữ/số, không có ranh giới từ, nên endswith/in
    # không phân biệt được "field của người khác có tiền tố" với "đúng field cần tìm".
    target = _norm_field_key(mapping.key)
    field_n = _norm_field_key(mapping.field)
    for raw_key, val in merged.items():
        nk = _norm_field_key(raw_key)
        if (target and nk == target) or (field_n and nk == field_n):
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

_GENDER_TOKENS = frozenset({"male", "female", "nam", "nu", "nữ", "m", "f"})

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


def _year_from_death_date(val: str) -> str:
    from app.services.ds260_dates import format_ds260_display_date, format_partial_ds260_date, parse_full_date

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
    # Giấy báo tử là nguồn quyết định: ghi đè còn-sống = No dù trước đó suy ra "Yes".
    for field in fields_out:
        key = field.get("key", "")
        if key == death_key and year:
            field["value"] = year
            field["source"] = {
                "document_type": "death_certificate",
                "source_field": "date_of_death",
                "record_id": str(death_rec.id),
                "derived": f"{parent}_death_from_cert",
            }
        if key == living_key:
            field["value"] = "No"
            field["source"] = {
                "document_type": "death_certificate",
                "source_field": "date_of_death",
                "record_id": str(death_rec.id),
                "derived": f"{parent}_not_living_from_death_cert",
            }


_JUDICIAL_STATUS_FIELD_ALIASES = (
    "criminal_record_status",
    "an_tich_status",
    "criminal_record",
    "conviction_status",
)

_NO_CRIMINAL_RECORD_PHRASES = (
    "không có án tích",
    "khong co an tich",
    "không có tiền án",
    "khong co tien an",
    "no criminal record",
    "not have a criminal record",
    "no record of conviction",
)


def _judicial_criminal_record_text(judicial_rec: ApplicantDocRecord | None) -> str:
    if not judicial_rec:
        return ""
    for key in _JUDICIAL_STATUS_FIELD_ALIASES:
        val = _resolve_from_record(judicial_rec, key, ())
        if val.strip():
            return val.strip()
    return ""


def enrich_arrested_convicted_from_judicial(
    fields_out: list[dict[str, Any]],
    judicial_rec: ApplicantDocRecord | None,
) -> None:
    """Điền câu 'Ever arrested or convicted?' (arrested_convicted, mục Security and
    Background) từ tình trạng án tích ghi trên Phiếu lý lịch tư pháp (criminal_record_status).

    Chỉ điền khi trường còn TRỐNG — không ghi đè câu trả lời khách đã tự khai trên worksheet
    (nếu khách khai khác với LLTP, đó là xung đột cần người duyệt xử lý thủ công, không tự
    quyết định ở đây). Không trích được criminal_record_status (giấy cũ OCR trước khi có field
    này, hoặc không đọc được) → bỏ qua, KHÔNG suy đoán Yes/No.

    Có án tích cụ thể → "Yes" kèm cảnh báo riêng ở validate_ds260 để người duyệt kiểm tra lại —
    câu hỏi nhạy cảm, sai sót ảnh hưởng trực tiếp hồ sơ visa.
    """
    status_text = _judicial_criminal_record_text(judicial_rec)
    if not status_text:
        return
    lowered = status_text.lower()
    has_record = not any(phrase in lowered for phrase in _NO_CRIMINAL_RECORD_PHRASES)
    value = "Yes" if has_record else "No"
    derived = (
        "arrested_convicted_yes_from_judicial"
        if has_record
        else "arrested_convicted_no_from_judicial"
    )
    for field in fields_out:
        if field.get("key") != "arrested_convicted":
            continue
        if (field.get("value") or "").strip():
            continue
        field["value"] = value
        field["source"] = {
            **empty_ds260_field_source(),
            "document_type": "judicial_certificate",
            "source_field": "criminal_record_status",
            "record_id": str(judicial_rec.id) if judicial_rec else None,
            "derived": derived,
        }


def _spouse_is_deceased(
    marriage_primary: ApplicantDocRecord | None,
    passport_rec: ApplicantDocRecord | None,
    passport_ref: ApplicantDocRecord | None,
    death_rec: ApplicantDocRecord | None,
) -> bool:
    """Phối ngẫu trên giấy kết hôn trùng người trên giấy báo tử → đã goá."""
    if not marriage_primary or not death_rec:
        return False
    side = _pick_spouse_side_from_marriage(marriage_primary, passport_rec, passport_ref)
    if not side:
        return False
    spouse_name = _resolve_from_record(
        marriage_primary, f"{side}_full_name", (f"{side}_name",)
    )
    if not spouse_name:
        return False
    merged = _merge_raw_dict(death_rec)
    deceased = (merged.get("deceased_full_name") or merged.get("full_name") or "").strip()
    return _names_match(deceased, spouse_name)


def _normalize_person_name_key(name: str) -> str:
    """Điểm chốt DUY NHẤT mà _names_match/_names_same_person dùng để so khớp tên người —
    sửa ở đây sửa cho MỌI nơi gọi (dedupe con, khớp vợ/chồng, khớp thành viên hồ sơ theo tên
    OCR, khớp cha/mẹ trên lý lịch tư pháp...). Dùng normalize_person_name (chỉ bỏ dấu), KHÔNG
    dùng normalize_location (dành cho địa danh, lọc mất từ hành chính trùng tên người — xem
    docstring normalize_person_name)."""
    from app.services.birth_location import normalize_person_name

    return normalize_person_name(name)


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
    marriage_rec: ApplicantDocRecord | None,
    passport_rec: ApplicantDocRecord | None,
    passport_ref: ApplicantDocRecord | None = None,
) -> str:
    """Trả 'husband' hoặc 'wife' — phía còn lại so với chủ hồ sơ trên giấy kết hôn.

    Tên chủ hồ sơ (passport OCR nhiễu) chỉ so khớp theo HỌ (_names_match) — khi vợ chồng trùng
    họ, CẢ HAI bên đều "khớp" và trước đây luôn chọn nhầm bên husband trước (thứ tự if) bất kể
    đúng sai. Dùng giới tính hộ chiếu làm trọng tài khi rơi vào trường hợp mơ hồ này — không đoán
    mò khi giới tính cũng không xác định được (giữ hành vi an toàn cũ: trả rỗng)."""
    if not marriage_rec:
        return ""
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

    matches_husband = bool(applicant and husband and _names_match(applicant, husband))
    matches_wife = bool(applicant and wife and _names_match(applicant, wife))

    if matches_husband and matches_wife:
        if gender in {"M", "MALE", "NAM"}:
            return "wife"
        if gender in {"F", "FEMALE", "NU", "NỮ"}:
            return "husband"
        return ""
    if matches_husband:
        return "wife"
    if matches_wife:
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


def _divorce_ex_spouse_full_name(
    divorce_rec: ApplicantDocRecord | None,
    passport_rec: ApplicantDocRecord | None,
    passport_ref: ApplicantDocRecord | None = None,
) -> str:
    """Tên đầy đủ của người đã ly hôn với chủ hồ sơ trên quyết định ly hôn (rỗng nếu không xác
    định được — dùng chung bởi enrich_previous_spouse_from_divorce và _marriage_is_the_divorced_one."""
    if not divorce_rec:
        return ""
    side = _pick_spouse_side_from_marriage(divorce_rec, passport_rec, passport_ref)
    ex_full = _strip_person_title(
        _resolve_from_record(
            divorce_rec,
            f"{side}_full_name" if side else "spouse_full_name",
            (f"{side}_name" if side else "spouse_name", "spouse_full_name", "spouse_name"),
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
            applicant = _resolve_from_record_luong1_fallback(
                passport_rec, passport_ref, "full_name", ("name",)
            )
            for part in parts:
                if applicant and _names_match(applicant, part):
                    continue
                ex_full = _strip_person_title(part)
                break
    return ex_full


def _marriage_is_the_divorced_one(
    marriage_rec: ApplicantDocRecord | None,
    marriage_ref: ApplicantDocRecord | None,
    divorce_rec: ApplicantDocRecord | None,
    passport_rec: ApplicantDocRecord | None,
    passport_ref: ApplicantDocRecord | None = None,
) -> bool:
    """True nếu vợ/chồng trên giấy kết hôn đang xét TRÙNG với người đã ly hôn trên quyết định ly
    hôn VÀ ngày kết hôn KHÔNG sau ngày ly hôn — tức đây chính là cuộc hôn nhân đã chấm dứt.

    False nghĩa là:
    1) Chủ hồ sơ đã tái hôn với người khác sau ly hôn cũ: giấy kết hôn đang xét là
    hôn nhân hiện tại (Married), giấy ly hôn chỉ mô tả cuộc hôn nhân trước (Previous Spouse).
    2) Hoặc chủ hồ sơ tái hôn lại với cùng người đó sau khi đã ly hôn (marriage_date > divorce_date).
    """
    if not divorce_rec:
        return False
    primary = marriage_rec or marriage_ref
    if not primary:
        return False
    ex_full = _divorce_ex_spouse_full_name(divorce_rec, passport_rec, passport_ref)
    if not ex_full:
        return True
    current_spouse_full = _spouse_field_from_marriage(
        marriage_rec, passport_rec, "full_name", marriage_ref=marriage_ref, passport_ref=passport_ref
    )
    if not current_spouse_full:
        return True
    if not _names_same_person(ex_full, current_spouse_full):
        return False

    # Nếu cùng tên người, kiểm tra ngày: Nếu ngày kết hôn SAU ngày ly hôn (tái hôn lại cùng người)
    # thì giấy kết hôn này là cuộc hôn nhân hiện tại (False - không phải cuộc hôn nhân đã ly hôn trước đó).
    from app.services.ds260_dates import parse_date_lenient

    m_date_raw = _resolve_from_record(primary, "marriage_date", ("date_of_marriage", "date"))
    d_date_raw = _resolve_from_record(
        divorce_rec, "divorce_date", ("date_of_divorce", "decision_date", "effective_date", "issue_date", "date")
    )
    if m_date_raw and d_date_raw:
        m_parsed = parse_date_lenient(m_date_raw)
        d_parsed = parse_date_lenient(d_date_raw)
        if m_parsed and d_parsed:
            m_dt, _ = m_parsed
            d_dt, _ = d_parsed
            if m_dt > d_dt:
                return False

    return True


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


def _reset_divorce_section_fields(fields_out: list[dict[str, Any]]) -> None:
    """Không có giấy ly hôn hợp lệ — previous_spouses_used=No, các trường khác trống."""
    for field in fields_out:
        key = field.get("key", "")
        if key == "previous_spouses_used":
            field["value"] = "No"
        else:
            field["value"] = ""
        field["source"] = empty_ds260_field_source()


def reconcile_previous_spouse_with_marital_status(sections_out: list[dict[str, Any]]) -> None:
    """Previous Spouse section chỉ có ý nghĩa khi đã từng có hôn nhân HỢP PHÁP kết thúc (ly hôn/
    goá). current_marital_status CUỐI CÙNG (sau conflict resolution + manual override — không
    phải giá trị lúc enrich_previous_spouse_from_divorce/_from_death chạy, sớm hơn trong pipeline
    và có thể bị ghi đè sau đó) = Single nghĩa là hôn nhân chưa từng đăng ký hợp pháp (vd. "tự
    nguyện chung sống", xem enrich_marital_status_from_documents) → xoá phần Previous Spouse đã
    lỡ điền, nếu không Single vẫn hiện "Previous Spouse: Yes" kèm tên/ngày sinh vợ/chồng cũ —
    mâu thuẫn logic (khách báo lỗi thực tế). Chỉ gate trên "Single" — Divorced/Widowed giữ
    nguyên Previous Spouse (không xoá nhầm, xem test_ds260_widow_death.py)."""
    final_status = ""
    for sec in sections_out:
        for field in sec.get("fields", []):
            if field.get("key") == "current_marital_status":
                final_status = (field.get("value") or "").strip()
                break
    if final_status != "Single":
        return
    for sec in sections_out:
        if sec.get("id") == "section_previous_spouse":
            _reset_divorce_section_fields(sec["fields"])


@lru_cache(maxsize=1)
def _child_excluded_section_ids() -> frozenset[str]:
    """Các mục DS-260 không áp dụng cho hồ sơ con (chỉ người lớn — vợ/chồng, ly hôn, phối ngẫu cũ).

    Mục con cái (section_children) VẪN HIỂN THỊ và tự động điền children_used = 'No'.
    Mục học vấn/việc làm (section_work_education) VẪN HIỂN THỊ cho con (học sinh/sinh viên).
    """
    return frozenset({
        "section_spouse",
        "section_divorce",
        "section_previous_spouse",
    })


@lru_cache(maxsize=1)
def _child_own_birth_cert_section_ids() -> frozenset[str]:
    """Hồ sơ con — cha/mẹ/GKS lấy từ birth_certificate_child của chính con."""
    return frozenset({"section_father", "section_mother", "section_birth_certificate"})


def clear_child_adult_only_ds260_sections(sections_out: list[dict[str, Any]]) -> None:
    """Hồ sơ con — không điền phối ngẫu, ly hôn. Mục con cái vẫn hiển thị và đặt children_used = 'No'."""
    excluded = _child_excluded_section_ids()
    for sec in sections_out:
        if sec["id"] in excluded:
            for field in sec["fields"]:
                field["value"] = ""
                field["source"] = empty_ds260_field_source()
        elif sec["id"] == "section_children":
            for field in sec["fields"]:
                k = field.get("key", "")
                if k == "children_used":
                    field["value"] = "No"
                    field["source"] = {
                        **empty_ds260_field_source(),
                        "derived": "child_default_no_children",
                    }
                else:
                    field["value"] = ""
                    field["source"] = empty_ds260_field_source()
        elif sec["id"] == "section_a_personal":
            for field in sec["fields"]:
                if field.get("key") == "current_marital_status":
                    field["value"] = "Single"
                    field["source"] = {
                        **empty_ds260_field_source(),
                        "derived": "child_default_single",
                    }


def _spouse_name_from_marriage(
    marriage_rec: ApplicantDocRecord | None,
    passport_rec: ApplicantDocRecord | None,
) -> str:
    if not marriage_rec:
        return ""
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


def _occupation_from_worksheet_record(rec: ApplicantDocRecord | None) -> dict[str, str]:
    if not rec:
        return {}
    ws_data = normalize_ds260_customer_raw(_merge_raw_dict(rec))
    primary_occ = (
        (ws_data.get("work_primary_occupation") or "")
        or (ws_data.get("primary_occupation") or "")
        or (ws_data.get("occupation") or "")
        or (ws_data.get("employment.primary_occupation") or "")
        or (ws_data.get("present_job_title") or "")
        or (ws_data.get("job_title") or "")
    ).strip()
    other_occ = (
        (ws_data.get("work_occupation_other_specify") or "")
        or (ws_data.get("occupation_other_specify") or "")
        or (ws_data.get("employment.occupation_other_specify") or "")
        or (ws_data.get("other_occupation") or "")
    ).strip()
    out: dict[str, str] = {}
    if primary_occ:
        out["spouse_occupation"] = primary_occ
    if other_occ:
        out["spouse_occupation_other"] = other_occ
    return out


def pick_spouse_worksheet(
    records: list[ApplicantDocRecord],
    spouse_name: str,
    person_name: str | None = None,
) -> ApplicantDocRecord | None:
    """Tìm worksheet DS-260 của người phối ngẫu trong danh sách records."""
    worksheets = [r for r in records if r.doc_type == "ds260_customer_form"]
    if not worksheets:
        return None

    # 1. Khớp theo tên người trên worksheet
    if spouse_name:
        for r in worksheets:
            pname = _worksheet_person_name(r)
            if pname and _names_same_person(pname, spouse_name):
                return r
        for r in worksheets:
            raw = _merge_raw_dict(r)
            for k in ("applicant_name_native", "applicant_name", "full_name", "name"):
                val = (raw.get(k) or "").strip()
                if val:
                    val_clean = re.sub(r"(?i)^ds[\s-]*260[\s:_-]*", "", val).strip()
                    if _names_same_person(val_clean, spouse_name):
                        return r

    # 2. Nếu có 2 worksheet và biết person_name của đương đơn hiện tại -> lấy worksheet còn lại
    if person_name and len(worksheets) == 2:
        other = [
            r for r in worksheets
            if not _names_same_person(_worksheet_person_name(r), person_name)
        ]
        if len(other) == 1:
            return other[0]

    return None


def enrich_spouse_occupation_from_spouse_records(
    fields_out: list[dict[str, Any]],
    records: list[ApplicantDocRecord],
    spouse_name: str,
    person_name: str | None = None,
) -> None:
    """Bổ sung nghề nghiệp phối ngẫu từ worksheet / giấy việc làm / đơn xin việc của phối ngẫu trong cùng case."""
    spouse_ws = pick_spouse_worksheet(records, spouse_name, person_name=person_name)
    from_ws = _occupation_from_worksheet_record(spouse_ws)

    from_emp: dict[str, str] = {}
    emp_rec = None
    if spouse_name:
        for doc_t in ("employment_letter", "application_form"):
            for r in records:
                if r.doc_type != doc_t:
                    continue
                name_on_doc = _person_name_on_record(r)
                if name_on_doc and _names_same_person(name_on_doc, spouse_name):
                    emp_rec = r
                    from_emp = _occupation_from_employment_record(r)
                    break
            if from_emp:
                break

    merged = _merge_occupation_fields(from_emp, from_ws)
    if not merged:
        return

    for field in fields_out:
        key = field.get("key", "")
        val = (merged.get(key) or "").strip()
        if not val:
            continue
        if (field.get("value") or "").strip():
            continue
        field["value"] = val
        field.setdefault("source", {})
        used_rec = spouse_ws if key in from_ws else emp_rec
        doc_type = used_rec.doc_type if used_rec else "ds260_customer_form"
        field["source"]["document_type"] = doc_type
        field["source"]["source_field"] = (
            "work_primary_occupation" if key == "spouse_occupation" else "work_occupation_other_specify"
        )
        field["source"]["derived"] = "spouse_occupation_from_spouse_ds260"
        if used_rec:
            if getattr(used_rec, "source_document_id", None):
                field["source"]["document_id"] = str(used_rec.source_document_id)
            if getattr(used_rec, "id", None):
                field["source"]["record_id"] = str(used_rec.id)


def sync_spouse_fields_from_spouse_records(
    fields_out: list[dict[str, Any]],
    records: list[ApplicantDocRecord],
    spouse_name: str,
    person_name: str | None = None,
) -> None:
    """Sync ALL spouse fields từ worksheet và passport của vợ/chồng trong cùng case (City/State/Country nơi sinh, Địa chỉ, DOB, Nghề nghiệp)."""
    from app.services.birth_location import (
        derive_birth_state_from_place,
        derive_city_from_place,
        derive_country_from_place,
        format_address_english,
        format_birth_city_display,
        format_nationality_country,
        format_place_name_title,
    )

    # 1. Thu thập dữ liệu từ worksheet của spouse
    spouse_ws = pick_spouse_worksheet(records, spouse_name, person_name=person_name)
    spouse_data = normalize_ds260_customer_raw(_merge_raw_dict(spouse_ws)) if spouse_ws else {}

    # 2. Thu thập dữ liệu từ passport của spouse (nếu có trong case) - Hộ chiếu là nguồn chính thức
    spouse_pp, _ = (
        pick_luong1_pair_for_person(records, "passport", spouse_name)
        if spouse_name
        else (None, None)
    )
    if spouse_pp:
        pp_pob = _resolve_from_record(spouse_pp, "place_of_birth", ("birth_place",))
        if pp_pob:
            pp_state = derive_birth_state_from_place(pp_pob)
            pp_city = derive_city_from_place(pp_pob)
            pp_country = derive_country_from_place(pp_pob) or "Vietnam"
            if pp_state:
                spouse_data["birth_state"] = pp_state
            if pp_city:
                spouse_data["birth_city"] = pp_city
            if pp_country:
                spouse_data["birth_country"] = pp_country
        pp_dob = _resolve_from_record(spouse_pp, "date_of_birth", ("dob",))
        if pp_dob:
            spouse_data["date_of_birth"] = pp_dob

    # 3. Chuẩn hóa họ tên phối ngẫu
    full_name_cand = (spouse_data.get("applicant_name") or spouse_data.get("full_name") or spouse_name or "").strip()
    if full_name_cand:
        sur, given = _split_vn_person_name(full_name_cand)
        if sur:
            spouse_data["family_name"] = sur
        if given:
            spouse_data["given_names"] = given

    # 4. Tự động trích xuất City/State/Country nếu worksheet ghi chung nơi sinh dạng chuỗi
    pob = (spouse_data.get("place_of_birth") or spouse_data.get("birth_place") or "").strip()
    if pob:
        if not spouse_data.get("birth_city"):
            derived_city = derive_city_from_place(pob)
            if derived_city:
                spouse_data["birth_city"] = derived_city
        if not spouse_data.get("birth_state"):
            derived_state = derive_birth_state_from_place(pob)
            if derived_state:
                spouse_data["birth_state"] = derived_state
        if not spouse_data.get("birth_country"):
            derived_country = derive_country_from_place(pob)
            if derived_country:
                spouse_data["birth_country"] = derived_country

    spouse_field_map = {
        "spouse_full_name": ("full_name", "name", "applicant_name", "applicant_name_native"),
        "spouse_surname": ("family_name", "surname"),
        "spouse_given_names": ("given_names", "first_name"),
        "spouse_date_of_birth": ("date_of_birth", "dob"),
        "spouse_birth_city": ("birth_city", "city_of_birth", "birth_place_city", "place_of_birth"),
        "spouse_birth_state": ("birth_state", "state_of_birth", "province_of_birth", "birth_place_state"),
        "spouse_birth_country": ("birth_country", "country_of_birth", "nationality"),
        "spouse_address": ("current_address", "address", "residence_address", "street_address", "present_address", "living_address"),
        "spouse_occupation": ("work_primary_occupation", "primary_occupation", "occupation", "employment.primary_occupation"),
        "spouse_occupation_other": ("work_occupation_other_specify", "occupation_other_specify", "employment.occupation_other_specify"),
    }

    for field in fields_out:
        key = field.get("key", "")
        if key not in spouse_field_map:
            continue

        # Cho phép ghi đè nếu field đang trống HOẶC đang lấy từ marriage_certificate / birth_certificate (dữ liệu cũ/chưa chuẩn hóa)
        src_doc = (field.get("source") or {}).get("document_type", "")
        is_weak_source = src_doc in ("marriage_certificate", "birth_certificate", "")
        if (field.get("value") or "").strip() and not is_weak_source:
            continue

        for src_key in spouse_field_map[key]:
            val = (spouse_data.get(src_key) or "").strip()
            if val:
                if key == "spouse_address":
                    val = format_address_english(val)
                elif key == "spouse_birth_city":
                    val = format_birth_city_display(val)
                elif key == "spouse_birth_state":
                    val = format_place_name_title(val)
                elif key == "spouse_birth_country":
                    val = format_nationality_country(val)

                field["value"] = val
                field.setdefault("source", {})
                field["source"]["document_type"] = "ds260_customer_form" if spouse_ws else ("passport" if spouse_pp else "spouse_member_sync")
                field["source"]["source_field"] = src_key
                field["source"]["derived"] = (
                    "spouse_occupation_from_spouse_ds260"
                    if key in ("spouse_occupation", "spouse_occupation_other")
                    else "spouse_fields_synced"
                )
                if spouse_ws and getattr(spouse_ws, "source_document_id", None):
                    field["source"]["document_id"] = str(spouse_ws.source_document_id)
                elif spouse_pp and getattr(spouse_pp, "source_document_id", None):
                    field["source"]["document_id"] = str(spouse_pp.source_document_id)
                if spouse_ws and getattr(spouse_ws, "id", None):
                    field["source"]["record_id"] = str(spouse_ws.id)
                break


async def read_spouse_occupation_from_applicant(
    db: AsyncSession,
    spouse_applicant_id,
) -> dict[str, str]:
    """Nghề nghiệp phối ngẫu từ DS-260 worksheet / profile / employment letter."""
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

    ws_rec = pick_latest_by_variant(recs, "ds260_customer_form", "exception") or pick_latest_record(
        recs, "ds260_customer_form"
    )
    from_worksheet = _occupation_from_worksheet_record(ws_rec)

    emp_rec = pick_latest_record(recs, "employment_letter")
    from_emp = _occupation_from_employment_record(emp_rec)

    # Merge: worksheet > employment letter > profile
    merged = _merge_occupation_fields(from_profile, from_emp)
    return _merge_occupation_fields(from_worksheet, merged)


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


async def sync_spouse_fields_from_spouse_applicant(
    fields_out: list[dict[str, Any]],
    db: AsyncSession,
    current: Applicant,
    marriage_rec: ApplicantDocRecord | None,
    passport_rec: ApplicantDocRecord | None,
) -> None:
    """Sync ALL spouse fields từ DS-260 của vợ/chồng vào section_spouse của principal.

    Khi principal và spouse đi chung (family case), thông tin spouse trên DS-260 của
    principal phải đồng bộ với thông tin cá nhân thật của spouse từ DS-260 worksheet của họ.

    Fields sync: full_name, surname, given_names, date_of_birth, birth_city, birth_state,
    birth_country, occupation.
    """
    import logging
    logger = logging.getLogger(__name__)

    spouse_app = await find_spouse_applicant(db, current, marriage_rec, passport_rec)
    if not spouse_app:
        logger.info(f"[SYNC_SPOUSE] Cannot find spouse applicant for {current.display_name}")
        return

    logger.info(f"[SYNC_SPOUSE] Found spouse: {spouse_app.display_name} (id={spouse_app.id})")

    # Lấy DS-260 form của spouse
    spouse_recs = await list_doc_records(db, spouse_app.id)
    spouse_ws = pick_latest_by_variant(spouse_recs, "ds260_customer_form", "exception") or pick_latest_record(
        spouse_recs, "ds260_customer_form"
    )
    if not spouse_ws:
        logger.info(f"[SYNC_SPOUSE] No DS-260 worksheet found for spouse {spouse_app.display_name}")
        return

    spouse_data = normalize_ds260_customer_raw(_merge_raw_dict(spouse_ws))
    logger.info(f"[SYNC_SPOUSE] Spouse worksheet data keys: {list(spouse_data.keys())}")
    logger.info(f"[SYNC_SPOUSE] Spouse occupation values: primary_occupation={spouse_data.get('primary_occupation')}, work_primary_occupation={spouse_data.get('work_primary_occupation')}")

    from app.services.birth_location import (
        derive_birth_state_from_place,
        derive_city_from_place,
        derive_country_from_place,
        format_address_english,
    )

    pob = (spouse_data.get("place_of_birth") or spouse_data.get("birth_place") or "").strip()
    if pob:
        if not spouse_data.get("birth_city"):
            derived_city = derive_city_from_place(pob)
            if derived_city:
                spouse_data["birth_city"] = derived_city
        if not spouse_data.get("birth_state"):
            derived_state = derive_birth_state_from_place(pob)
            if derived_state:
                spouse_data["birth_state"] = derived_state
        if not spouse_data.get("birth_country"):
            derived_country = derive_country_from_place(pob)
            if derived_country:
                spouse_data["birth_country"] = derived_country

    # Mapping: principal's spouse_* key -> spouse's field key trong DS-260 worksheet
    spouse_field_map = {
        "spouse_full_name": ("full_name", "name", "applicant_name", "applicant_name_native"),
        "spouse_surname": ("family_name", "surname"),
        "spouse_given_names": ("given_names", "first_name"),
        "spouse_date_of_birth": ("date_of_birth", "dob"),
        "spouse_birth_city": ("birth_city", "city_of_birth", "birth_place_city", "place_of_birth"),
        "spouse_birth_state": ("birth_state", "state_of_birth", "province_of_birth", "birth_place_state"),
        "spouse_birth_country": ("birth_country", "country_of_birth", "nationality"),
        "spouse_address": ("current_address", "address", "residence_address", "street_address", "present_address", "living_address"),
        # Occupation: thử cả key gốc OCR lẫn key sau normalize
        "spouse_occupation": ("work_primary_occupation", "primary_occupation", "occupation", "employment.primary_occupation"),
        "spouse_occupation_other": ("work_occupation_other_specify", "occupation_other_specify", "employment.occupation_other_specify"),
    }

    for field in fields_out:
        key = field.get("key", "")
        if key not in spouse_field_map:
            continue

        # Bỏ qua nếu đã có giá trị (worksheet giữ quyền ưu tiên)
        if (field.get("value") or "").strip():
            continue

        # Thử các keys theo thứ tự ưu tiên
        for src_key in spouse_field_map[key]:
            val = (spouse_data.get(src_key) or "").strip()
            if val:
                if key == "spouse_address":
                    val = format_address_english(val)
                field["value"] = val
                field.setdefault("source", {})
                field["source"]["document_type"] = "ds260_customer_form"
                field["source"]["source_field"] = src_key
                field["source"]["derived"] = (
                    "spouse_occupation_from_spouse_ds260"
                    if key in ("spouse_occupation", "spouse_occupation_other")
                    else "spouse_fields_synced"
                )
                field["source"]["spouse_applicant_id"] = str(spouse_app.id)
                if getattr(spouse_ws, "source_document_id", None):
                    field["source"]["document_id"] = str(spouse_ws.source_document_id)
                if getattr(spouse_ws, "id", None):
                    field["source"]["record_id"] = str(spouse_ws.id)
                break


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


def enrich_divorce_section_from_record(
    fields_out: list[dict[str, Any]],
    divorce_rec: ApplicantDocRecord | None,
) -> None:
    """Điền section ly hôn từ quyết định ly hôn (không lấy worksheet)."""
    if not divorce_rec:
        _reset_divorce_section_fields(fields_out)
        return
    derived = {
        "divorce_husband_name": _strip_person_title(
            _resolve_from_record(divorce_rec, "husband_full_name", ("husband_name",))
        ),
        "divorce_wife_name": _strip_person_title(
            _resolve_from_record(divorce_rec, "wife_full_name", ("wife_name",))
        ),
        "divorce_marriage_date": _resolve_from_record(
            divorce_rec, "marriage_date", ("date_of_marriage",)
        ),
        "divorce_date": _resolve_from_record(divorce_rec, "divorce_date", ()),
        "divorce_document_number": _resolve_from_record(
            divorce_rec, "document_number", ("certificate_number",)
        ),
    }
    for field in fields_out:
        key = field.get("key", "")
        val = (derived.get(key) or "").strip()
        if not val:
            continue
        field["value"] = val
        field.setdefault("source", {})
        field["source"]["document_type"] = "divorce"
        field["source"]["source_field"] = key
        field["source"]["derived"] = "divorce_from_decree"


def enrich_previous_spouse_from_divorce(
    fields_out: list[dict[str, Any]],
    divorce_rec: ApplicantDocRecord | None,
    passport_rec: ApplicantDocRecord | None,
    *,
    is_same_person_remarried: bool = False,
) -> None:
    """Điền section phối ngẫu cũ từ quyết định ly hôn — chọn vợ/chồng không trùng chủ hồ sơ."""
    if not divorce_rec:
        _reset_divorce_section_fields(fields_out)
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

    applicant = ""
    if passport_rec:
        applicant = _resolve_from_record(passport_rec, "full_name", ("name",))
    if not ex_full or (applicant and _names_match(applicant, ex_full)):
        _reset_divorce_section_fields(fields_out)
        return

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


def enrich_previous_spouse_from_death(
    fields_out: list[dict[str, Any]],
    records: list[ApplicantDocRecord],
    passport_rec: ApplicantDocRecord | None,
    passport_ref: ApplicantDocRecord | None = None,
) -> None:
    """
    Hôn nhân kết thúc do phối ngẫu qua đời (không có giấy ly hôn) → khai phối ngẫu cũ
    từ giấy kết hôn + giấy báo tử (ngày mất dùng làm ngày kết thúc hôn nhân).
    """
    death_rec = pick_latest_record(records, "death_certificate")
    marriage_rec, marriage_ref = pick_luong1_pair(records, "marriage_certificate")
    primary = marriage_rec or marriage_ref
    if not death_rec or not primary or not _spouse_is_deceased(
        primary, passport_rec, passport_ref, death_rec
    ):
        _reset_divorce_section_fields(fields_out)
        return

    side = _pick_spouse_side_from_marriage(primary, passport_rec, passport_ref)
    spouse_name = _strip_person_title(
        _resolve_from_record(primary, f"{side}_full_name", (f"{side}_name",))
    )
    # Phối ngẫu QUA ĐỜI (không ly hôn): khai như phối ngẫu cũ, NHƯNG tuyệt đối KHÔNG
    # đưa ngày mất vào ô "Date of Divorce" (previous_divorce_date) — người goá KHÔNG ly hôn.
    # Mẫu ImmiPath không có ô "lý do/ngày kết thúc hôn nhân", nên để ô ly hôn TRỐNG;
    # tình trạng "Widowed" (marital status) + giấy báo tử đã thể hiện việc phối ngẫu đã mất.
    derived = {
        "previous_spouses_used": "Yes",
        "previous_spouse_full_name": spouse_name,
        "previous_spouse_date_of_birth": _resolve_from_record(
            primary, f"{side}_date_of_birth", ()
        ),
        "previous_marriage_date": _resolve_from_record(
            primary, "marriage_date", ("date_of_marriage",)
        ),
    }
    for field in fields_out:
        key = field.get("key", "")
        # Người goá không ly hôn → xóa mọi giá trị lỡ điền vào ô "Date of Divorce".
        if key == "previous_divorce_date":
            if (field.get("value") or "").strip():
                field["value"] = ""
                field.setdefault("source", {})
                field["source"]["derived"] = "previous_spouse_deceased_not_divorced"
            continue
        val = (derived.get(key) or "").strip()
        if val:
            field["value"] = val
            field.setdefault("source", {})
            field["source"]["document_type"] = "death_certificate"
            field["source"]["source_field"] = key
            field["source"]["derived"] = "previous_spouse_from_death"


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
    """Chỉ điền City/State nơi sinh từ passport khi worksheet CHƯA có cả hai — không được đè
    lên dữ liệu thật đã đọc từ worksheet.

    Trước đây hàm này ép City = State cho MỌI hồ sơ (kể cả khi cả hai đã có giá trị THẬT và
    KHÁC nhau từ worksheet, vd. City="Xã Vĩnh Lạc, Huyện Lục Yên, Tỉnh Yên Bái", State="Yên
    Bái"): nếu City ngắn hơn (chỉ "Vĩnh Lạc") thì việc ép State = City làm MẤT tên tỉnh thật,
    sau đó normalize_ds260_place_fields (chạy cuối pipeline, tự tách City/State đúng quy ước
    DS-260: TP trực thuộc TW → State=N/A, TP/thị xã thuộc tỉnh → State=tỉnh đó) không còn đủ
    dữ liệu để tách đúng và có thể match nhầm sang tỉnh khác (vd. "Vinh Lac" → "Vinh" của Nghệ
    An thay vì Yên Bái — xác nhận bằng test thực tế 2026-08-04). Việc tách City/State đúng quy
    ước đã có sẵn ở normalize_ds260_place_fields; hàm này chỉ còn nhiệm vụ fallback từ passport
    khi worksheet hoàn toàn không có dữ liệu.
    """
    by_key = {f.get("key", ""): f for f in fields_out}
    city_has_value = bool((by_key.get("birth_city", {}).get("value") or "").strip())
    state_has_value = bool((by_key.get("birth_state", {}).get("value") or "").strip())
    if city_has_value and state_has_value:
        # Cả hai đã có dữ liệu thật (worksheet/OCR) — có thể khác nhau và đều đúng (vd. City
        # là địa chỉ đầy đủ, State là tên tỉnh riêng). Không đè, để normalize_ds260_place_fields
        # tách đúng theo quy ước DS-260 từ chính hai giá trị thật này.
        return
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


_UNREGISTERED_MARRIAGE_PHRASES = (
    "tự nguyện chung sống",
    "tu nguyen chung song",
    "không đăng ký kết hôn",
    "khong dang ky ket hon",
    "không công nhận quan hệ vợ chồng",
    "khong cong nhan quan he vo chong",
    "không công nhận là vợ chồng",
)


def _divorce_text_blob(divorce_rec: ApplicantDocRecord) -> str:
    form = json.loads(divorce_rec.form_data or "{}")
    raw = json.loads(divorce_rec.raw_data or "{}")
    parts: list[str] = []
    for src in (raw, form):
        for v in src.values():
            if isinstance(v, str):
                parts.append(v)
    return " ".join(parts).lower()


def _divorce_marriage_was_registered(
    divorce_rec: ApplicantDocRecord,
    *,
    has_marriage_certificate: bool = False,
) -> bool:
    """True nếu giấy ly hôn cho thấy cuộc hôn nhân CÓ đăng ký — False nếu nội dung ghi "tự
    nguyện chung sống" / "không đăng ký kết hôn" / tòa "không công nhận quan hệ vợ chồng"
    (chưa từng đăng ký kết hôn hợp pháp).

    Giấy ly hôn không ghi ngày đăng ký kết hôn (giấy cũ/OCR thiếu trường này) KHÔNG được suy
    luôn là chưa đăng ký — phải kiểm tra thêm hồ sơ có giấy đăng ký kết hôn (cho đúng cuộc hôn
    nhân đã ly hôn đó) hay không: có giấy kết hôn → vẫn tính là đã đăng ký (Divorced); không có
    giấy kết hôn nào → mới coi là chưa đăng ký (Single). (Khách yêu cầu 2026-08-14.)"""
    blob = _divorce_text_blob(divorce_rec)
    if any(phrase in blob for phrase in _UNREGISTERED_MARRIAGE_PHRASES):
        return False
    marriage_date = _resolve_from_record(divorce_rec, "marriage_date", ("date_of_marriage",))
    if marriage_date.strip():
        return True
    return has_marriage_certificate


def enrich_marital_status_from_documents(
    fields_out: list[dict[str, Any]],
    divorce_rec: ApplicantDocRecord | None,
    *,
    marriage_rec: ApplicantDocRecord | None = None,
    marriage_ref: ApplicantDocRecord | None = None,
    passport_rec: ApplicantDocRecord | None = None,
    passport_ref: ApplicantDocRecord | None = None,
    death_rec: ApplicantDocRecord | None = None,
) -> None:
    """
    Ly hôn: giấy ly hôn ghi rõ ngày ĐĂNG KÝ kết hôn (cuộc hôn nhân từng hợp pháp) → Divorced.
    Giấy ly hôn ghi "tự nguyện chung sống" / "không đăng ký kết hôn" / tòa "không công nhận
    quan hệ vợ chồng" (chưa từng đăng ký kết hôn hợp pháp), hoặc không có ngày kết hôn nào
    được ghi nhận → Single. Kết hôn + phối ngẫu đã mất → Widowed. Kết hôn hợp lệ → Married.
    Không có giấy tờ → để trống. (Trước 2026-08-14 công ty quy ước ly hôn luôn khai "Single"
    bất kể có đăng ký hay không — nay tách theo tình trạng đăng ký thực tế theo yêu cầu mới.)

    Có cả giấy ly hôn LẪN giấy kết hôn: nếu vợ/chồng trên giấy kết hôn trùng người đã ly hôn
    → vẫn dùng kết quả Divorced/Single ở trên (giấy kết hôn đó chính là cuộc hôn nhân đã chấm
    dứt). Nếu KHÁC người (tái hôn) → giấy ly hôn chỉ mô tả cuộc hôn nhân trước, giấy kết hôn
    đang xét mới là hiện tại → Married/Widowed như bình thường (xem _marriage_is_the_divorced_one).
    """
    has_marriage_cert = has_applicable_marriage_certificate(
        marriage_rec, marriage_ref, passport_rec, passport_ref
    )
    remarried_after_divorce = bool(divorce_rec) and has_marriage_cert and not _marriage_is_the_divorced_one(
        marriage_rec, marriage_ref, divorce_rec, passport_rec, passport_ref
    )

    if divorce_rec and not remarried_after_divorce:
        # Không remarried => nếu có giấy kết hôn thì chắc chắn là cuộc hôn nhân đã ly hôn này
        # (nếu là người khác thì đã rơi vào remarried_after_divorce ở trên).
        if _divorce_marriage_was_registered(
            divorce_rec, has_marriage_certificate=has_marriage_cert
        ):
            status = "Divorced"
            derived = "marital_status_divorced_from_divorce"
        else:
            status = "Single"
            derived = "marital_status_single_unregistered_from_divorce"
        doc_type = "divorce"
    elif has_applicable_marriage_certificate(
        marriage_rec, marriage_ref, passport_rec, passport_ref
    ):
        if _spouse_is_deceased(
            marriage_rec or marriage_ref, passport_rec, passport_ref, death_rec
        ):
            status = "Widowed"
            derived = "marital_status_widowed_from_death"
            doc_type = "death_certificate"
        else:
            status = "Married"
            derived = "marital_status_from_marriage"
            doc_type = "marriage_certificate"
    else:
        for field in fields_out:
            if field.get("key") != "current_marital_status":
                continue
            field["value"] = ""
            field["source"] = empty_ds260_field_source()
        return

    for field in fields_out:
        if field.get("key") != "current_marital_status":
            continue
        field["value"] = status
        field.setdefault("source", {})
        field["source"]["document_type"] = doc_type
        field["source"]["source_field"] = "marital_status"
        field["source"]["derived"] = derived


_CHILD_YES_NO_VALUES = frozenset(
    {"yes", "no", "y", "n", "có", "co", "không", "khong", "true", "false", "0", "1"}
)


def _normalize_child_file_stem(filename: str) -> str:
    stem = Path(filename).stem.lower()
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return re.sub(r"\s+new$", "", stem).strip()


def _child_has_meaningful_data(data: dict[str, str]) -> bool:
    """Chỉ coi là một con khi có tên hợp lệ (tránh OCR rác / chỉ Có-Không / chỉ quốc gia)."""
    name = re.sub(r"\s+", " ", (data.get("full_name") or "").strip())
    if len(name) >= 2 and re.search(r"[A-Za-zÀ-ỹ]", name):
        if name.lower() not in _CHILD_YES_NO_VALUES:
            return True
    dob = (data.get("date_of_birth") or "").strip()
    if dob and name and len(name) >= 2:
        return True
    return False


def _worksheet_declares_no_children(ws_merged: dict[str, str]) -> bool:
    """Worksheet khai không có con (children_used=No hoặc children_count=0)."""
    used = (ws_merged.get("children_used") or "").strip().lower()
    count = (ws_merged.get("children_count") or "").strip()
    if used in {"no", "n", "không", "khong", "false"}:
        return True
    if count == "0":
        return True
    return False


def _child_is_plausible(
    data: dict[str, str],
    *,
    applicant_name: str = "",
) -> bool:
    """Loại tên trùng chủ hồ sơ / OCR rác trên form không có con."""
    if not _child_has_meaningful_data(data):
        return False
    name = (data.get("full_name") or "").strip()
    if applicant_name and _names_same_person(name, applicant_name):
        return False
    return True


def _latest_child_variant(
    recs: list[ApplicantDocRecord], variant: str
) -> ApplicantDocRecord | None:
    candidates = [r for r in recs if r.variant == variant]
    if not candidates:
        return None
    return max(candidates, key=lambda r: (r.updated_at or r.id, str(r.id)))


def group_child_birth_luong1_pairs(
    records: list[ApplicantDocRecord],
    filename_map: dict[str, str] | None = None,
) -> list[tuple[ApplicantDocRecord | None, ApplicantDocRecord | None]]:
    """
    Gộp standard + _new của cùng một giấy khai sinh con thành một cặp Luồng 1.
    Tránh đếm 2 file (mẫu + đối chiếu) thành 2 con riêng.
    """
    typed = [r for r in records if r.doc_type == "birth_certificate_child"]
    groups: dict[str, list[ApplicantDocRecord]] = {}
    ungrouped: list[ApplicantDocRecord] = []

    for rec in typed:
        fname = ""
        if rec.source_document_id and filename_map:
            fname = filename_map.get(str(rec.source_document_id), "")
        if fname:
            key = _normalize_child_file_stem(fname)
        else:
            data = _child_data_from_record(rec)
            name, dob = _child_dedupe_key(data)
            key = f"{name}|{dob}" if (name or dob) else ""
        if not key:
            ungrouped.append(rec)
            continue
        groups.setdefault(key, []).append(rec)

    pairs: list[tuple[ApplicantDocRecord | None, ApplicantDocRecord | None]] = []
    for recs in groups.values():
        pairs.append(
            (
                _latest_child_variant(recs, "standard"),
                _latest_child_variant(recs, "exception"),
            )
        )

    seen_ids: set[str] = set()
    for std, exc in pairs:
        for rec in (std, exc):
            if rec:
                seen_ids.add(str(rec.id))

    for rec in ungrouped:
        if str(rec.id) in seen_ids:
            continue
        if rec.variant == "standard":
            pairs.append((rec, None))
        else:
            pairs.append((None, rec))

    return pairs


def list_child_birth_records(
    records: list[ApplicantDocRecord],
    *,
    filename_map: dict[str, str] | None = None,
) -> list[ApplicantDocRecord]:
    """Mỗi con một bản đại diện (standard ưu tiên) — đã gộp cặp standard/_new."""
    out: list[ApplicantDocRecord] = []
    for std, exc in group_child_birth_luong1_pairs(records, filename_map):
        rep = std or exc
        if rep:
            out.append(rep)
    return sorted(out, key=lambda r: (r.updated_at or r.id, str(r.id)))


def _child_data_from_luong1_pair(
    standard: ApplicantDocRecord | None,
    reference: ApplicantDocRecord | None,
) -> dict[str, str]:
    full = _resolve_from_record_luong1_fallback(
        standard, reference, "child_full_name", ("full_name", "name")
    )
    dob = _resolve_from_record_luong1_fallback(
        standard, reference, "child_date_of_birth", ("date_of_birth", "dob")
    )
    pob = _resolve_from_record_luong1_fallback(
        standard, reference, "child_place_of_birth", ("place_of_birth",)
    )
    city = _resolve_from_record_luong1_fallback(
        standard, reference, "child_birth_city", ("birth_city",)
    )
    state = _resolve_from_record_luong1_fallback(
        standard, reference, "child_birth_state", ("birth_state",)
    )
    country = _resolve_from_record_luong1_fallback(
        standard, reference, "child_birth_country", ("birth_country",)
    )
    if not city and pob:
        city = derive_city_from_place(pob) or pob
    if not state and pob:
        state = derive_birth_state_from_place(pob) or ""
    if not country and pob:
        country = derive_country_from_place(pob) or ""
    father = _resolve_from_record_luong1_fallback(
        standard, reference, "father_name", ("father_full_name",)
    )
    mother = _resolve_from_record_luong1_fallback(
        standard, reference, "mother_name", ("mother_full_name",)
    )
    return {
        "full_name": full,
        "date_of_birth": dob,
        "birth_city": city,
        "birth_state": state,
        "birth_country": country,
        "father_name": father,
        "mother_name": mother,
        "lives_with": "",
        "current_address": "",
        "immigrating": "",
        "immigrating_future": "",
    }


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
        "father_name": _resolve_from_record(rec, "father_name", ("father_full_name",)),
        "mother_name": _resolve_from_record(rec, "mother_name", ("mother_full_name",)),
    }


def _child_dedupe_key(data: dict[str, str]) -> tuple[str, str]:
    """`.strip().upper()` KHÔNG bỏ dấu — giấy khai sinh ghi có dấu ("Nguyễn Minh Phương") còn
    worksheet khách khai thường gõ không dấu ("NGUYEN MINH PHUONG"), hai chuỗi khác nhau nên
    không dedupe được → cùng một con bị tính 2 lần, children_count dư ra dù hiển thị "trùng
    tên" trên form (form hiển thị đã qua bước bỏ dấu cuối pipeline nên nhìn giống hệt nhau —
    báo lỗi thực tế 2026-08-04). Dùng format_person_name_ascii (chỉ bỏ dấu, KHÔNG lọc từ hành
    chính như normalize_location — normalize_location từng cắt mất "Phương" vì trùng "phường").
    """
    from app.services.birth_location import format_person_name_ascii

    name = format_person_name_ascii(data.get("full_name") or "")
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
        full = (
            merged.get(f"{prefix}full_name")
            or (merged.get("child_full_name") if idx == 1 else "")
            or (merged.get(f"{prefix}name") if idx > 1 else "")
        )
        if idx == 1 and not full:
            full = merged.get("child_full_name", "") or merged.get("child_name", "")
        dob = (
            merged.get(f"{prefix}date_of_birth")
            or merged.get(f"{prefix}dob")
            or (merged.get("child_date_of_birth") if idx == 1 else "")
            or (merged.get("child_dob") if idx == 1 else "")
        )
        pob = (
            merged.get(f"{prefix}place_of_birth")
            or merged.get(f"{prefix}pob")
            or (merged.get("child_place_of_birth") if idx == 1 else "")
            or (merged.get("child_pob") if idx == 1 else "")
        )
        city = (
            merged.get(f"{prefix}birth_city")
            or merged.get(f"{prefix}city")
            or (merged.get("child_birth_city") if idx == 1 else "")
        )
        state = (
            merged.get(f"{prefix}birth_state")
            or merged.get(f"{prefix}state")
            or (merged.get("child_birth_state") if idx == 1 else "")
        )
        country = (
            merged.get(f"{prefix}birth_country")
            or merged.get(f"{prefix}country")
            or (merged.get("child_birth_country") if idx == 1 else "")
        )
        if not city and pob:
            city = derive_city_from_place(pob) or pob
        if not state and pob:
            state = derive_birth_state_from_place(pob) or ""
        if not country and (city or state or pob):
            country = derive_country_from_place(pob) or "Vietnam"
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
        if _child_has_meaningful_data(data):
            children.append(data)
    return children


def _apply_children_review_visibility(fields_out: list[dict[str, Any]]) -> None:
    """Ẩn slot con trống / vượt quá số con thực tế trên màn Review."""
    filled_slots: set[int] = set()
    children_used = ""
    for field in fields_out:
        key = field.get("key", "")
        if key == "children_used":
            children_used = (field.get("value") or "").strip()
        m = re.match(r"^child_(\d+)_full_name$", key)
        if m and (field.get("value") or "").strip():
            filled_slots.add(int(m.group(1)))

    max_slot = max(filled_slots) if filled_slots else 0
    has_children = max_slot > 0 or children_used.lower() in {"yes", "có", "co"}

    for field in fields_out:
        key = field.get("key", "")
        m = re.match(r"^child_(\d+)_", key)
        if not m:
            if key in {"children_used", "children_count"} and not has_children:
                if not (field.get("value") or "").strip():
                    field["value"] = "No" if key == "children_used" else "0"
            continue
        slot = int(m.group(1))
        if slot > max_slot or not has_children:
            field["value"] = ""
            field["source"] = empty_ds260_field_source()
            field["review_hidden"] = True


# Field chỉ có trên worksheet (giấy khai sinh không có) — phải gộp khi trùng con.
_CHILD_WORKSHEET_ONLY_FIELDS = ("lives_with", "current_address", "immigrating", "immigrating_future")


def _same_child(a: dict[str, str], b: dict[str, str]) -> bool:
    """Cùng một đứa trẻ khi TÊN khớp (dùng _names_same_person — chịu được có/không dấu, thứ tự
    chữ) — KHÔNG còn đòi hỏi ngày sinh khớp. Ngày sinh khác nhau giữa 2 nguồn (worksheet vs
    giấy khai sinh) là MÂU THUẪN DỮ LIỆU cần cảnh báo (xem build_child_identity_conflict_rows),
    không phải bằng chứng đây là 2 người khác nhau — trước đây so khớp cứng theo cả tên lẫn
    ngày sinh khiến 1 người bị tách thành 2 slot con khi một nguồn OCR đọc sai ngày (báo lỗi
    thực tế 2026-08-05: giấy khai sinh NGUYEN MINH PHUONG bị OCR đọc nhầm số quyển "208/2015"
    thành ngày sinh, trong khi hộ chiếu + worksheet đều ghi đúng 29/01/2007 — cùng 1 người bị
    hiện thành cả child_2 và child_3)."""
    name_a = (a.get("full_name") or "").strip()
    name_b = (b.get("full_name") or "").strip()
    return bool(name_a) and bool(name_b) and _names_same_person(name_a, name_b)


def _dedupe_children(
    items: list[tuple[dict[str, str], str, ApplicantDocRecord | None]],
) -> list[tuple[dict[str, str], str, ApplicantDocRecord | None]]:
    """Union birth certs + worksheet; prefer birth_certificate_child on duplicate,
    nhưng GỘP các field còn thiếu (lives_with, immigrating, birth_city, ...) từ worksheet vào bản đã giữ.
    So khớp theo _same_child (chỉ tên — xem docstring _same_child), KHÔNG dùng tuple (tên,
    ngày sinh) làm key từ điển như trước — cách đó tách 1 người thành 2 slot khi ngày sinh
    giữa 2 nguồn khác nhau (do OCR đọc sai ở một bên). Mâu thuẫn ngày sinh/nơi sinh giữa các
    nguồn được báo riêng qua build_child_identity_conflict_rows(), không xử lý ở đây."""
    priority = {"birth_certificate_child": 0, "ds260_customer_form": 1}
    ranked = sorted(items, key=lambda x: (priority.get(x[1], 9), _child_dedupe_key(x[0])))
    out: list[tuple[dict[str, str], str, ApplicantDocRecord | None]] = []
    for data, source, rec in ranked:
        key = _child_dedupe_key(data)
        if not key[0] and not key[1]:
            continue
        matched_idx = next(
            (i for i, (kept_data, _, _) in enumerate(out) if _same_child(data, kept_data)),
            None,
        )
        if matched_idx is not None:
            kept_data = out[matched_idx][0]
            for f, val in data.items():
                if not (kept_data.get(f) or "").strip() and (val or "").strip():
                    kept_data[f] = val
            continue
        out.append((data, source, rec))
    return out


_CHILD_IDENTITY_COMPARE_FIELDS: tuple[str, ...] = (
    "date_of_birth",
    "birth_city",
    "birth_state",
    "birth_country",
)


def _child_identity_values_equal(field: str, a: str, b: str) -> bool:
    if field == "date_of_birth":
        parsed_a, parsed_b = parse_full_date(a), parse_full_date(b)
        if parsed_a and parsed_b:
            return parsed_a == parsed_b
        return format_partial_ds260_date(a) == format_partial_ds260_date(b) or a.upper() == b.upper()
    return re.sub(r"\s+", " ", a.strip().upper()) == re.sub(r"\s+", " ", b.strip().upper())


def build_child_identity_conflict_rows(
    records: list[ApplicantDocRecord],
    resolutions: dict[str, str],
) -> list[dict[str, Any]]:
    """So sánh ngày sinh/nơi sinh của TỪNG CON (tên khớp qua _names_same_person) giữa các
    nguồn — giấy khai sinh con (birth_certificate_child) và worksheet DS-260 khách khai. Khi
    khác nhau → tạo Conflict để nhân viên chọn giá trị đúng, KHÔNG tách thành 2 slot con khác
    nhau (dedupe_children đã gộp theo tên — xem _same_child). Field_key khoá theo TÊN con
    (không theo vị trí slot child_1/child_2 — vị trí này đổi mỗi lần dữ liệu thay đổi nên
    không dùng làm khoá ổn định được).

    Báo lỗi thực tế 2026-08-05: giấy khai sinh NGUYEN MINH PHUONG bị OCR đọc nhầm số quyển
    "208/2015" thành ngày sinh; hộ chiếu + worksheet đều ghi đúng 29/01/2007. Trước đây không
    có cơ chế nào cảnh báo — 2 giá trị khác nhau chỉ âm thầm tách thành 2 "con" riêng biệt.
    """
    from app.services.ds260_conflicts import child_identity_conflict_field_key, pick_latest_by_variant

    items: list[tuple[dict[str, str], ApplicantDocRecord | None]] = []
    for std, ref in group_child_birth_luong1_pairs(records, None):
        data = _child_data_from_luong1_pair(std, ref)
        if (data.get("full_name") or "").strip():
            items.append((data, std or ref))

    ws_rec = pick_latest_by_variant(records, "ds260_customer_form", "exception") or pick_latest_record(
        records, "ds260_customer_form"
    )
    if ws_rec:
        for data in _child_data_from_worksheet(ws_rec):
            if (data.get("full_name") or "").strip():
                items.append((data, ws_rec))

    rows: list[dict[str, Any]] = []
    emitted: set[str] = set()
    for i in range(len(items)):
        data_a, rec_a = items[i]
        name_a = (data_a.get("full_name") or "").strip()
        for j in range(i + 1, len(items)):
            data_b, rec_b = items[j]
            name_b = (data_b.get("full_name") or "").strip()
            if not name_b or not _names_same_person(name_a, name_b):
                continue
            for field in _CHILD_IDENTITY_COMPARE_FIELDS:
                val_a = (data_a.get(field) or "").strip()
                val_b = (data_b.get(field) or "").strip()
                if not val_a or not val_b:
                    continue
                if _child_identity_values_equal(field, val_a, val_b):
                    continue
                fk = child_identity_conflict_field_key(name_a, field)
                if fk in resolutions or fk in emitted:
                    continue
                emitted.add(fk)
                rows.append(
                    {
                        "field_key": fk,
                        "value_a": format_ds260_display_date(val_a) if field == "date_of_birth" else val_a,
                        "document_a_id": rec_a.source_document_id if rec_a else None,
                        "value_b": format_ds260_display_date(val_b) if field == "date_of_birth" else val_b,
                        "document_b_id": rec_b.source_document_id if rec_b else None,
                    }
                )
    return rows


def _child_worksheet_record_for_member(
    records: list[ApplicantDocRecord],
    member_display_name: str,
) -> ApplicantDocRecord | None:
    candidates = [r for r in records if r.doc_type == "ds260_customer_form"]
    for r in candidates:
        if _names_same_person(_worksheet_person_name(r), member_display_name):
            return r
    return None


async def build_child_parent_identity_conflict_rows(
    db: AsyncSession, applicant_id, resolutions: dict[str, str]
) -> list[dict[str, Any]]:
    """So sánh ngày sinh/quốc gia sinh của cha/mẹ — khai trên WORKSHEET CỦA CHÍNH NGƯỜI CON —
    với hồ sơ THẬT của người đó, CHỈ KHI cha/mẹ này CŨNG là một case member trong cùng bộ hồ sơ
    (vd. mẹ chính là đương đơn chính). Chỉ so khi CẢ HAI bên đều có dữ liệu — thiếu bên nào thì
    bỏ qua, không đoán mò (đúng yêu cầu thực tế 2026-08-05: "thông tin nào không có thì thôi
    chớ có là phải đối chiếu liền").

    Phạm vi so sánh: date_of_birth + birth_country (city/state từ hộ chiếu phải suy ra từ chuỗi
    place_of_birth tự do — độ tin cậy thấp hơn, dễ báo sai — nên KHÔNG đưa vào so sánh tự động
    ở đây, chỉ so 2 field đọc trực tiếp/đáng tin cậy nhất).
    """
    from app.services.birth_location import derive_country_from_place
    from app.services.family_case import load_case_members
    from app.services.ds260_conflicts import child_parent_identity_conflict_field_key

    records = await list_doc_records(db, applicant_id)
    members = await load_case_members(db, applicant_id)
    if len(members) < 2:
        return []

    rows: list[dict[str, Any]] = []
    for member in members:
        if str(member.role) not in ("child", "grandchild"):
            continue
        ws_rec = _child_worksheet_record_for_member(records, member.display_name)
        if not ws_rec:
            continue

        for parent in ("father", "mother"):
            surname = _resolve_from_record(ws_rec, f"{parent}_surname", ())
            given = _resolve_from_record(ws_rec, f"{parent}_given_names", ())
            parent_name = f"{surname} {given}".strip()
            if not parent_name:
                parent_name = _resolve_from_record(ws_rec, f"{parent}_full_name", ())
            if not parent_name:
                continue

            # Tìm case member khác có tên khớp với parent_name
            other = next(
                (
                    m
                    for m in members
                    if m.id != member.id and _names_same_person(parent_name, m.display_name)
                ),
                None,
            )
            if not other:
                continue

            passport_std, passport_ref = pick_luong1_pair_for_person(
                records, "passport", other.display_name
            )
            official_rec = passport_std or passport_ref
            if not official_rec:
                continue

            # Kiểm tra gender phù hợp với father/mother:
            # - father phải là Male/Nam
            # - mother phải là Female/Nữ
            # Nếu gender không phù hợp → bỏ qua, có thể là nhầm lẫn với người cùng tên
            official_gender = _resolve_from_record(official_rec, "gender", ("sex",)).upper()
            expected_genders = {"M", "MALE", "NAM"} if parent == "father" else {"F", "FEMALE", "NU", "NỮ"}
            if official_gender and official_gender not in expected_genders:
                # Gender không phù hợp → bỏ qua, không so sánh
                continue

            official_dob = _resolve_from_record(official_rec, "date_of_birth", ("dob",))
            official_pob = _resolve_from_record(official_rec, "place_of_birth", ("birth_place",))
            official_country = derive_country_from_place(official_pob) if official_pob else ""

            ws_dob = _resolve_from_record(ws_rec, f"{parent}_date_of_birth", ())
            ws_country = _resolve_from_record(ws_rec, f"{parent}_birth_country", ())

            for field, ws_val, official_val in (
                ("date_of_birth", ws_dob, official_dob),
                ("birth_country", ws_country, official_country),
            ):
                if not ws_val or not official_val:
                    continue
                if field == "date_of_birth":
                    parsed_ws, parsed_official = parse_full_date(ws_val), parse_full_date(official_val)
                    if parsed_ws and parsed_official:
                        equal = parsed_ws == parsed_official
                    else:
                        equal = ws_val.strip().upper() == official_val.strip().upper()
                else:
                    equal = ws_val.strip().upper() == official_val.strip().upper()
                if equal:
                    continue

                fk = child_parent_identity_conflict_field_key(member.display_name, parent, field)
                if fk in resolutions:
                    continue
                rows.append(
                    {
                        "field_key": fk,
                        "value_a": format_ds260_display_date(official_val) if field == "date_of_birth" else official_val,
                        "document_a_id": official_rec.source_document_id,
                        "value_b": format_ds260_display_date(ws_val) if field == "date_of_birth" else ws_val,
                        "document_b_id": ws_rec.source_document_id,
                    }
                )
    return rows


def enrich_children_section_from_birth_certs(
    fields_out: list[dict[str, Any]],
    child_records: list[ApplicantDocRecord],
    *,
    all_records: list[ApplicantDocRecord] | None = None,
    filename_map: dict[str, str] | None = None,
    case_members: list[Any] | None = None,
    applicant_name: str = "",
    member_role: str | None = None,
) -> None:
    """
    Union giấy khai sinh con + worksheet DS-260, dedupe, điền tối đa 4 slot.
    Mỗi giấy khai sinh: gộp standard + _new thành một con (Luồng 1).

    Cây gia phả: khi hồ sơ có nhánh phụ (cháu nội/ngoại hoặc anh/chị/em được bảo lãnh),
    GKS con chỉ tính cho người mà tên cha/mẹ trên GKS khớp với người đang xét — tránh
    con của người này hiển thị nhầm sang form người khác.
    """
    from app.services.ds260_conflicts import pick_latest_by_variant

    records = all_records if all_records is not None else child_records

    # Cây gia phả: GKS của cháu (nội/ngoại) cũng là birth_certificate_child — loại khỏi
    # mục "con" của chủ hồ sơ, vì cháu là con của thành viên 'child', không phải của chủ hồ sơ.
    grandchild_names = [
        (getattr(m, "display_name", None) or "").strip()
        for m in (case_members or [])
        if str(getattr(m, "role", "")) == "grandchild"
        and (getattr(m, "display_name", None) or "").strip()
    ]

    def _is_grandchild_record(data: dict[str, str]) -> bool:
        name = (data.get("full_name") or "").strip()
        return bool(name) and any(_names_same_person(name, gc) for gc in grandchild_names)

    # Có nhánh phụ → bắt buộc gán con theo tên cha/mẹ trên GKS để không lẫn nhánh.
    has_extra_branches = any(
        str(getattr(m, "role", "")) in ("grandchild", "sibling") for m in (case_members or [])
    )

    def _child_parent_matches(data: dict[str, str]) -> bool:
        if not applicant_name:
            return False
        return any(
            _names_same_person(data.get(key) or "", applicant_name)
            for key in ("father_name", "mother_name")
        )

    items: list[tuple[dict[str, str], str, ApplicantDocRecord | None]] = []
    for std, ref in group_child_birth_luong1_pairs(records, filename_map):
        data = _child_data_from_luong1_pair(std, ref)
        if _is_grandchild_record(data):
            continue
        if has_extra_branches and not _child_parent_matches(data):
            continue
        if _child_is_plausible(data, applicant_name=applicant_name):
            items.append((data, "birth_certificate_child", std or ref))

    # Con khai báo sẵn (case member role='child') chỉ thuộc chủ hồ sơ + phối ngẫu;
    # anh/chị/em hay cháu không nhận các con này vào form của họ.
    if case_members and member_role in (None, "principal", "spouse"):
        from app.services.family_case import pick_child_birth_cert_for_person

        seen_keys = {_child_dedupe_key(x[0]) for x in items}
        for member in case_members:
            role = getattr(member, "role", None)
            if role != "child" and str(role) != "child":
                continue
            name = (getattr(member, "display_name", None) or "").strip()
            if not name:
                continue
            bc = pick_child_birth_cert_for_person(records, name)
            if not bc:
                continue
            data = _child_data_from_record(bc)
            if not _child_is_plausible(data, applicant_name=applicant_name):
                continue
            key = _child_dedupe_key(data)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            items.append((data, "birth_certificate_child", bc))

    ws_rec = None
    if applicant_name:
        scoped_ws_records = scope_worksheets_to_person(records, applicant_name, is_family_case=True)
        ws_rec = pick_latest_by_variant(scoped_ws_records, "ds260_customer_form", "exception") or pick_latest_record(
            scoped_ws_records, "ds260_customer_form"
        )
    if not ws_rec:
        ws_rec = pick_latest_by_variant(records, "ds260_customer_form", "exception") or pick_latest_record(
            records, "ds260_customer_form"
        )
    ws_declared_count = ""
    ws_declares_no = False
    if ws_rec:
        ws_merged = _merge_raw_dict(ws_rec)
        ws_declared_count = (ws_merged.get("children_count") or "").strip()
        ws_declares_no = _worksheet_declares_no_children(ws_merged)
        birth_cert_count = sum(1 for _, src, _ in items if src == "birth_certificate_child")
        if not (ws_declares_no and birth_cert_count == 0):
            for data in _child_data_from_worksheet(ws_rec):
                if _is_grandchild_record(data):
                    continue
                if _child_is_plausible(data, applicant_name=applicant_name):
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
    if total:
        derived["children_used"] = "Yes"
        derived["children_count"] = str(total)
    elif ws_declares_no or ws_declared_count in {"", "0"}:
        derived["children_used"] = "No"
        derived["children_count"] = "0"

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

    _apply_children_review_visibility(fields_out)


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
        # KHÔNG dùng alias f"{parent}_city" — đó là THÀNH PHỐ NƠI THƯỜNG TRÚ (Residence) trên
        # giấy khai sinh, không phải nơi sinh của cha/mẹ. Giấy khai sinh VN chỉ ghi nơi thường
        # trú của cha/mẹ, KHÔNG ghi nơi sinh của họ — lấy nhầm residence làm birth city sẽ ra
        # kết quả sai (khách yêu cầu 2026-08-12: tránh đọc nơi thường trú ra thành nơi sinh cha).
        city = _resolve_from_record(
            record,
            f"{parent}_birth_city",
            (f"{parent}_city_of_birth",),
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
            # KHÔNG dùng alias f"{prefix}_country" — đó là QUỐC TỊCH (Nationality) trên giấy khai
            # sinh, không phải quốc gia nơi sinh của cha/mẹ. Giấy khai sinh VN chỉ ghi quốc tịch
            # hiện tại của cha/mẹ, KHÔNG ghi họ sinh ra ở nước nào — lấy nhầm quốc tịch làm birth
            # country sẽ ra kết quả sai (khách yêu cầu 2026-08-12: tránh đọc thông tin thường trú/
            # quốc tịch ra thành nơi sinh cha/mẹ). Chỉ nhận field EXPLICIT ghi rõ "nơi sinh".
            explicit = _resolve_from_record(record, f"{prefix}_birth_country", ())
            if explicit:
                mapped = derive_country_from_place(explicit)
                return mapped or explicit, f"{prefix}_birth_country"
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


def pick_luong1_pair(
    records: list[ApplicantDocRecord],
    doc_type: str,
) -> tuple[ApplicantDocRecord | None, ApplicantDocRecord | None]:
    """Luồng 1 (standard) và bản đối chiếu khách upload (_new / exception)."""
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

# Cha/mẹ: ưu tiên DS-260 worksheet (conf 1.0) trước birth certificate (conf thấp).
# BC chỉ dùng để đối chiếu, không phải nguồn chính.
_PARENT_NAME_KEYS: frozenset[str] = frozenset({
    "father_surname",
    "father_given_names",
    "father_full_name",
    "mother_surname",
    "mother_given_names",
    "mother_full_name",
})
_PARENT_BIRTH_KEYS: frozenset[str] = frozenset({
    "father_birth_city",
    "father_birth_state",
    "father_birth_country",
    "mother_birth_city",
    "mother_birth_state",
    "mother_birth_country",
})


def _person_name_on_record(rec: ApplicantDocRecord) -> str:
    if rec.doc_type == "birth_certificate_child":
        return _resolve_from_record(rec, "child_full_name", ("full_name", "name")) or ""
    return _resolve_from_record(rec, "full_name", ("name",)) or ""


def _worksheet_person_name(rec: ApplicantDocRecord) -> str:
    """Tên người trên worksheet DS-260 (bỏ tiền tố 'DS260', ưu tiên tên bản ngữ)."""
    merged = _merge_raw_dict(rec)
    for key in ("applicant_name_native", "applicant_name", "full_name", "name"):
        val = (merged.get(key) or "").strip()
        if val:
            val = re.sub(r"(?i)^ds[\s-]*260[\s:_-]*", "", val).strip()
            if val:
                return val
    return ""


def scope_worksheets_to_person(
    records: list[ApplicantDocRecord],
    person_name: str | None,
    *,
    is_family_case: bool = False,
) -> list[ApplicantDocRecord]:
    """
    Hồ sơ gia đình: mỗi thành viên có 1 worksheet DS-260 riêng. Chỉ giữ worksheet ĐÚNG NGƯỜI
    để field khách-khai (địa chỉ, cha mẹ, nghề nghiệp, con...) không lấy nhầm của thành viên khác.

    Hồ sơ gia đình (is_family_case=True) PHẢI fail-closed: khi không xác định được worksheet nào
    đúng người — kể cả khi cả hồ sơ chỉ có ĐÚNG 1 worksheet nhưng của người khác, hoặc không
    worksheet nào khớp tên — thì LOẠI HẾT worksheet ra thay vì trả nguyên vẹn. Trả nguyên vẹn
    (hành vi cũ) từng khiến field khách-khai (vd. applicant_name) của thành viên A bị điền nhầm
    dữ liệu của thành viên B khi B là người duy nhất đã có worksheet (báo lỗi thực tế 2026-08-12:
    Applicant Name của "NGUYEN HOANG YEN" — thành viên 02 — hiện ra "NGUYEN DANG DANG", tên của
    thành viên 01, vì hồ sơ lúc đó chỉ có 1 worksheet và nó thuộc về thành viên 01).

    Hồ sơ đơn (is_family_case=False, chỉ 1 người trong cả case) giữ nguyên hành vi cũ — 1
    worksheet nghiễm nhiên là của người đó, không cần khớp tên.
    """
    worksheets = [r for r in records if r.doc_type == "ds260_customer_form"]
    if not worksheets:
        return records
    if not is_family_case:
        return records
    name = (person_name or "").strip()
    matched = [r for r in worksheets if name and _names_same_person(_worksheet_person_name(r), name)]
    if matched:
        keep_ids = {id(r) for r in matched}
        return [r for r in records if r.doc_type != "ds260_customer_form" or id(r) in keep_ids]
    return [r for r in records if r.doc_type != "ds260_customer_form"]


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


# Bộ field "công việc HIỆN TẠI" (Primary Occupation/Present Employer + địa chỉ/job title/ngày
# bắt đầu đi kèm) — DS-260 khách khai (ds260_customer_form) LUÔN được ưu tiên hơn Application
# form cho nhóm này, vì khách có thể nộp Job Application cũ (mô tả công việc đã nghỉ) trong khi
# DS-260 tự khai mới hơn phản ánh đúng công việc hiện tại (vd. khách chuyển sang tự làm/nghề khác
# sau khi đã điền Application form). Việc làm cũ mà Application form liệt kê là "hiện tại" (do
# form không có trường ngày kết thúc) vẫn được giữ lại — nhưng chỉ qua work_other_occupation_detail
# (nguồn ds260_customer_form, xem ds260_mapping.json), không được ghi đè lên nghề nghiệp chính.
_WORK_CURRENT_JOB_KEYS: frozenset[str] = frozenset(
    {
        "work_primary_occupation",
        "work_occupation_other_specify",
        "work_present_employer",
        "work_employer_address",
        "work_employer_city",
        "work_employer_state",
        "work_employer_postal_code",
        "work_employer_country",
        "work_job_title",
        "work_start_date",
    }
)


# Application form thường tiếng Anh, DS-260 khách khai thường tiếng Việt — để so khớp được
# CÙNG một công việc/công ty dù viết 2 ngôn ngữ khác nhau (vd. "Công ty tư nhân của ông Tân
# Nguyên" ↔ "Private business of Mr. Tan Nguyen"), dịch các cụm/từ tiếng Việt thường gặp trong
# mục công việc sang 1 token tiếng Anh CHUNG trước khi tokenize để so khớp (khách yêu cầu
# 2026-08-13). Hiển thị cho người dùng vẫn dùng nguyên văn gốc của từng giấy tờ — bảng này CHỈ
# dùng nội bộ để SO SÁNH, không dùng để format giá trị hiển thị/export.
# Cụm dài xếp trước cụm ngắn để khớp đúng cụm trước khi rơi xuống từ đơn (vd. "cong ty" phải
# khớp trước khi "ty" một mình bị hiểu nhầm).
_JOB_VOCAB_VI_TO_EN: tuple[tuple[str, str], ...] = (
    ("cong ty tu nhan", "private company"),
    ("doanh nghiep tu nhan", "private company"),
    ("cong ty", "company"),
    ("tu nhan", "private"),
    ("nhan vien", "staff"),
    ("cong nhan", "worker"),
    ("quan ly", "manager"),
    ("quan li", "manager"),
    ("giam doc", "director"),
    ("chu doanh nghiep", "owner"),
    ("chu tiem", "owner"),
    ("chu cua hang", "owner"),
    ("kinh doanh", "business"),
    ("cua hang", "store"),
    ("tho may", "tailor"),
    ("ke toan", "accountant"),
    ("giao vien", "teacher"),
    ("bac si", "doctor"),
    ("y ta", "nurse"),
    ("tai xe", "driver"),
    ("lai xe", "driver"),
    ("ban hang", "sales"),
    ("san xuat", "production"),
    ("tu do", "freelance"),
    ("ong", "mr"),
    ("ba", "mrs"),
    ("chu", "owner"),
)


def _translate_job_vocab(accent_stripped_lower_text: str) -> str:
    """Thay các cụm/từ tiếng Việt thường gặp (đã bỏ dấu, chữ thường) sang token tiếng Anh chung
    — dùng trước khi tokenize trong _job_identity_tokens() để so khớp xuyên ngôn ngữ."""
    text = accent_stripped_lower_text
    for vi, en in _JOB_VOCAB_VI_TO_EN:
        text = re.sub(rf"\b{re.escape(vi)}\b", en, text)
    return text


def _job_identity_tokens(occupation: str, employer: str) -> set[str]:
    """Token hoá nghề nghiệp + tên công ty để so khớp mờ (khác cách viết HOẶC khác ngôn ngữ,
    cùng ý nghĩa) — dịch từ vựng VN→EN thường gặp trước khi tokenize (xem _JOB_VOCAB_VI_TO_EN)."""
    import unicodedata

    text = f"{occupation or ''} {employer or ''}"
    text = text.replace("Đ", "D").replace("đ", "d")
    text = "".join(ch for ch in unicodedata.normalize("NFD", text) if unicodedata.category(ch) != "Mn")
    text = _translate_job_vocab(text.lower())
    cleaned = re.sub(r"[^A-Za-z0-9\s]", " ", text.upper())
    stopwords = {"THE", "AND", "OF", "CO", "LTD", "INC", "TU", "VA", "CUA"}
    return {t for t in cleaned.split() if len(t) >= 2 and t not in stopwords}


def resolve_work_current_job_field(
    records: list[ApplicantDocRecord],
    mapping: Ds260FieldMapping,
    resolutions: dict[str, str],
    *,
    person_name: str | None = None,
) -> tuple[str, str, ApplicantDocRecord | None, dict[str, Any]]:
    """CHỈ lấy từ DS-260 khách khai — KHÔNG rơi về Application form (Luồng 1) nữa dù worksheet
    thiếu field. Phòng Docs yêu cầu 2026-08-13: 1 nguồn duy nhất (DS-260) để điền form, Application
    form chỉ dùng để ĐỐI CHIẾU/tạo Conflict (xem build_worksheet_conflict_rows trong
    ds260_conflicts.py) — trộn 2 nguồn vào cùng 1 field khiến việc so sánh/kiểm tra chéo khó khăn."""
    ws_value, ws_source_field, ws_rec, ws_extra = resolve_customer_form_field(
        records, "ds260_customer_form", mapping
    )
    return ws_value, ws_source_field, ws_rec, {**ws_extra, "derived": "ds260_worksheet_only"}


def resolve_work_prior_jobs_field(
    records: list[ApplicantDocRecord],
    mapping: Ds260FieldMapping,
    resolutions: dict[str, str],
    *,
    person_name: str | None = None,
) -> tuple[str, str, ApplicantDocRecord | None, dict[str, Any]]:
    """work_prior_jobs_history: CHỈ lấy từ DS-260 khách khai — cùng lý do resolve_work_current_job_field
    (khách yêu cầu 2026-08-13). Format lại thành từng entry 3 dòng + loại entry trùng công việc
    hiện tại từ CẢ worksheet VÀ Application form (xem format_prior_jobs_history_display) — giữ
    nguyên ngôn ngữ/dấu gốc của khách."""
    ws_value, ws_source_field, ws_rec, ws_extra = resolve_customer_form_field(
        records, "ds260_customer_form", mapping
    )
    if ws_value.strip():
        mappings = flatten_ds260_mappings()
        occ_val, *_ = resolve_work_current_job_field(
            records, mappings["work_primary_occupation"], resolutions, person_name=person_name
        )
        emp_val, *_ = resolve_work_current_job_field(
            records, mappings["work_present_employer"], resolutions, person_name=person_name
        )
        # Also read occupation/employer from Application form — trùng với BẤT KỲ nguồn nào
        # (worksheet hoặc application form) đều phải bỏ entry khỏi lịch sử.
        from app.services.ds260_conflicts import pick_latest_by_variant

        app_rec = pick_latest_by_variant(records, "application_form", "standard") or pick_latest_by_variant(
            records, "application_form", "exception"
        )
        app_occ_val, *_ = _resolve_ds260_field_value(mappings["work_primary_occupation"], app_rec) if app_rec else ("", "")
        app_emp_val, *_ = _resolve_ds260_field_value(mappings["work_present_employer"], app_rec) if app_rec else ("", "")
        ws_value = format_prior_jobs_history_display(
            ws_value,
            current_occupation=occ_val,
            current_employer=emp_val,
            app_current_occupation=app_occ_val,
            app_current_employer=app_emp_val,
        )
    return ws_value, ws_source_field, ws_rec, {**ws_extra, "derived": "ds260_worksheet_only"}


# --- Mốc thời gian việc làm (khách yêu cầu 2026-08-13) ---------------------------------------
# work_prior_jobs_history là 1 đoạn text TỰ DO (khách gõ tay, OCR ra), không có cấu trúc field
# cố định — 2 kiểu viết thường gặp: "01/01/2009 den 8/8/2018" (ngày-nối-ngày) và
# "Bat Dau Lam Tu Ngay 06/02/2019 Ket Thuc Vao Ngay 11/09/2020" (nhãn tách rời). Parser dưới đây
# là HEURISTIC (suy đoán tốt nhất có thể) dùng để tạo CẢNH BÁO cho người review đối chiếu lại
# giấy gốc — không phải căn cứ tuyệt đối để tự sửa dữ liệu.
_WORK_DATE_TOKEN_RE = re.compile(r"\d{1,2}[/.\-]\d{1,2}[/.\-]\d{4}|\d{4}-\d{2}-\d{2}")
_WORK_START_KEYWORDS = ("bat dau", "start", "tu ngay", "from")
_WORK_END_KEYWORDS = ("ket thuc", "end", "den ngay", " den ", " to ", "present", "hien tai", "hien nay", "den nay")
_WORK_OPEN_END_RE = re.compile(r"\bpresent\b|\bhien tai\b|\bhien nay\b|\bden nay\b", re.IGNORECASE)


def parse_work_periods_from_text(text: str) -> list[tuple[date, date | None]]:
    """Tìm các khoảng (ngày bắt đầu, ngày kết thúc) trong 1 đoạn work_prior_jobs_history tự do.
    Kết thúc = None nghĩa là khoảng MỞ (Present/hiện tại — hiếm gặp ở lịch sử việc làm CŨ nhưng
    vẫn xử lý phòng khi khách ghi nhầm công việc đang làm vào đây)."""
    from app.services.birth_location import _strip_accents

    if not (text or "").strip():
        return []
    plain = _strip_accents(text).lower()
    events: list[tuple[int, date | None, str]] = []
    for m in _WORK_DATE_TOKEN_RE.finditer(plain):
        d = parse_full_date(m.group(0))
        if not d:
            continue
        window = plain[max(0, m.start() - 30) : m.start()]
        if any(k in window for k in _WORK_END_KEYWORDS):
            events.append((m.start(), d, "end"))
        elif any(k in window for k in _WORK_START_KEYWORDS):
            events.append((m.start(), d, "start"))
        else:
            events.append((m.start(), d, "?"))
    for m in _WORK_OPEN_END_RE.finditer(plain):
        events.append((m.start(), None, "end"))
    events.sort(key=lambda e: e[0])

    periods: list[tuple[date, date | None]] = []
    pending: date | None = None
    for _pos, d, kind in events:
        if kind == "start":
            pending = d
        elif kind == "end":
            if pending is not None:
                periods.append((pending, d))
                pending = None
        else:  # không rõ nhãn — coi cụm đầu tiên chưa ghép là "start", cụm sau là "end"
            if pending is None:
                pending = d
            else:
                periods.append((pending, d))
                pending = None
    return periods


def _periods_overlap(a: tuple[date, date | None], b: tuple[date, date | None]) -> bool:
    a_start, a_end = a
    b_start, b_end = b
    a_end_eff = a_end or date.max
    b_end_eff = b_end or date.max
    return a_start <= b_end_eff and b_start <= a_end_eff


def detect_work_period_issues(
    records: list[ApplicantDocRecord],
    resolutions: dict[str, str],
    *,
    person_name: str | None,
) -> dict[str, Any]:
    """Phát hiện các vấn đề về mốc thời gian việc làm (khách yêu cầu 2026-08-13) — CẢNH BÁO cho
    người review, không phải lỗi cứng chặn export:

    - "start_after_signed": ngày bắt đầu công việc HIỆN TẠI sau ngày ký (Date signed) trên
      Application form — dấu hiệu khách ghi sai ngày.
    - "overlapping_periods": có ≥ 2 công việc (hiện tại + lịch sử) trùng thời điểm — khách có
      thể đã khai nhầm 2 việc cùng lúc.
    - "current_matches_closed_prior": công việc "hiện tại" (primary_occupation/present_employer)
      trùng công ty/nghề (so mờ, xuyên ngôn ngữ) với 1 entry ĐÃ CÓ ngày kết thúc trong lịch sử
      làm việc — nhiều khả năng khách ghi nhầm, việc đó thực ra đã nghỉ chứ không phải đang làm.
    """
    from app.services.ds260_conflicts import pick_latest_by_variant

    mappings = flatten_ds260_mappings()
    occ_val, *_ = resolve_work_current_job_field(
        records, mappings["work_primary_occupation"], resolutions, person_name=person_name
    )
    emp_val, *_ = resolve_work_current_job_field(
        records, mappings["work_present_employer"], resolutions, person_name=person_name
    )
    start_val, *_ = resolve_work_current_job_field(
        records, mappings["work_start_date"], resolutions, person_name=person_name
    )
    prior_val, *_ = resolve_work_prior_jobs_field(
        records, mappings["work_prior_jobs_history"], resolutions, person_name=person_name
    )

    current_start = parse_full_date(start_val) if start_val.strip() else None
    prior_periods = parse_work_periods_from_text(prior_val)

    out: dict[str, Any] = {}

    app_rec = pick_latest_by_variant(records, "application_form", "standard") or pick_latest_by_variant(
        records, "application_form", "exception"
    )
    date_signed_val = _resolve_from_record(app_rec, "date_signed", ()) if app_rec else ""
    date_signed = parse_full_date(date_signed_val) if date_signed_val.strip() else None
    if current_start and date_signed and current_start > date_signed:
        out["start_after_signed"] = {"start": start_val, "date_signed": date_signed_val}

    all_periods = list(prior_periods)
    if current_start:
        all_periods.append((current_start, None))
    overlaps: list[tuple[tuple[date, date | None], tuple[date, date | None]]] = []
    for i in range(len(all_periods)):
        for j in range(i + 1, len(all_periods)):
            if _periods_overlap(all_periods[i], all_periods[j]):
                overlaps.append((all_periods[i], all_periods[j]))
    if overlaps:
        out["overlapping_periods"] = overlaps

    if (occ_val.strip() or emp_val.strip()) and prior_val.strip():
        has_closed_period = any(end is not None for _start, end in prior_periods)
        if has_closed_period:
            cur_tokens = _job_identity_tokens(occ_val, emp_val)
            prior_tokens = _job_identity_tokens("", prior_val)
            if cur_tokens and prior_tokens:
                # Containment (không phải Jaccard đầy đủ): work_prior_jobs_history là 1 đoạn
                # narrative dài (nhãn, số điện thoại, ngày...) nên union sẽ luôn rất lớn — chỉ
                # cần token nhận diện công việc HIỆN TẠI (thường ngắn) xuất hiện phần lớn TRONG
                # narrative là đủ nghi ngờ trùng, không cần cả 2 bên tương đồng kích thước.
                containment = len(cur_tokens & prior_tokens) / len(cur_tokens)
                if containment >= 0.5:
                    out["current_matches_closed_prior"] = {"overlap_ratio": containment}

    return out


# --- Format lại work_prior_jobs_history: ngày lên đầu, mỗi entry 3 dòng, bỏ entry trùng công
# việc hiện tại (khách yêu cầu 2026-08-13) --------------------------------------------------
# Nhãn nhận diện ACCENT-INSENSITIVE (khớp cả có dấu/không dấu) nhưng LUÔN lấy lại chữ GỐC (giữ
# nguyên dấu/không dấu đúng như khách gõ) từ vị trí khớp — không dịch/không tự thêm dấu.
_PRIOR_JOB_LABEL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("start", re.compile(r"bat\s*dau\s*lam\s*tu\s*ngay|ngay\s*bat\s*dau|bat\s*dau|start\s*date|from\b", re.I)),
    ("end", re.compile(r"ket\s*thuc\s*vao\s*ngay|ngay\s*ket\s*thuc|ket\s*thuc|end\s*date|\bto\b", re.I)),
    ("company", re.compile(r"ten\s*cong\s*ty|ten\s*doanh\s*nghiep|company\s*name", re.I)),
    ("address", re.compile(r"dia\s*chi|address", re.I)),
    (
        "position",
        re.compile(r"vi\s*tri\s*lam\s*viec|vi\s*tri\s*cong\s*viec|vi\s*tri|position|chuc\s*danh|job\s*title", re.I),
    ),
    ("manager", re.compile(r"ten\s*nguoi\s*quan\s*ly|nguoi\s*quan\s*ly|supervisor|manager", re.I)),
    ("phone", re.compile(r"\bsdt\b|so\s*dien\s*thoai|\bphone\b|\btel\b", re.I)),
)

# Tách nhiều entry trong 1 khối text — mỗi entry đánh số "N." hoặc "N)" ở đầu dòng/sau ';'.
_PRIOR_JOB_ENTRY_SPLIT_RE = re.compile(r"(?:^|;|\n)\s*\d+[\.\)]\s*")


def _split_prior_job_entries(text: str) -> list[str]:
    raw = (text or "").strip()
    if not raw:
        return []
    parts = [p.strip(" ;\n") for p in _PRIOR_JOB_ENTRY_SPLIT_RE.split(raw) if p.strip(" ;\n")]
    return parts or [raw]


def _extract_prior_job_labeled_fields(entry: str) -> list[tuple[str, str, str]] | None:
    """[(label_type, nhãn_GỐC, giá_trị_GỐC), ...] theo thứ tự nhãn xuất hiện — giữ nguyên văn
    (dấu/không dấu) từ entry gốc, chỉ dùng bản bỏ dấu để TÌM vị trí nhãn. None nếu không nhận
    diện được nhãn nào (giữ nguyên entry gốc, không cố ép cấu trúc lên text lạ)."""
    from app.services.birth_location import _strip_accents

    plain = _strip_accents(entry).lower()
    hits: list[tuple[int, int, str]] = []
    for label_type, pattern in _PRIOR_JOB_LABEL_PATTERNS:
        for m in pattern.finditer(plain):
            hits.append((m.start(), m.end(), label_type))
    if not hits:
        return None
    hits.sort(key=lambda h: h[0])

    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for i, (start, label_end, label_type) in enumerate(hits):
        if label_type in seen:
            continue
        value_end = hits[i + 1][0] if i + 1 < len(hits) else len(entry)
        value = entry[label_end:value_end].strip(" \t:;.,\n")
        if not value:
            continue
        seen.add(label_type)
        label_text = entry[start:label_end].strip()
        out.append((label_type, label_text, value))
    return out or None


def _format_prior_job_entry(fields: list[tuple[str, str, str]], index: int) -> str:
    by_type = {t: (lbl, val) for t, lbl, val in fields}

    def _piece(key: str) -> str:
        if key not in by_type:
            return ""
        lbl, val = by_type[key]
        # Chuẩn hoá phone về +84 khi hiển thị
        if key == "phone":
            val = format_vn_phone_display(val)
        return f"{lbl}: {val}"

    date_bits = [b for b in (
        (f"{by_type['start'][0]} {by_type['start'][1]}" if "start" in by_type else ""),
        (f"{by_type['end'][0]} {by_type['end'][1]}" if "end" in by_type else ""),
    ) if b]
    line1 = " ".join(date_bits)
    line2 = ", ".join(p for p in (_piece("company"), _piece("position")) if p)
    line3 = ", ".join(p for p in (_piece("manager"), _piece("phone")) if p)
    if line3:
        line3 = line3.rstrip(",") + "."

    lines = [l for l in (line1, line2, line3) if l]
    if not lines:
        return ""
    body = "\n".join(lines)
    return f"{index}. {body}" if index else body


def format_prior_jobs_history_display(
    text: str,
    *,
    current_occupation: str = "",
    current_employer: str = "",
    app_current_occupation: str = "",
    app_current_employer: str = "",
) -> str:
    """Format lại work_prior_jobs_history cho Review/export (khách yêu cầu 2026-08-13):
      - Mỗi entry viết lại 3 dòng: dòng 1 = khoảng thời gian, dòng 2 = công ty + vị trí,
        dòng 3 = quản lý + SĐT (kết bằng dấu chấm) — thay vì dồn hết vào 1 dòng dài.
      - Entry trùng công ty/nghề nghiệp với công việc HIỆN TẠI VÀ không có ngày kết thúc rõ ràng
        (khoảng mở/Present — trùng lặp vô hại, khách lỡ ghi lại việc đang làm vào mục lịch sử)
        bị LOẠI khỏi lịch sử. Entry trùng công việc hiện tại NHƯNG CÓ ngày kết thúc cụ thể KHÔNG
        bị loại — đây chính là dấu hiệu khách ghi nhầm (việc "hiện tại" thực ra đã nghỉ) mà
        detect_work_period_issues() cần thấy để cảnh báo; xoá đi sẽ giấu mất bằng chứng.
      - So với CẢ worksheet (DS-260 khách khai) VÀ Application form — trùng với BẤT KỲ nguồn nào
        đều bị loại khỏi lịch sử (khách khai "hiện tại" = "studento" trên worksheet nhưng
        application form ghi "studo" → cùng 1 công việc, entry lịch sử trùng vẫn phải bỏ).
      - GIỮ NGUYÊN NGÔN NGỮ/DẤU gốc của khách — không dịch, không bỏ dấu, không thêm dấu.
      - Entry không nhận diện được nhãn nào (text lạ, không theo mẫu quen) → giữ nguyên văn,
        không cố ép cấu trúc lên nó (tránh làm hỏng dữ liệu không khớp mẫu).
    """
    entries = _split_prior_job_entries(text)
    if not entries:
        return ""

    # Merge tokens từ cả 2 nguồn: worksheet + application form.
    ws_tokens = _job_identity_tokens(current_occupation, current_employer) if (
        current_occupation.strip() or current_employer.strip()
    ) else set()
    app_tokens = _job_identity_tokens(app_current_occupation, app_current_employer) if (
        app_current_occupation.strip() or app_current_employer.strip()
    ) else set()
    cur_tokens = ws_tokens | app_tokens

    out_lines: list[str] = []
    idx = 0
    for entry in entries:
        fields = _extract_prior_job_labeled_fields(entry)
        if fields and cur_tokens:
            by_type = {t: v for t, _lbl, v in fields}
            entry_tokens = _job_identity_tokens(by_type.get("position", ""), by_type.get("company", ""))
            end_val = by_type.get("end", "").strip()
            has_definite_end = bool(end_val) and parse_full_date(end_val) is not None
            if entry_tokens and not has_definite_end:
                containment = len(entry_tokens & cur_tokens) / len(entry_tokens)
                if containment >= 0.5:
                    continue  # trùng công việc hiện tại, khoảng mở — bỏ qua entry này
        idx += 1
        if fields:
            out_lines.append(_format_prior_job_entry(fields, idx if len(entries) > 1 else 0))
        else:
            out_lines.append(entry)
    return "\n".join(l for l in out_lines if l)


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


_SECTIONS_BLOCK_WORKSHEET_WITHOUT_PRIMARY = frozenset({
    "section_death",
    "section_military",
    "section_judicial",
})


def _section_primary_doc_present(
    records: list[ApplicantDocRecord],
    section_id: str,
    *,
    person_name: str | None = None,
) -> bool:
    """Có giấy tờ chính của section (vd. death_certificate) — tránh worksheet điền nhầm."""
    primary = SECTION_PRIMARY_DOC.get(section_id)
    if not primary:
        return True
    typed = [r for r in records if r.doc_type == primary]
    if not typed:
        return False
    if not person_name:
        return True
    if primary in LUONG1_PERSON_SCOPED_DOC_TYPES or primary == "judicial_certificate":
        std, ref = pick_luong1_pair_for_person(records, primary, person_name)
        return bool(std or ref)
    return True


def clear_child_member_unscoped_sections(
    sections_out: list[dict[str, Any]],
    records: list[ApplicantDocRecord],
    person_name: str,
) -> None:
    """Hồ sơ con — bỏ judicial/death/military nếu không có giấy tờ đúng người."""
    for sec in sections_out:
        sid = sec.get("id", "")
        if sid not in ("section_judicial", "section_death", "section_military"):
            continue
        if _section_primary_doc_present(records, sid, person_name=person_name):
            continue
        for field in sec["fields"]:
            field["value"] = ""
            field["source"] = empty_ds260_field_source()


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
        section_id = sec.get("id", "")
        if section_id in ("section_children", "section_previous_spouse", "section_divorce"):
            continue
        primary_ok = _section_primary_doc_present(records, section_id, person_name=person_name)
        for field in sec["fields"]:
            if field.get("source", {}).get("derived") in (
                "conflict_resolution",
                "worksheet_conflict_resolution",
                "manual_override",
            ):
                continue
            if not _is_empty_for_fallback(field.get("value") or ""):
                continue
            field_key = field.get("key", "")
            if field_key == "current_marital_status":
                continue
            mapping = mappings.get(field_key)
            if not mapping or mapping.document == "spouse_applicant_profile":
                continue

            allowed = _allowed_doc_types_for_field(field_key, mapping)
            eligible = [r for r in records if r.doc_type in allowed]
            if person_name:
                eligible = _eligible_records_for_field_fill(eligible, person_name, field_key)
            if not primary_ok and section_id in _SECTIONS_BLOCK_WORKSHEET_WITHOUT_PRIMARY:
                eligible = [r for r in eligible if r.doc_type != "ds260_customer_form"]

            # Cha/mẹ: ưu tiên DS-260 worksheet (conf 1.0) trước birth certificate.
            # BC chỉ để đối chiếu, không phải nguồn chính. Áp dụng cho cả tên lẫn nơi sinh.
            if field_key in _PARENT_NAME_KEYS | _PARENT_BIRTH_KEYS:
                ws_rec = next((r for r in eligible if r.doc_type == "ds260_customer_form"), None)
                if ws_rec:
                    val, source_field = _resolve_field_from_record(ws_rec, mapping)
                    if not _is_empty_for_fallback(val):
                        doc_id = str(ws_rec.source_document_id) if ws_rec.source_document_id else None
                        field["value"] = val
                        field["source"] = {
                            "document_type": ws_rec.doc_type,
                            "source_field": source_field,
                            "document_id": doc_id,
                            "document_filename": filename_map.get(doc_id or "", "") if doc_id else "",
                            "variant": ws_rec.variant,
                            "record_id": str(ws_rec.id),
                            "derived": "ds260_worksheet_fill",
                        }
                        continue
                # Worksheet trống → duyệt eligible (BC) như bình thường

            if not eligible:
                continue

            target_mapping = mapping
            ordered = sorted(eligible, key=lambda r: _record_fill_priority(r, target_mapping))
            for rec in ordered:
                val, source_field = _resolve_field_from_record(rec, mapping)
                if _is_empty_for_fallback(val):
                    continue
                # Chặn giá trị giới tính lọt nhầm vào trường họ/tên (bleed OCR).
                if field_key.endswith(
                    ("_full_name", "_surname", "_given_names", "_name")
                ) and val.strip().lower() in _GENDER_TOKENS:
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


def _phone_completeness_score(val: str) -> int:
    s = (val or "").strip()
    if not s:
        return 0
    digits = re.sub(r"\D", "", s)
    if s.startswith("+") or digits.startswith("0084") or (digits.startswith("84") and len(digits) >= 11):
        return 3
    if s.startswith("0") or (digits.startswith("0") and len(digits) >= 10):
        return 2
    return 1


def _pick_fuller_phone(val1: str, val2: str) -> str:
    """Chọn số điện thoại đầy đủ hơn giữa 2 số cùng subscriber number:
    ưu tiên +84 (score 3) > 0 (score 2) > số chỉ có 9 số không có đầu số (score 1)."""
    s1 = _phone_completeness_score(val1)
    s2 = _phone_completeness_score(val2)
    if s2 > s1:
        return val2
    return val1


def enrich_work_education_from_worksheet(
    fields_out: list[dict[str, Any]],
    records: list[ApplicantDocRecord],
    filename_map: dict[str, str] | None = None,
) -> None:
    """Bổ sung Phần D từ DS-260 khách khai khi Application form thiếu hoặc chưa upload.
    Với các field công việc hiện tại (_WORK_CURRENT_JOB_KEYS): nếu Application Form và worksheet
    cùng thông tin (dù viết khác ngôn ngữ) → ưu tiên Application Form, KHÔNG ghi đè bằng
    Vietnamese từ worksheet."""
    from app.services.ds260_conflicts import (
        _ADDRESS_COMPARE_KEYS,
        _work_values_match,
        pick_latest_by_variant,
    )
    from app.services.ds260_customer_keys import normalize_ds260_customer_raw

    ws_rec = pick_latest_by_variant(records, "ds260_customer_form", "exception") or pick_latest_record(
        records, "ds260_customer_form"
    )
    if not ws_rec:
        return

    merged = normalize_ds260_customer_raw(_merge_raw_dict(ws_rec))
    if not merged:
        return

    app_rec = pick_latest_by_variant(records, "application_form", "standard") or pick_latest_by_variant(
        records, "application_form", "exception"
    )
    mappings = flatten_ds260_mappings()
    doc_id = str(ws_rec.source_document_id) if ws_rec.source_document_id else None

    for field in fields_out:
        if field.get("source", {}).get("derived") in (
            "conflict_resolution",
            "worksheet_conflict_resolution",
            "manual_override",
        ):
            continue
        if not _is_empty_for_fallback(field.get("value") or ""):
            continue
        key = field.get("key", "")
        mapping = mappings.get(key)
        if not mapping:
            continue

        candidates: list[str] = []
        if key in merged:
            candidates.append(key)
        if mapping.field and mapping.field in merged:
            candidates.append(mapping.field)
        for alias in mapping.aliases or ():
            if alias in merged:
                candidates.append(alias)
        for alias in _effective_aliases(mapping):
            if alias in merged and alias not in candidates:
                candidates.append(alias)

        val = ""
        source_field = mapping.field
        for cand in candidates:
            v = (merged.get(cand) or "").strip()
            if not _is_empty_for_fallback(v):
                val = v
                source_field = cand
                break
        if not val:
            continue

        # Công việc hiện tại: nếu Application Form đã có cùng thông tin → giữ App Form (English).
        # Địa chỉ + prior jobs history: cũng ưu tiên Application Form khi 2 bên trùng nhau.
        # (Cùng logic với _ADDRESS_COMPARE_KEYS + work_prior_jobs_history trong conflict detection.)
        _WORK_ADVANCED_KEYS = _WORK_CURRENT_JOB_KEYS | _ADDRESS_COMPARE_KEYS | {"work_prior_jobs_history"}
        if key in _WORK_ADVANCED_KEYS and app_rec:
            app_val, app_sf = _resolve_ds260_field_value(mapping, app_rec)
            app_val = (app_val or "").strip()
            ws_val = val
            if app_val and _work_values_match(key, app_val, ws_val):
                # Application Form English trùng với worksheet Vietnamese → giữ App Form.
                continue

        field["value"] = val
        field["source"] = {
            "document_type": "ds260_customer_form",
            "source_field": source_field,
            "document_id": doc_id,
            "document_filename": (filename_map or {}).get(doc_id or "", "") if doc_id else "",
            "variant": ws_rec.variant,
            "record_id": str(ws_rec.id),
            "derived": "ds260_worksheet_fill",
        }


def reattribute_matching_worksheet_sources(
    sections_out: list[dict[str, Any]],
    records: list[ApplicantDocRecord],
    resolutions: dict[str, str],
    filename_map: dict[str, str] | None = None,
) -> None:
    """Khi DS-260 khách khai (worksheet) trùng giá trị với Application form (nguồn đối chiếu
    chính thức cho địa chỉ/liên lạc/công việc hiện tại) — đổi SOURCE hiển thị sang
    application_form, GIỮ NGUYÊN giá trị (khách yêu cầu: hiển thị đúng nguồn khi 2 bên đã khớp
    nhau, thay vì luôn hiện "DS-260 khách khai").

    Dùng ĐÚNG predicate so khớp của build_worksheet_conflict_rows (norm_conflict_value /
    _place_or_school_values_match / _work_values_match) để attribution ở đây và Conflict ở
    ds260_conflicts.py không bao giờ lệch nhau — field coi là "trùng" ở đây thì cũng phải
    "trùng" (không tạo Conflict) ở build_worksheet_conflict_rows, và ngược lại.
    """
    from app.services.ds260_conflicts import (
        WORKSHEET_OFFICIAL_DOC_OVERRIDES,
        _PHONE_COMPARE_KEY_RE,
        _WORK_CURRENT_JOB_KEYS,
        _official_value_for_worksheet_compare,
        _place_or_school_values_match,
        _PLACE_SCHOOL_COMPARE_KEY_RE,
        _work_values_match,
        norm_conflict_value,
    )

    filename_map = filename_map or {}
    target_keys = set(WORKSHEET_OFFICIAL_DOC_OVERRIDES) | _WORK_CURRENT_JOB_KEYS

    for sec in sections_out:
        for field in sec.get("fields", []):
            mapping_key = field.get("key", "")
            if mapping_key not in target_keys:
                continue
            source = field.get("source") or {}
            if source.get("document_type") != "ds260_customer_form":
                continue
            worksheet_val = (field.get("value") or "").strip()
            if not worksheet_val:
                continue

            official_val, official_rec = _official_value_for_worksheet_compare(
                records, mapping_key, resolutions
            )
            official_val = official_val.strip()
            if not official_val:
                continue

            if mapping_key in _WORK_CURRENT_JOB_KEYS:
                matched = _work_values_match(mapping_key, official_val, worksheet_val)
            elif norm_conflict_value(mapping_key, official_val) == norm_conflict_value(
                mapping_key, worksheet_val
            ):
                matched = True
            elif _PLACE_SCHOOL_COMPARE_KEY_RE.search(mapping_key) and _place_or_school_values_match(
                official_val, worksheet_val
            ):
                matched = True
            else:
                matched = False
            if not matched:
                continue

            if _PHONE_COMPARE_KEY_RE.search(mapping_key):
                field["value"] = _pick_fuller_phone(worksheet_val, official_val)

            doc_id = str(official_rec.source_document_id) if official_rec and official_rec.source_document_id else None
            field["source"] = {
                **source,
                "document_type": "application_form",
                "source_field": mapping_key,
                "document_id": doc_id,
                "document_filename": filename_map.get(doc_id, "") if doc_id else "",
                "variant": official_rec.variant if official_rec else None,
                "record_id": str(official_rec.id) if official_rec else None,
                "derived": "golden_source_application_form",
            }


# Alias tương thích ngược cho reattribute_matching_worksheet_sources
reattribute_matched_worksheet_to_application_form = reattribute_matching_worksheet_sources


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
    "section_work_education": "application_form",
}


def _attach_section_warnings(sections_out: list[dict[str, Any]]) -> None:
    """Thêm warnings vào section khi có vấn đề cần lưu ý."""
    for sec in sections_out:
        warnings: list[str] = []
        if sec["id"] == "section_address":
            from_date_field = next(
                (f for f in sec["fields"] if f.get("key") == "address_from_date"), None
            )
            if from_date_field and not (from_date_field.get("value") or "").strip():
                warnings.append("⚠️ Thiếu From Date cho người dùng điền vào nhé")
        if warnings:
            sec["warnings"] = warnings


def _attach_section_fill_stats(
    sections_out: list[dict[str, Any]],
    records: list[ApplicantDocRecord],
    *,
    member_role: str | None = None,
) -> tuple[int, int, int, int]:
    """Returns filled, total, applicable_filled, applicable_total."""
    present_docs = {r.doc_type for r in records}
    has_ref = any(r.variant == "exception" for r in records)
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
        if member_role in ("child", "grandchild") and sec["id"] in _child_excluded_section_ids():
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
                if field.get("review_hidden"):
                    applicable = False
                else:
                    m = re.match(r"^child_(\d+)_", field.get("key", ""))
                    if m:
                        max_filled = 0
                        for f in sec["fields"]:
                            fm = re.match(r"^child_(\d+)_full_name$", f.get("key", ""))
                            if fm and (f.get("value") or "").strip():
                                max_filled = max(max_filled, int(fm.group(1)))
                        if int(m.group(1)) > max(max_filled, 0):
                            applicable = False
            if applicable and mapping and mapping.document in {"ds260_customer_form", "address_document"}:
                applicable = (
                    "ds260_customer_form" in present_docs
                    or "address_document" in present_docs
                    or has_ref
                )
            if (
                applicable
                and member_role in ("child", "grandchild")
                and field.get("key") == "current_marital_status"
            ):
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


_PLACE_GROUP_PREFIXES = ("", "father_", "mother_", "spouse_") + tuple(
    f"child_{i}_" for i in range(1, 5)
)


def _index_fields_by_key(sections_out: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    idx: dict[str, dict[str, Any]] = {}
    for sec in sections_out:
        for field in sec.get("fields", []):
            idx[field.get("key", "")] = field
    return idx


def _field_value(idx: dict[str, dict[str, Any]], key: str) -> str:
    field = idx.get(key)
    return (field.get("value") or "").strip() if field else ""


def _set_value(field: dict[str, Any], value: str, derived: str) -> None:
    field["value"] = value
    field.setdefault("source", {})
    field["source"]["derived"] = derived


def _is_vietnam_birth(country: str) -> bool:
    from app.services.birth_location import normalize_location

    c = normalize_location(country)
    return c == "" or c in {"vietnam", "viet nam"}


def normalize_ds260_place_fields(sections_out: list[dict[str, Any]]) -> None:
    """
    Chuẩn hóa City/State nơi sinh theo quy ước DS-260:
      TP trực thuộc TW → City; Tỉnh → State; cái còn lại → N/A; bỏ tên bệnh viện/địa chỉ.
    Áp cho đương đơn, cha, mẹ, phối ngẫu, từng con. Chỉ áp cho nơi sinh ở VN.
    """
    idx = _index_fields_by_key(sections_out)
    for prefix in _PLACE_GROUP_PREFIXES:
        city_f = idx.get(f"{prefix}birth_city")
        state_f = idx.get(f"{prefix}birth_state")
        if not city_f and not state_f:
            continue
        if not _is_vietnam_birth(_field_value(idx, f"{prefix}birth_country")):
            continue
        blobs = [_field_value(idx, f"{prefix}birth_state"), _field_value(idx, f"{prefix}birth_city")]
        if prefix == "":
            blobs.append(_field_value(idx, "place_of_birth"))
        result = split_birthplace_city_state(*blobs)
        if result is None:
            continue
        city_val, state_val = result
        if city_f is not None:
            curr_city = (city_f.get("value") or "").strip()
            if city_val == "N/A" and curr_city and curr_city.upper() != "N/A" and not looks_like_address_or_facility(curr_city):
                # Khách khai hoặc giấy tờ đã có tên địa danh nơi sinh -> giữ nguyên thay vì ép thành N/A
                pass
            else:
                _set_value(city_f, city_val, "birthplace_normalized")
        if state_f is not None:
            _set_value(state_f, state_val, "birthplace_normalized")

    # Thành phố kết hôn — bỏ tên cơ quan đăng ký, chỉ giữ tên thành phố.
    marriage_city_f = idx.get("spouse_marriage_city")
    if marriage_city_f:
        raw = (marriage_city_f.get("value") or "").strip()
        if raw and looks_like_address_or_facility(raw):
            token = extract_city_token(raw)
            if token:
                _set_value(marriage_city_f, token, "marriage_city_normalized")


def enrich_native_name_from_worksheet(
    sections_out: list[dict[str, Any]],
    records: list[ApplicantDocRecord],
) -> None:
    """
    'Full Name in Native Language' phải GIỮ dấu tiếng Việt. Passport MRZ thường không dấu,
    nên nếu worksheet có tên bản ngữ CÓ DẤU và bỏ dấu trùng với tên hiện tại thì dùng tên worksheet.
    """
    from app.services.birth_location import _strip_accents
    from app.services.ds260_customer_keys import normalize_ds260_customer_raw

    ws_rec = pick_latest_record(records, "ds260_customer_form")
    if not ws_rec:
        return
    ws = normalize_ds260_customer_raw(_merge_raw_dict(ws_rec))
    native_ws = (ws.get("applicant_name_native") or "").strip()
    if not native_ws or _strip_accents(native_ws) == native_ws:
        return  # worksheet không có (hoặc không có dấu)

    for sec in sections_out:
        for field in sec.get("fields", []):
            if field.get("key") != "applicant_name_native":
                continue
            current = (field.get("value") or "").strip()
            # Chỉ thay khi cùng tên (bỏ dấu trùng) — tránh ghi đè tên thiếu họ.
            if current and _strip_accents(native_ws).upper() != _strip_accents(current).upper():
                return
            field["value"] = native_ws
            field.setdefault("source", {})
            field["source"]["derived"] = "native_name_from_worksheet"
            return


def upgrade_partial_dates_from_worksheet(
    sections_out: list[dict[str, Any]],
    records: list[ApplicantDocRecord],
    filename_map: dict[str, str] | None = None,
) -> None:
    """
    Field ngày đang ở dạng một phần (chỉ năm / tháng-năm) → nếu worksheet có NGÀY ĐẦY ĐỦ
    cùng năm thì thay bằng ngày đầy đủ (vd. mother_date_of_birth '1954' → '1954-12-30').
    Nguồn hiển thị được cập nhật sang DS-260 worksheet vì ngày đầy đủ xuất xứ từ worksheet.
    """
    from app.services.ds260_dates import is_date_field_key, is_partial_date_value
    from app.services.ds260_customer_keys import normalize_ds260_customer_raw
    from app.services.ds260_conflicts import pick_latest_by_variant

    ws_rec = pick_latest_by_variant(records, "ds260_customer_form", "exception") or pick_latest_record(
        records, "ds260_customer_form"
    )
    if not ws_rec:
        return
    ws = normalize_ds260_customer_raw(_merge_raw_dict(ws_rec))
    if not ws:
        return
    mappings = flatten_ds260_mappings()
    filename_map = filename_map or {}
    doc_id = str(ws_rec.source_document_id) if ws_rec.source_document_id else None

    for sec in sections_out:
        for field in sec.get("fields", []):
            key = field.get("key", "")
            val = (field.get("value") or "").strip()
            if not val or not is_date_field_key(key) or not is_partial_date_value(val):
                continue
            mapping = mappings.get(key)
            cand_keys = [key]
            if mapping:
                cand_keys += [mapping.field, *(mapping.aliases or ())]
            for ck in cand_keys:
                ws_val = (ws.get(ck) or "").strip()
                full = parse_full_date(ws_val)
                if full and str(full.year) in val:
                    field["value"] = ws_val
                    field["source"] = {
                        "document_type": "ds260_customer_form",
                        "source_field": ck,
                        "document_id": doc_id,
                        "document_filename": filename_map.get(doc_id or "", "") if doc_id else "",
                        "variant": ws_rec.variant,
                        "record_id": str(ws_rec.id),
                        "derived": "partial_date_upgraded_from_worksheet",
                    }
                    break


def reconcile_parent_living_status(sections_out: list[dict[str, Any]]) -> None:
    """Có năm mất (worksheet/giấy báo tử) → Còn sống = No (khắc phục mâu thuẫn is_living).

    "N/A"/"Không có"/… trong ô năm mất nghĩa là KHÔNG có năm mất, không phải giá trị thật —
    dùng _is_empty_for_fallback thay vì so truthy trực tiếp, nếu không "N/A" sẽ bị hiểu nhầm là
    đã mất và tự động xóa luôn địa chỉ hiện tại của cha/mẹ (báo lỗi thực tế 2026-08-17: cha vẫn
    còn sống, worksheet ghi rõ "N/A" ở năm mất + đầy đủ địa chỉ hiện tại, nhưng hiển thị "No" và
    mất hết địa chỉ)."""
    idx = _index_fields_by_key(sections_out)
    for parent in ("father", "mother"):
        death_val = _field_value(idx, f"{parent}_death_year")
        if death_val and not _is_empty_for_fallback(death_val):
            living_f = idx.get(f"{parent}_is_living")
            if living_f and (living_f.get("value") or "").strip().lower() != "no":
                _set_value(living_f, "No", f"{parent}_not_living_from_death_year")


def reconcile_parent_spouse_addresses(sections_out: list[dict[str, Any]]) -> None:
    """
    - Cha/mẹ đã mất → để trống khối địa chỉ hiện tại.
    - Địa chỉ cha/mẹ trùng địa chỉ đương đơn chỉ coi là bleed khi OCR nhầm từ giấy tờ scan và cha/mẹ không còn sống.
    - Ô State (tỉnh hiện tại) chứa địa chỉ phố → xóa.
    """
    from app.services.birth_location import normalize_location

    idx = _index_fields_by_key(sections_out)
    applicant_addr = normalize_location(_field_value(idx, "current_address"))

    for parent in ("father", "mother"):
        addr_keys = [
            f"{parent}_address",
            f"{parent}_city",
            f"{parent}_state",
            f"{parent}_postal_code",
            f"{parent}_country",
        ]
        not_living = _field_value(idx, f"{parent}_is_living").lower() == "no"
        addr_field = idx.get(f"{parent}_address")
        parent_addr = normalize_location(_field_value(idx, f"{parent}_address"))
        from_customer_form = bool(
            addr_field
            and (
                (addr_field.get("source") or {}).get("document_type") in ("ds260_customer_form", "case_member")
                or (addr_field.get("source") or {}).get("derived", "").startswith("child_")
            )
        )
        bleed = bool(applicant_addr) and parent_addr == applicant_addr and not from_customer_form
        if not_living or bleed:
            for key in addr_keys:
                field = idx.get(key)
                if field and (field.get("value") or "").strip():
                    _set_value(field, "", "parent_address_cleared")

    # Ô tỉnh/bang hiện tại không được chứa địa chỉ phố/cơ sở (kể cả khi chuỗi có lẫn tên TP).
    for key in ("current_state", "father_state", "mother_state", "spouse_state"):
        field = idx.get(key)
        if not field:
            continue
        val = (field.get("value") or "").strip()
        if val and looks_like_address_or_facility(val):
            _set_value(field, "", "state_address_cleared")


def reconcile_parent_living_addresses(sections_out: list[dict[str, Any]]) -> None:
    """Đảm bảo địa chỉ cha/mẹ còn sống được điền đầy đủ (Street, City, State, Postal, Country).

    Áp dụng cho mọi form (đương đơn, phối ngẫu, con cái):
    1. Nếu cha/mẹ còn sống (is_living='Yes' hoặc có tên và không có năm mất):
       - Nếu địa chỉ cha/mẹ ghi 'SAME' / 'Như trên' / 'Cùng địa chỉ' / 'Chung hộ khẩu':
         lấy từ current_address, current_city, current_state, postal_code, current_country.
       - Nếu có address (địa chỉ đường) nhưng thiếu City / State / Country / Postal code:
         + Bổ sung City & State từ chuỗi địa chỉ (derive_city_from_place, derive_birth_state_from_place).
         + Bổ sung Country (mặc định 'Vietnam' nếu địa chỉ VN hoặc cùng quốc gia của đương đơn).
         + Bổ sung Postal code nếu City/State khớp với current_city/current_state của đương đơn.
    2. Nếu cả cha và mẹ đều còn sống, một người có địa chỉ còn người kia để trống:
       - Điền địa chỉ người còn lại theo địa chỉ cha/mẹ (cha mẹ sống chung).
    """
    from app.services.birth_location import (
        derive_birth_state_from_place,
        derive_city_from_place,
        derive_country_from_place,
    )

    idx = _index_fields_by_key(sections_out)
    curr_addr = _field_value(idx, "current_address")
    curr_city = _field_value(idx, "current_city")
    curr_state = _field_value(idx, "current_state")
    curr_postal = _field_value(idx, "postal_code")
    curr_country = _field_value(idx, "current_country") or "Vietnam"

    same_keywords = {
        "same", "nhu tren", "như trên", "cung dia chi", "cùng địa chỉ",
        "chung dia chi", "chung địa chỉ", "y nhu tren", "y như trên",
        "theo duong don", "theo đương đơn", "same as applicant",
        "cung ho khau", "cùng hộ khẩu", "song chung", "sống chung",
    }

    for parent in ("father", "mother"):
        living_f = idx.get(f"{parent}_is_living")
        death_f = idx.get(f"{parent}_death_year")
        name_f = idx.get(f"{parent}_surname") or idx.get(f"{parent}_given_names") or idx.get(f"{parent}_full_name")
        has_name = bool((name_f.get("value") or "").strip()) if name_f else False

        is_living_val = (living_f.get("value") or "").strip().lower() if living_f else ""
        death_val = (death_f.get("value") or "").strip() if death_f else ""

        # Nếu có tên cha/mẹ và không có năm mất (hoặc năm mất N/A) và chưa khai No -> mặc định Yes
        if has_name and not is_living_val and (not death_val or _is_empty_for_fallback(death_val)):
            if living_f:
                _set_value(living_f, "Yes", f"{parent}_living_default_yes")
                is_living_val = "yes"

        if is_living_val != "yes":
            continue

        addr_f = idx.get(f"{parent}_address")
        city_f = idx.get(f"{parent}_city")
        state_f = idx.get(f"{parent}_state")
        postal_f = idx.get(f"{parent}_postal_code")
        country_f = idx.get(f"{parent}_country")

        addr_val = (addr_f.get("value") or "").strip() if addr_f else ""
        addr_clean = re.sub(r"[^\w\s]", " ", addr_val.lower()).strip()
        addr_clean_compact = " ".join(addr_clean.split())

        # Trường hợp ghi "SAME" hoặc cùng địa chỉ với đương đơn
        if addr_clean_compact in same_keywords or (
            not addr_val
            and curr_addr
            and addr_f
            and (addr_f.get("source", {}).get("derived") or "").startswith(f"child_{parent}_")
        ):
            if curr_addr and addr_f:
                _set_value(addr_f, curr_addr, f"{parent}_address_same_as_applicant")
            if curr_city and city_f and not (city_f.get("value") or "").strip():
                _set_value(city_f, curr_city, f"{parent}_city_same_as_applicant")
            if curr_state and state_f and not (state_f.get("value") or "").strip():
                _set_value(state_f, curr_state, f"{parent}_state_same_as_applicant")
            if curr_postal and postal_f and not (postal_f.get("value") or "").strip():
                _set_value(postal_f, curr_postal, f"{parent}_postal_same_as_applicant")
            if curr_country and country_f and not (country_f.get("value") or "").strip():
                _set_value(country_f, curr_country, f"{parent}_country_same_as_applicant")
            continue

        # Nếu có địa chỉ cụ thể:
        addr_val = (addr_f.get("value") or "").strip() if addr_f else ""
        if addr_val:
            city_val = (city_f.get("value") or "").strip() if city_f else ""
            state_val = (state_f.get("value") or "").strip() if state_f else ""
            country_val = (country_f.get("value") or "").strip() if country_f else ""
            postal_val = (postal_f.get("value") or "").strip() if postal_f else ""

            parsed_city, parsed_state = _parse_birth_place_city_state(addr_val)
            if not city_val and city_f:
                derived_city = parsed_city or derive_city_from_place(addr_val)
                if derived_city:
                    _set_value(city_f, derived_city, f"{parent}_city_derived_from_address")
            if not state_val and state_f:
                derived_state = parsed_state or derive_birth_state_from_place(addr_val)
                if derived_state:
                    _set_value(state_f, derived_state, f"{parent}_state_derived_from_address")
            if not country_val and country_f:
                derived_country = derive_country_from_place(addr_val) or "Vietnam"
                _set_value(country_f, derived_country, f"{parent}_country_default_vietnam")
            if not postal_val and postal_f and curr_postal:
                cur_p_city = (city_f.get("value") or "").strip() if city_f else ""
                cur_p_state = (state_f.get("value") or "").strip() if state_f else ""
                from app.services.birth_location import normalize_location

                same_loc = (
                    (cur_p_city and curr_city and (
                        normalize_location(cur_p_city) == normalize_location(curr_city)
                        or curr_city.lower() in cur_p_city.lower()
                        or cur_p_city.lower() in curr_city.lower()
                    ))
                    or (cur_p_state and curr_state and normalize_location(cur_p_state) == normalize_location(curr_state))
                )
                if same_loc:
                    _set_value(postal_f, curr_postal, f"{parent}_postal_from_applicant")

    # 2. Nếu cả 2 cha mẹ cùng còn sống, một người có địa chỉ đầy đủ còn người kia để trống
    f_living = (idx.get("father_is_living", {}).get("value") or "").strip().lower() == "yes"
    m_living = (idx.get("mother_is_living", {}).get("value") or "").strip().lower() == "yes"
    f_addr = (idx.get("father_address", {}).get("value") or "").strip()
    m_addr = (idx.get("mother_address", {}).get("value") or "").strip()

    if f_living and m_living:
        if f_addr and not m_addr:
            for suffix in ("address", "city", "state", "postal_code", "country"):
                src_val = (idx.get(f"father_{suffix}", {}).get("value") or "").strip()
                dst_f = idx.get(f"mother_{suffix}")
                if src_val and dst_f and not (dst_f.get("value") or "").strip():
                    _set_value(dst_f, src_val, "mother_address_from_father_same_household")
        elif m_addr and not f_addr:
            for suffix in ("address", "city", "state", "postal_code", "country"):
                src_val = (idx.get(f"mother_{suffix}", {}).get("value") or "").strip()
                dst_f = idx.get(f"father_{suffix}")
                if src_val and dst_f and not (dst_f.get("value") or "").strip():
                    _set_value(dst_f, src_val, "father_address_from_mother_same_household")


def apply_ds260_default_values(sections_out: list[dict[str, Any]]) -> None:
    """Điền giá trị mặc định cho các trường còn trống (CHỌN YES/NO, LUÔN KHAI CÓ).

    Chỉ áp dụng khi trường vẫn trống — không ghi đè giá trị từ giấy tờ, worksheet,
    conflict hay manual override. Trường con (child_N_*_future) chỉ điền khi con đó tồn tại.

    Riêng has_vaccination_docs (Có giấy chích ngừa / Have vaccination documentation per U.S law?):
    luôn luôn chọn "Yes" là default dù khách có khai "No" đi chăng nữa (trừ khi có manual override).
    """
    defaults = {k: m.default for k, m in flatten_ds260_mappings().items() if m.default}
    if not defaults:
        return
    for sec in sections_out:
        present_children: set[str] = set()
        for field in sec["fields"]:
            m = re.match(r"^(child_\d+)_full_name$", field.get("key", ""))
            if m and (field.get("value") or "").strip():
                present_children.add(m.group(1))
        for field in sec["fields"]:
            key = field.get("key", "")
            default = defaults.get(key)
            if not default:
                continue
            # has_vaccination_docs: luôn luôn chọn "Yes" là default dù khách có khai "No" đi chăng nữa
            if key == "has_vaccination_docs":
                if field.get("source", {}).get("derived") == "manual_override":
                    continue
                if (field.get("value") or "").strip().lower() != "yes":
                    field["value"] = "Yes"
                    field["source"] = {
                        **empty_ds260_field_source(),
                        "derived": "default_value",
                    }
                continue
            if (field.get("value") or "").strip():
                continue
            # Không ghi đè manual override (user đã xóa field)
            if field.get("source", {}).get("derived") == "manual_override":
                continue
            cm = re.match(r"^(child_\d+)_immigrating_future$", key)
            if cm and cm.group(1) not in present_children:
                continue
            field["value"] = default
            field["source"] = {
                **empty_ds260_field_source(),
                "derived": "default_value",
            }


# Câu hỏi Yes/No mà đáp án hợp lệ CHỈ có thể là Yes/No → "N/A" luôn sai; khi trống mà KHÔNG
# có dữ liệu kèm theo (evidence) thì mặc định "No" theo mẫu DS-260. Mỗi câu ánh xạ tới các
# field "bằng chứng" — nếu có bằng chứng thì để nguyên cho người review (không tự đoán Yes/No).
# KHÔNG gồm *_is_living (N/A ở đó KHÔNG được suy thành "No" = đã mất) và children_count
# (định dạng riêng "No, 0").
_YESNO_QUESTION_EVIDENCE: dict[str, tuple[str, ...]] = {
    "other_addresses_used": ("other_addresses_history",),
    "other_nationality_used": ("other_nationality_history",),
    "other_phones_used": ("other_phones_history",),
    "other_emails_used": ("other_emails_history",),
    "other_social_media_used": ("other_social_history",),
    "work_other_occupation_used": ("work_other_occupation_detail",),
    "work_prior_jobs_used": ("work_prior_jobs_history",),
    # traveled_countries_5yr_used / other_languages_used: nếu khách để trống không khai thì để trống, không tự động khai No.
    "previous_spouses_used": ("previous_spouse_full_name",),
    "children_used": ("children_count", "child_1_full_name"),
    "military_served": ("military_full_name", "military_country", "military_branch"),
}

# Các trường khi history/detail có dữ liệu thì câu hỏi bắt buộc phải là "Yes" (tránh mâu thuẫn history có mà Yes/No là No)
_AUTO_YES_WHEN_EVIDENCE_PRESENT = frozenset(
    {
        "other_addresses_used",
        "other_nationality_used",
        "other_phones_used",
        "other_emails_used",
        "other_social_media_used",
        "work_other_occupation_used",
        "work_prior_jobs_used",
    }
)


def _is_na_value(val: str) -> bool:
    """True khi giá trị là 'N/A' (mọi biến thể) — không phải câu trả lời Yes/No hợp lệ."""
    return (val or "").strip().lower().replace(" ", "").replace(".", "") in {"na", "n/a"}


def _has_meaningful_evidence(val: str) -> bool:
    """True khi trường lịch sử/chi tiết có nội dung thực tế (không phải rỗng, N/A, None, Không)."""
    v = (val or "").strip()
    if not v or _is_na_value(v):
        return False
    if v.lower() in {"no", "none", "không", "không có", "khong co", "khong"}:
        return False
    return True


def reconcile_ds260_yesno_and_death_year(sections_out: list[dict[str, Any]]) -> None:
    """Hậu xử lý XÁC ĐỊNH (deterministic), chạy sau khi đã chuẩn hóa tiếng Anh:

    - Nếu field lịch sử/bằng chứng (Prior address history, other phones, other emails...) CÓ DỮ LIỆU
      → câu hỏi Yes/No tương ứng (Lived elsewhere since age 16?...) PHẢI LÀ 'Yes' (tránh mâu thuẫn).
    - B4: câu hỏi Yes/No để "N/A" hoặc để trống & KHÔNG có dữ liệu kèm → "No".
    - A4: '*_death_year' lỡ nhận NGÀY đầy đủ (vd. 07/09/2006) → rút về NĂM (2006),
      đúng ô 'Year of death' và giảm rủi ro số liệu bịa quá chi tiết.
    """
    index: dict[str, dict[str, Any]] = {}
    for sec in sections_out:
        for field in sec.get("fields", []):
            index.setdefault(field.get("key", ""), field)

    def _val(key: str) -> str:
        f = index.get(key)
        return (f.get("value") or "").strip() if f else ""

    for qkey, evidence_keys in _YESNO_QUESTION_EVIDENCE.items():
        field = index.get(qkey)
        if field is None:
            continue
        # Không ghi đè manual override (user đã chủ động sửa thủ công)
        if field.get("source", {}).get("derived") == "manual_override":
            continue

        has_evidence = any(_has_meaningful_evidence(_val(e)) for e in evidence_keys)
        if has_evidence:
            if qkey in _AUTO_YES_WHEN_EVIDENCE_PRESENT:
                # Lịch sử/bằng chứng có dữ liệu -> câu hỏi bắt buộc là "Yes"
                field["value"] = "Yes"
                field["source"] = {
                    **empty_ds260_field_source(),
                    "derived": "yesno_from_history",
                }
                continue
            else:
                # Có bằng chứng -> để review tự chốt Yes/No
                continue

        cur = (field.get("value") or "").strip()
        if cur and not _is_na_value(cur):
            if qkey in _AUTO_YES_WHEN_EVIDENCE_PRESENT and cur.lower() in ("yes", "y", "true", "1"):
                pass  # Không có evidence -> đồng bộ về No (tránh mâu thuẫn Yes/No là Yes nhưng history trống)
            else:
                continue  # đã có Yes/No hợp lệ và không có evidence mâu thuẫn → giữ nguyên

        if qkey == "other_addresses_used":
            # "Lived elsewhere since age 16?": nếu khách không khai thì để trống, không tự điền "No"
            field["value"] = ""
            continue

        field["value"] = "No"
        field["source"] = {
            **empty_ds260_field_source(),
            "derived": "yesno_default_no",
        }


    # other_name_used: luôn điền "No" khi trống, không cần kiểm tra other_names.
    # Nếu người dùng thực sự có tên khác, họ sẽ tự sửa thành "Yes" trên worksheet.
    other_name_field = index.get("other_name_used")
    if other_name_field:
        # Không ghi đè manual override
        if other_name_field.get("source", {}).get("derived") != "manual_override":
            cur = (other_name_field.get("value") or "").strip()
            if not cur or _is_na_value(cur):
                other_name_field["value"] = "No"
                other_name_field["source"] = {
                    **empty_ds260_field_source(),
                    "derived": "yesno_default_no",
                }

    # other_names (Other Names details): luôn điền "No" khi trống.
    # Người dùng tự điền chi tiết tên khác nếu có.
    other_names_field = index.get("other_names")
    if other_names_field:
        # Không ghi đè manual override
        if other_names_field.get("source", {}).get("derived") != "manual_override":
            cur = (other_names_field.get("value") or "").strip()
            if not cur or _is_na_value(cur):
                other_names_field["value"] = "No"
                other_names_field["source"] = {
                    **empty_ds260_field_source(),
                    "derived": "yesno_default_no",
                }

    # been_in_us / issued_us_visa: nếu có US Visa document (visa dán trong passport, entry stamp Mỹ)
    # → điền "Yes" (khách đã từng đến Mỹ). Evidence: visa_type, entry_stamp, visa_number, entry_date.
    # Riêng issued_us_visa / refused_us_visa: nếu khách để trống không khai thì để trống, không tự động khai "No".
    for field_key in ("been_in_us", "issued_us_visa"):
        field = index.get(field_key)
        if not field:
            continue
        # Không ghi đè manual override
        if field.get("source", {}).get("derived") == "manual_override":
            continue
        cur = (field.get("value") or "").strip()
        if cur and not _is_na_value(cur):
            continue  # đã có giá trị Yes/No hợp lệ → giữ nguyên
        # Kiểm tra evidence từ US Visa (visa_type, entry_stamp, visa_number...)
        has_us_visa_evidence = any(
            _val(e) for e in ("visa_type", "entry_stamp", "visa_number", "entry_date")
        )
        if has_us_visa_evidence:
            field["value"] = "Yes"
            field["source"] = {
                **empty_ds260_field_source(),
                "derived": "yesno_from_us_visa_document",
            }
        elif field_key == "been_in_us" and (not cur or _is_na_value(cur)):
            # been_in_us: Không có US Visa document → mặc định "No" (khách chưa từng đến Mỹ)
            field["value"] = "No"
            field["source"] = {
                **empty_ds260_field_source(),
                "derived": "yesno_default_no",
            }

    for key, field in index.items():
        if not key.endswith("_death_year"):
            continue
        raw = (field.get("value") or "").strip()
        if not raw or re.fullmatch(r"\d{4}", raw):
            continue
        year = _year_from_death_date(raw)
        if year and year != raw:
            field["value"] = year
            field.setdefault("source", {})
            field["source"]["derived"] = "death_year_normalized"


# Ô THÔNG TIN (số điện thoại, email, định danh MXH) — bỏ trống thì ghi 'N/A',
# KHÔNG bao giờ là 'No'. Lỗi Case B-2: Work Phone hiển thị 'No'.
_NA_NOT_NO_KEYS: frozenset[str] = frozenset(
    {
        "primary_phone",
        "secondary_phone",
        "work_phone",
        "email",
        "social_media_identifier",
    }
)

# Cặp (ô City, ô State) — City đã có giá trị thì State không được để TRỐNG (phải 'N/A').
_CITY_STATE_PAIRS: tuple[tuple[str, str], ...] = (
    ("birth_city", "birth_state"),
    ("father_birth_city", "father_birth_state"),
    ("mother_birth_city", "mother_birth_state"),
    ("spouse_birth_city", "spouse_birth_state"),
    ("current_city", "current_state"),
    ("work_employer_city", "work_employer_state"),
)


def normalize_ds260_na_conventions(sections_out: list[dict[str, Any]]) -> None:
    """Thống nhất quy ước 'N/A' vs 'No' vs để trống trên toàn bộ form.

    Ba nhóm lệch mà tester ghi nhận lặp lại ở nhiều hồ sơ:
      - Ô số điện thoại/email hiển thị 'No' (Case B-2) → phải là 'N/A'.
      - 'Số con' để TRỐNG ở một thành viên trong khi anh chị em ghi 'No' (Case C-2).
      - Ô Tỉnh/Bang để TRỐNG trong khi ô Thành phố đã có (Case E).
    """
    idx = _index_fields_by_key(sections_out)

    for key in _NA_NOT_NO_KEYS:
        field = idx.get(key)
        if not field:
            continue
        val = (field.get("value") or "").strip()
        if not val or val.lower() in {"no", "none", "không", "khong"}:
            _set_value(field, "N/A", "na_not_no")

    count_field = idx.get("children_count")
    if count_field and not (count_field.get("value") or "").strip():
        has_child = any(
            (idx.get(f"child_{i}_full_name", {}).get("value") or "").strip()
            for i in range(1, 10)
        )
        if not has_child:
            _set_value(count_field, "No", "children_count_none")

    for city_key, state_key in _CITY_STATE_PAIRS:
        city_field, state_field = idx.get(city_key), idx.get(state_key)
        if not city_field or not state_field:
            continue
        if (city_field.get("value") or "").strip() and not (
            state_field.get("value") or ""
        ).strip():
            _set_value(state_field, "N/A", "state_na_when_city_present")


def _year_of(val: str) -> int | None:
    """Năm từ một giá trị ngày bất kỳ (đầy đủ / tháng-năm / chỉ năm)."""
    v = (val or "").strip()
    if not v:
        return None
    full = parse_full_date(v)
    if full:
        return full.year
    m = re.search(r"(1[89]\d{2}|20\d{2})", v)
    return int(m.group(1)) if m else None


# Cặp (ô năm mất, ô ngày sinh của CHÍNH người đó) — chết không thể trước khi sinh.
_DEATH_VS_OWN_BIRTH: tuple[tuple[str, str], ...] = (
    ("father_death_year", "father_date_of_birth"),
    ("mother_death_year", "mother_date_of_birth"),
)

# Cha/mẹ phải còn sống ở thời điểm đương đơn ra đời. Cha có thể mất TRƯỚC khi con sinh
# (thụ thai rồi mất) → cho phép sớm hơn 1 năm; mẹ thì không.
_DEATH_VS_APPLICANT_BIRTH: tuple[tuple[str, int], ...] = (
    ("father_death_year", 1),
    ("mother_death_year", 0),
)


def enforce_ds260_temporal_plausibility(sections_out: list[dict[str, Any]]) -> None:
    """Xoá năm mất VÔ LÝ về mặt thời gian thay vì in lên form pháp lý.

    Lỗi thực tế (Case D): cha đương đơn ghi mất năm 1968 trong khi đương đơn sinh 1973 —
    không ai phát hiện vì không có kiểm tra nào. Chỉ xoá khi CHẮC CHẮN vô lý; thiếu dữ
    liệu để so sánh thì giữ nguyên cho người review.
    """
    idx = _index_fields_by_key(sections_out)
    applicant_birth_year = _year_of(_field_value(idx, "date_of_birth"))

    def _drop(key: str, reason: str) -> None:
        field = idx.get(key)
        if field and (field.get("value") or "").strip():
            _set_value(field, "", reason)

    for death_key, birth_key in _DEATH_VS_OWN_BIRTH:
        dy = _year_of(_field_value(idx, death_key))
        by = _year_of(_field_value(idx, birth_key))
        if dy is not None and by is not None and dy < by:
            _drop(death_key, "death_year_before_own_birth")

    if applicant_birth_year is not None:
        for death_key, slack in _DEATH_VS_APPLICANT_BIRTH:
            dy = _year_of(_field_value(idx, death_key))
            if dy is not None and dy < applicant_birth_year - slack:
                _drop(death_key, "death_year_before_applicant_birth")


def downgrade_fabricated_date_precision(
    sections_out: list[dict[str, Any]],
    records: list[ApplicantDocRecord],
) -> None:
    """Worksheet chỉ ghi NĂM mà form lại xuất NGÀY ĐẦY ĐỦ → rút về đúng độ chi tiết đã khai.

    Lỗi thực tế: KHAI ghi cha sinh '1963' → xuất 'Jan 01, 1963'; KHAI ghi cha/mẹ 'Mất'
    (không ngày) → xuất '07 September 2006'. Đây là bịa dữ liệu trên form pháp lý.
    Chỉ áp dụng khi giá trị LẤY TỪ worksheet — ngày đầy đủ trên giấy tờ chính thức
    (khai sinh, chứng tử) vẫn giữ nguyên vì đó là nguồn đáng tin.
    """
    from app.services.ds260_customer_keys import normalize_ds260_customer_raw
    from app.services.ds260_dates import is_date_field_key, is_partial_date_value

    ws_rec = pick_latest_record(records, "ds260_customer_form")
    if not ws_rec:
        return
    ws = normalize_ds260_customer_raw(_merge_raw_dict(ws_rec))
    if not ws:
        return
    mappings = flatten_ds260_mappings()

    for sec in sections_out:
        for field in sec.get("fields", []):
            key = field.get("key", "")
            val = (field.get("value") or "").strip()
            if not val or not is_date_field_key(key):
                continue
            if (field.get("source") or {}).get("document_type") != "ds260_customer_form":
                continue
            if not parse_full_date(val):
                continue  # đã là một phần → không có gì để rút
            mapping = mappings.get(key)
            cand_keys = [key]
            if mapping:
                cand_keys += [mapping.field, *(mapping.aliases or ())]
            for ck in cand_keys:
                ws_val = (ws.get(ck) or "").strip()
                if not ws_val:
                    continue
                if is_partial_date_value(ws_val):
                    field["value"] = ws_val
                    field.setdefault("source", {})
                    field["source"]["derived"] = "date_precision_downgraded_to_source"
                break


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
    all_case_records = list(records)
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
    case_members_all: list[Any] = []
    if applicant:
        case_members_all = await load_case_members(db, applicant_id)

    member_ctx: MemberContext | None = None
    if applicant:
        mid = member_id
        if isinstance(mid, str):
            mid = uuid.UUID(mid)
        member_ctx = await resolve_member_context(db, applicant, mid)

    person_name = member_ctx.display_name if member_ctx else (applicant.display_name if applicant else "")
    member_number = (
        member_number_map(case_members_all).get(member_ctx.id) if member_ctx else None
    )
    # Hồ sơ gia đình: chỉ dùng worksheet DS-260 đúng người (tránh lấy nhầm của thành viên khác).
    records = scope_worksheets_to_person(
        records, person_name, is_family_case=len(case_members_all) > 1
    )
    # application_form (Job Application) không có field tên để so khớp như worksheet — dùng
    # tên file/OCR qua resolve_doc_records_member_numbers (cùng cơ chế identity_outlier) để
    # loại application_form của THÀNH VIÊN KHÁC ra khỏi enrich-fill/so sánh của người đang xem
    # (báo lỗi thực tế 2026-08-05: địa chỉ/SĐT của người A bị điền/so nhầm sang form người B).
    if member_ctx and len(case_members_all) > 1 and member_number:
        from app.services.family_case import resolve_doc_records_member_numbers

        numbers_by_record = await resolve_doc_records_member_numbers(db, applicant_id, records)
        records = [
            r
            for r in records
            if r.doc_type != "application_form" or numbers_by_record.get(id(r)) == member_number
        ]
    # Con và cháu (nội/ngoại) dùng chung luồng "thành viên phụ thuộc": thông tin cá nhân
    # lấy từ GKS/hộ chiếu của chính họ, ẩn các section vợ/chồng/ly hôn/con.
    is_child_member = member_ctx is not None and member_ctx.role in ("child", "grandchild")
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
            if sec.id == "section_a_personal" and mapping.key == "current_marital_status":
                rec = None
                value, source_field = "", mapping.field
                src_extra = {}
            elif sec.id == "section_previous_spouse":
                rec = None
                value, source_field = "", mapping.field
                src_extra = {}
            elif sec.id == "section_children" and (
                mapping.key.startswith("children_") or re.match(r"^child_\d+_", mapping.key)
            ):
                rec = None
                value, source_field = "", mapping.field
                src_extra = {}
            else:
                src_extra: dict[str, Any] = {}
                if mapping.key in _WORK_CURRENT_JOB_KEYS:
                    value, source_field, rec, src_extra = resolve_work_current_job_field(
                        records,
                        mapping,
                        resolutions,
                        person_name=person_name if member_ctx else None,
                    )
                elif mapping.key == "work_prior_jobs_history":
                    value, source_field, rec, src_extra = resolve_work_prior_jobs_field(
                        records,
                        mapping,
                        resolutions,
                        person_name=person_name if member_ctx else None,
                    )
                # Cha/mẹ tên: bắt buộc lấy từ DS-260 worksheet, không dùng BC/Luồng 1.
                # BC có tier 0 trong resolve_luong1_ds260_field → sẽ thắng nếu không override.
                elif mapping.key in _PARENT_NAME_KEYS:
                    value, source_field, rec, src_extra = resolve_customer_form_field(
                        records, "ds260_customer_form", mapping
                    )
                elif mapping.document in LUONG1_DOC_TYPES:
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
                    wk_fk_suffixed = worksheet_conflict_field_key(
                        mapping.key, member_number if len(case_members_all) > 1 else None
                    )
                    wk_fk_plain = worksheet_conflict_field_key(mapping.key)
                    chosen = None
                    if wk_fk_suffixed in resolutions:
                        chosen = resolutions[wk_fk_suffixed]
                    elif wk_fk_plain in resolutions:
                        chosen = resolutions[wk_fk_plain]

                    if chosen is not None and not is_child_member:
                        apply_ws = True
                        if mapping.key == "current_marital_status":
                            apply_ws = False
                        elif mapping.key in {
                            "applicant_name",
                            "date_of_birth",
                            "passport_number",
                            "gender",
                        } and person_name and chosen and not _names_same_person(chosen, person_name):
                            apply_ws = False
                        if apply_ws:
                            value = (chosen or "").strip()
                            source_field = mapping.field
                            src_extra = {"derived": "worksheet_conflict_resolution"}

            doc_id = str(rec.source_document_id) if rec and rec.source_document_id else None
            actual_doc_type = rec.doc_type if rec else mapping.document
            source_meta: dict[str, Any] = {
                "document_type": actual_doc_type,
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
            death_rec = pick_latest_record(records, "death_certificate")
            father_name = next(
                (f.get("value") or "" for f in fields_out if f.get("key") == "father_full_name"),
                "",
            )
            enrich_parent_death_from_death_cert(fields_out, death_rec, "father", father_name)
        if sec.id == "section_mother" and not is_child_member:
            death_rec = pick_latest_record(records, "death_certificate")
            mother_name = next(
                (f.get("value") or "" for f in fields_out if f.get("key") == "mother_full_name"),
                "",
            )
            enrich_parent_death_from_death_cert(fields_out, death_rec, "mother", mother_name)
        if sec.id == "section_a_personal":
            if not is_child_member:
                divorce_rec = pick_latest_record(records, "divorce")
                marriage_rec, marriage_ref = pick_luong1_pair(records, "marriage_certificate")
                enrich_marital_status_from_documents(
                    fields_out,
                    divorce_rec,
                    marriage_rec=marriage_rec,
                    marriage_ref=marriage_ref,
                    passport_rec=passport_rec,
                    passport_ref=passport_ref,
                    death_rec=pick_latest_record(records, "death_certificate"),
                )
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
        if sec.id == "section_security" and not is_child_member:
            if member_ctx and person_name:
                jud_rec, jud_ref = pick_luong1_pair_for_person(
                    records, "judicial_certificate", person_name
                )
            else:
                jud_rec, jud_ref = pick_luong1_pair(records, "judicial_certificate")
            enrich_arrested_convicted_from_judicial(fields_out, jud_rec or jud_ref)
        if sec.id == "section_divorce" and not is_child_member:
            divorce_rec = pick_latest_record(records, "divorce")
            enrich_divorce_section_from_record(fields_out, divorce_rec)
        if sec.id == "section_spouse" and not is_child_member:
            marriage_rec, marriage_ref = pick_luong1_pair(all_case_records, "marriage_certificate")
            divorce_rec = pick_latest_record(all_case_records, "divorce")
            if has_applicable_marriage_certificate(
                marriage_rec, marriage_ref, passport_rec, passport_ref
            ) and not _marriage_is_the_divorced_one(
                marriage_rec, marriage_ref, divorce_rec, passport_rec, passport_ref
            ):
                birth_certs = list_birth_certificate_records(all_case_records)
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
                spouse_name = _spouse_name_from_marriage(marriage_rec or marriage_ref, passport_rec)
                if not spouse_name and case_members_all:
                    spouse_m = next((m for m in case_members_all if getattr(m, "role", "") == "spouse"), None)
                    if not spouse_m and member_ctx and member_ctx.role == "spouse":
                        spouse_m = next((m for m in case_members_all if getattr(m, "role", "") == "principal"), None)
                    if spouse_m:
                        spouse_name = spouse_m.display_name

                # 1. Bổ sung nghề nghiệp và đồng bộ thông tin từ records trong cùng bộ hồ sơ (family case)
                enrich_spouse_occupation_from_spouse_records(
                    fields_out, all_case_records, spouse_name, person_name=person_name
                )
                sync_spouse_fields_from_spouse_records(
                    fields_out, all_case_records, spouse_name, person_name=person_name
                )

                # 2. Bổ sung từ hồ sơ applicant phối ngẫu riêng (nếu có)
                if applicant:
                    await enrich_spouse_occupation_from_spouse_applicant(
                        fields_out, db, applicant, marriage_rec or marriage_ref, passport_rec
                    )
                    # Sync ALL spouse fields từ DS-260 của vợ/chồng (family case)
                    await sync_spouse_fields_from_spouse_applicant(
                        fields_out, db, applicant, marriage_rec or marriage_ref, passport_rec
                    )
            else:
                clear_spouse_section_fields(fields_out)
        if sec.id == "section_previous_spouse" and not is_child_member:
            divorce_rec = pick_latest_record(records, "divorce")
            marriage_rec, marriage_ref = pick_luong1_pair(records, "marriage_certificate")
            # Khi tái hôn cùng người (same person remarried), vẫn điền Previous Spouse
            # vì giấy ly hôn mô tả cuộc hôn nhân trước với cùng người đó
            is_same_person_remarried = (
                bool(divorce_rec)
                and bool(marriage_rec or marriage_ref)
                and not _marriage_is_the_divorced_one(
                    marriage_rec, marriage_ref, divorce_rec, passport_rec, passport_ref
                )
            )
            if divorce_rec:
                enrich_previous_spouse_from_divorce(
                    fields_out, divorce_rec, passport_rec,
                    is_same_person_remarried=is_same_person_remarried,
                )
            else:
                # Không có giấy ly hôn — thử phối ngẫu cũ đã qua đời (goá).
                enrich_previous_spouse_from_death(
                    fields_out, records, passport_rec, passport_ref
                )
        if sec.id == "section_children" and not is_child_member:
            child_recs = list_child_birth_records(all_case_records, filename_map=filename_map)
            enrich_children_section_from_birth_certs(
                fields_out,
                child_recs,
                all_records=all_case_records,
                filename_map=filename_map,
                case_members=case_members_all,
                applicant_name=person_name,
                member_role=member_ctx.role if member_ctx else None,
            )
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

    for sec in sections_out:
        if sec["id"] == "section_work_education":
            enrich_work_education_from_worksheet(sec["fields"], records, filename_map)

    reattribute_matching_worksheet_sources(sections_out, records, resolutions, filename_map)

    if is_child_member and person_name:
        clear_child_member_unscoped_sections(sections_out, records, person_name)

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

    marriage_rec, marriage_ref = pick_luong1_pair(all_case_records, "marriage_certificate")
    divorce_rec = pick_latest_record(all_case_records, "divorce")
    if not has_applicable_marriage_certificate(
        marriage_rec, marriage_ref, passport_rec, passport_ref
    ) or _marriage_is_the_divorced_one(
        marriage_rec, marriage_ref, divorce_rec, passport_rec, passport_ref
    ):
        for sec in sections_out:
            if sec["id"] == "section_spouse":
                clear_spouse_section_fields(sec["fields"])
    else:
        # Có vợ/chồng hợp lệ nhưng worksheet chưa trả lời — mặc định "Yes" (đang chung hồ sơ).
        for sec in sections_out:
            if sec["id"] != "section_spouse":
                continue
            for field in sec["fields"]:
                if field.get("key") != "spouse_immigrating":
                    continue
                if (field.get("value") or "").strip():
                    continue
                field["value"] = "Yes"
                field.setdefault("source", {})
                field["source"]["document_type"] = "ds260_customer_form"
                field["source"]["source_field"] = "spouse_immigrating"
                field["source"]["derived"] = "spouse_immigrating_default_yes"

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
        member_number=member_number,
    )
    manual_overrides = await load_ds260_manual_overrides(
        db, applicant_id, member_id=member_ctx.id if member_ctx else None
    )
    if is_child_member:
        clear_child_adult_only_ds260_sections(sections_out)
        case_members = await load_case_members(db, applicant_id)
        apply_child_sections_from_birth_cert(
            sections_out,
            child_bc,
            records=records,
            members=case_members,
            role=member_ctx.role if member_ctx else "child",
        )
        if child_bc:
            for sec in sections_out:
                enrich_child_member_personal(sec["fields"], child_bc, passport_rec)
        # Con/cháu mặc định độc thân (Single) trên DS-260.
        for sec in sections_out:
            if sec["id"] != "section_a_personal":
                continue
            for field in sec["fields"]:
                if field.get("key") == "current_marital_status":
                    field["value"] = "Single"
                    field["source"] = {
                        **empty_ds260_field_source(),
                        "derived": "child_default_single",
                    }

    if member_ctx is not None and member_ctx.role == "sibling":
        from app.services.family_case import apply_sibling_parent_fallback

        apply_sibling_parent_fallback(sections_out, records, case_members_all, person_name)

    apply_ds260_manual_overrides(sections_out, manual_overrides)

    reconcile_previous_spouse_with_marital_status(sections_out)

    # Giá trị mặc định (CHỌN YES/NO, LUÔN KHAI CÓ) — chỉ điền khi vẫn còn trống.
    apply_ds260_default_values(sections_out)

    upgrade_partial_dates_from_worksheet(sections_out, records, filename_map)
    # Ngược chiều với hàm trên: giá trị LẤY TỪ worksheet không được chi tiết hơn chính
    # worksheet (KHAI '1963' thì không được xuất 'Jan 01, 1963').
    downgrade_fabricated_date_precision(sections_out, records)
    enrich_native_name_from_worksheet(sections_out, records)

    from app.services.ds260_dates import format_sections_date_display

    format_sections_date_display(sections_out)

    from app.services.ds260_english_output import format_sections_english_output

    format_sections_english_output(sections_out)

    # Chốt Yes/No (N/A/trống-không-dữ-liệu → No) + rút '*_death_year' về năm. Chạy SAU khi đã
    # chuẩn hóa tiếng Anh để thao tác trên đúng giá trị hiển thị cuối cùng.
    reconcile_ds260_yesno_and_death_year(sections_out)

    # Năm mất vô lý (trước khi chính người đó sinh, hoặc trước khi đương đơn ra đời)
    # → xoá thay vì in lên form. Chạy sau khi '*_death_year' đã được rút về năm.
    enforce_ds260_temporal_plausibility(sections_out)

    # Thống nhất 'N/A' vs 'No' vs để trống (SĐT/email, số con, ô Tỉnh).
    normalize_ds260_na_conventions(sections_out)

    # Hậu xử lý nghiệp vụ: chuẩn hóa nơi sinh, đối chiếu còn sống / địa chỉ cha mẹ.
    reconcile_parent_living_status(sections_out)
    reconcile_parent_spouse_addresses(sections_out)
    reconcile_parent_living_addresses(sections_out)
    normalize_ds260_place_fields(sections_out)

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

    # Thêm warnings vào section nếu có vấn đề cần lưu ý.
    _attach_section_warnings(sections_out)

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
        rec = standard_rec or reference_rec
        if not rec:
            continue
        field["value"] = val
        field["source"] = {
            "document_type": doc_type,
            "source_field": mapping.field,
            "derived": derived,
            "record_id": str(rec.id),
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
