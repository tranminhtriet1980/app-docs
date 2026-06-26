"""Chuẩn hóa giá trị DS-260 xuất Review/Word — 100% tiếng Anh, không dấu."""

from __future__ import annotations

import re
from typing import Any

from app.services.birth_location import (
    canonical_vn_city,
    derive_country_from_place,
    format_birth_city_display,
    format_person_name_ascii,
    format_place_name_title,
)

_YES_MARKERS = frozenset(
    {
        "yes",
        "y",
        "co",
        "có",
        "true",
        "1",
        "male",
        "nam",
        "married",
        "da ket hon",
        "đã kết hôn",
    }
)
_NO_MARKERS = frozenset(
    {
        "no",
        "n",
        "khong",
        "không",
        "false",
        "0",
        "female",
        "nu",
        "nữ",
        "single",
        "doc than",
        "độc thân",
        "divorced",
        "ly hon",
        "ly hôn",
        "widowed",
        "goa",
        "goá",
    }
)

_GENDER_MAP = {
    "m": "Male",
    "male": "Male",
    "nam": "Male",
    "f": "Female",
    "female": "Female",
    "nu": "Female",
    "nữ": "Female",
}

_MARITAL_MAP = {
    "single": "Single",
    "doc than": "Single",
    "độc thân": "Single",
    "married": "Married",
    "da ket hon": "Married",
    "đã kết hôn": "Married",
    "ket hon": "Married",
    "kết hôn": "Married",
    "divorced": "Divorced",
    "ly hon": "Divorced",
    "ly hôn": "Divorced",
    "widowed": "Widowed",
    "goa": "Widowed",
    "goá": "Widowed",
    "separated": "Legally Separated",
    "ly than": "Legally Separated",
    "ly thân": "Legally Separated",
}

_NAME_KEY_RE = re.compile(
    r"(^|_)(name|surname|given_names|full_name|husband_name|wife_name|deceased_name)(_|$)",
    re.I,
)
_COUNTRY_KEY_RE = re.compile(r"(^|_)(country|nationality)(_|$)", re.I)
_CITY_KEY_RE = re.compile(r"(^|_)(city|birth_city|marriage_city)(_|$)", re.I)
_STATE_KEY_RE = re.compile(r"(^|_)(state|birth_state|marriage_state)(_|$)", re.I)
_ADDRESS_KEY_RE = re.compile(r"(^|_)(address|history)(_|$)", re.I)
_YESNO_KEY_RE = re.compile(
    r"(^|_)(used|is_living|immigrating|lives_with|military_served)(_|$)|^children_used$",
    re.I,
)
_GENDER_KEY_RE = re.compile(r"(^|_)(gender|sex)(_|$)", re.I)
_MARITAL_KEY_RE = re.compile(r"current_marital_status", re.I)
_SKIP_KEYS = frozenset(
    {
        "passport_number",
        "id_card_number",
        "country_code",
        "postal_code",
        "father_postal_code",
        "mother_postal_code",
        "email",
        "primary_phone",
        "secondary_phone",
        "work_phone",
        "social_media_identifier",
        "judicial_certificate_number",
        "divorce_document_number",
        "marriage_document_number",
        "military_document_number",
        "death_document_number",
        "father_death_year",
        "mother_death_year",
        "children_count",
    }
)


def _norm_token(s: str) -> str:
    from app.services.birth_location import normalize_location

    return normalize_location(s)


def format_yes_no(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    token = _norm_token(v)
    if token in _YES_MARKERS or token.startswith("yes"):
        return "Yes"
    if token in _NO_MARKERS or token.startswith("no"):
        return "No"
    # Câu trả lời khẳng định kiểu VN cho "sống cùng/nhập cư" (vd. "đang ở cùng bố mẹ").
    if any(t in token for t in ("dang o", "o cung", "song chung", "o voi", "cung bo me", "cung gia dinh")):
        return "Yes"
    # Còn sống / đã mất (Is your father/mother still living?).
    if "con song" in token:
        return "Yes"
    if any(t in token for t in ("da mat", "qua doi", "da chet", "mat roi")):
        return "No"
    if v.lower() in {"yes", "no"}:
        return v.title()
    return format_place_name_title(v)


def format_gender(value: str) -> str:
    token = _norm_token(value)
    return _GENDER_MAP.get(token, format_place_name_title(value))


def format_marital_status(value: str) -> str:
    token = _norm_token(value)
    if token in _MARITAL_MAP:
        return _MARITAL_MAP[token]
    for k, label in _MARITAL_MAP.items():
        if k in token:
            return label
    return format_place_name_title(value)


def format_native_name(value: str) -> str:
    """Họ tên bản ngữ (Full Name in Native Language) — GIỮ dấu tiếng Việt, chuẩn hóa khoảng trắng + IN HOA."""
    return " ".join((value or "").split()).upper()


def format_country_value(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    mapped = derive_country_from_place(v)
    if mapped:
        return mapped
    return format_place_name_title(v)


def format_ds260_field_value(key: str, value: str) -> str:
    """Map OCR/VN text → English display for DS-260."""
    v = (value or "").strip()
    if not v or key in _SKIP_KEYS:
        return v
    if "date" in key.lower() or key.endswith("_dob") or key.endswith("_death_year"):
        return v

    if key.endswith("_native"):
        return format_native_name(v)

    if key in {"nationality", "judicial_nationality"}:
        token = _norm_token(v)
        if token in {"vietnam", "viet nam", "vietnamese"}:
            return "Vietnamese"
        return format_place_name_title(v)
    if _GENDER_KEY_RE.search(key):
        return format_gender(v)
    if _MARITAL_KEY_RE.search(key):
        return format_marital_status(v)
    if _YESNO_KEY_RE.search(key):
        return format_yes_no(v)
    if _NAME_KEY_RE.search(key):
        return format_person_name_ascii(v)
    if _COUNTRY_KEY_RE.search(key):
        return format_country_value(v)
    if _CITY_KEY_RE.search(key):
        canon = canonical_vn_city(v)
        if canon:
            return canon
        if "birth_city" in key:
            return format_birth_city_display(v)
        return format_place_name_title(v)
    if _STATE_KEY_RE.search(key):
        return format_place_name_title(v)
    if _ADDRESS_KEY_RE.search(key) or key in {"current_address", "father_address", "mother_address", "spouse_address"}:
        return format_place_name_title(v)
    if key.endswith("_occupation") or key.endswith("_occupation_other"):
        return format_place_name_title(v)
    if key.endswith("_branch") or key.endswith("_rank") or key.endswith("_specialty"):
        return format_place_name_title(v)

    return format_place_name_title(v)


def format_sections_english_output(sections: list[dict[str, Any]]) -> None:
    for sec in sections:
        for field in sec.get("fields", []):
            key = field.get("key", "")
            val = field.get("value") or ""
            if not str(val).strip():
                continue
            field["value"] = format_ds260_field_value(key, str(val))
