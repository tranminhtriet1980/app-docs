"""
Registry for 8 standard immigration document templates (Data test folder).

Each type maps to one logical table row per applicant (variant=standard = Luồng 1).
Nguồn đối chiếu: upload cùng loại giấy + hậu tố ``_new`` (variant=exception).
Khi Luồng 1 và đối chiếu khác nhau → user chọn giá trị (Conflict ds260.*).
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal

from app.services.ds260_normalize import normalize_gender

DocVariant = Literal["standard", "exception"]

EXCEPTION_SUFFIX = "_new"


@dataclass(frozen=True)
class DocTypeDef:
    code: str
    display_name: str
    filename_tokens: tuple[str, ...]
    form_section: str
    extract_keys: tuple[str, ...]
    profile_keys: tuple[str, ...]


# I. File mẫu chuẩn — 8 loại (tên thống nhất với thư mục Data test)
DOCUMENT_REGISTRY: tuple[DocTypeDef, ...] = (
    DocTypeDef(
        code="passport",
        display_name="Passport",
        filename_tokens=("passport", "ho chieu", "hộ chiếu"),
        form_section="DS-260 mục A — Passport (Personal + Travel Document)",
        extract_keys=(
            "full_name", "family_name", "given_names",
            "date_of_birth", "place_of_birth", "birth_city", "birth_state", "birth_country",
            "gender", "sex", "nationality", "id_card_number",
            "passport_type", "country_code", "passport_number",
            "issue_date", "expiration_date", "expiry_date",
            "place_of_issue", "issuing_country", "issuing_authority",
        ),
        profile_keys=(
            "identity.family_name", "identity.given_names", "identity.full_name",
            "identity.gender", "identity.date_of_birth", "identity.birth_city",
            "identity.birth_state", "identity.birth_country", "identity.nationality",
            "passport.number", "passport.issue_date", "passport.expiry_date",
            "passport.issuing_country",
        ),
    ),
    DocTypeDef(
        code="judicial_certificate",
        display_name="JUDICIAL CERTIFICATE",
        filename_tokens=("judicial", "ly lich", "lý lịch", "lltp"),
        form_section="DS-160 — Lý lịch tư pháp",
        extract_keys=(
            "full_name", "date_of_birth", "nationality", "father_name", "mother_name",
            "document_number", "issue_date", "document_type",
        ),
        profile_keys=(
            "identity.full_name", "identity.date_of_birth", "identity.nationality",
            "family.father_name", "family.mother_name",
            "other.document_number", "other.document_type",
        ),
    ),
    DocTypeDef(
        code="divorce",
        display_name="Divorce",
        filename_tokens=("divorce", "ly hon", "ly hôn", "qdst"),
        form_section="DS-160 / DS-260 — Ly hôn",
        extract_keys=(
            "husband_full_name", "wife_full_name", "husband_date_of_birth", "wife_date_of_birth",
            "spouse_name", "plaintiff_name", "defendant_name",
            "marriage_date", "divorce_date", "document_number", "document_type",
        ),
        profile_keys=(
            "identity.marital_status", "family.previous_spouses_used",
            "family.previous_spouses_history", "family.spouse_name",
            "other.document_number",
        ),
    ),
    DocTypeDef(
        code="birth_certificate",
        display_name="Birth certificate",
        filename_tokens=("birth certificate", "birth cert", "giay khai sinh", "gks", "khai sinh"),
        form_section="DS-160 — Giấy khai sinh (chủ hồ sơ)",
        extract_keys=(
            "full_name", "date_of_birth", "place_of_birth", "gender",
            "father_name", "father_surname", "father_given_names",
            "father_date_of_birth", "father_dob", "father_year_of_birth",
            "father_address", "father_residence", "father_nationality",
            "mother_name", "mother_surname", "mother_given_names", "mother_full_name",
            "mother_date_of_birth", "mother_dob", "mother_year_of_birth",
            "mother_address", "mother_residence", "mother_nationality",
            "registration_number",
        ),
        profile_keys=(
            "identity.full_name", "identity.date_of_birth", "identity.place_of_birth",
            "identity.gender", "family.father_name", "family.mother_name",
        ),
    ),
    DocTypeDef(
        code="death_certificate",
        display_name="Death certificate",
        filename_tokens=("death certificate", "death cert", "giay bao tu", "báo tử"),
        form_section="DS-260 — Giấy báo tử",
        extract_keys=(
            "deceased_full_name", "date_of_death", "place_of_death",
            "relationship_to_applicant", "document_number",
        ),
        profile_keys=(
            "family.father_is_living", "family.father_death_year",
            "family.mother_is_living", "family.mother_death_year",
            "family.spouse_name",
        ),
    ),
    DocTypeDef(
        code="marriage_certificate",
        display_name="Marriage certificate",
        filename_tokens=("marriage certificate", "marriage cert", "giay ket hon", "kết hôn"),
        form_section="DS-160 / DS-260 — Giấy kết hôn",
        extract_keys=(
            "husband_full_name", "wife_full_name", "spouse_name", "spouse_full_name",
            "husband_name", "wife_name", "husband_surname", "wife_surname",
            "husband_given_names", "wife_given_names", "spouse_surname", "spouse_given_names",
            "husband_date_of_birth", "wife_date_of_birth", "spouse_date_of_birth",
            "husband_birth_city", "wife_birth_city", "spouse_birth_city",
            "husband_birth_state", "wife_birth_state", "spouse_birth_state",
            "husband_birth_country", "wife_birth_country", "spouse_birth_country",
            "husband_address", "wife_address", "spouse_address",
            "husband_occupation", "wife_occupation", "spouse_occupation",
            "marriage_date", "marriage_place", "marriage_city", "marriage_state", "marriage_country",
            "document_number", "registration_number",
        ),
        profile_keys=(
            "identity.marital_status", "family.spouse_name",
            "family.spouse_marriage_date", "family.spouse_marriage_city",
        ),
    ),
    DocTypeDef(
        code="birth_certificate_child",
        display_name="Birth certificate child",
        filename_tokens=(
            "birth certificate child", "birth cert child", "child birth",
            "gks con", "khai sinh con", "con cai",
        ),
        form_section="DS-260 — 5. THÔNG TIN CỦA CON CÁI",
        extract_keys=(
            "child_full_name", "child_date_of_birth", "child_place_of_birth",
            "child_birth_city", "child_birth_state", "child_birth_country",
            "child_gender", "father_name", "mother_name", "registration_number",
        ),
        profile_keys=(
            "family.children_used", "family.children_count", "family.children_history",
        ),
    ),
    DocTypeDef(
        code="military_discharge",
        display_name="Military discharge",
        filename_tokens=("military discharge", "military", "nvqs", "xuat ngu", "xuất ngũ"),
        form_section="DS-160 — Nghĩa vụ quân sự",
        extract_keys=(
            "full_name", "military_country", "military_branch", "military_rank",
            "military_specialty", "service_from_date", "service_to_date", "document_number",
        ),
        profile_keys=(
            "additional.military_served_used", "additional.military_country",
            "additional.military_branch", "additional.military_rank",
            "additional.military_specialty", "additional.military_service_from",
            "additional.military_service_to",
        ),
    ),
)

REGISTRY_BY_CODE: dict[str, DocTypeDef] = {d.code: d for d in DOCUMENT_REGISTRY}
STANDARD_DOCUMENT_TYPES: list[str] = [d.code for d in DOCUMENT_REGISTRY]

# DS-260 worksheet khách khai (mục 3–5) — không thuộc Luồng 1, luôn variant=exception
DS260_CUSTOMER_EXTRACT_KEYS: tuple[str, ...] = (
    "current_address", "address_line1", "address", "street_address", "residential_address",
    "address_city", "city", "contact_city", "current_city",
    "address_state", "state", "province", "state_province", "contact_state", "current_state",
    "postal_code", "zip_code", "postal_zone", "zip",
    "address_country", "country", "contact_country", "current_country",
    "address_from_date", "from_date", "residence_from", "lived_since",
    "other_addresses_since_16", "other_addresses_used", "lived_elsewhere_since_16",
    "other_addresses_history", "prior_addresses", "address_history", "previous_addresses",
    "primary_phone_number", "primary_phone", "phone_primary", "phone", "mobile", "telephone",
    "secondary_phone_number", "secondary_phone", "phone_secondary",
    "work_phone_number", "work_phone", "phone_work",
    "other_phones_used", "other_telephones_used", "other_phone_used_last_5_years",
    "other_phones_history", "other_telephone_numbers", "other_phones_detail",
    "email_address", "email", "primary_email",
    "other_emails_used", "other_email_used", "other_email_used_last_5_years",
    "other_emails_history", "other_email_addresses", "other_emails_detail",
    "social_media_platform", "social_platform", "social_media_provider", "platform_provider",
    "social_media_identifier", "social_identifier", "profile_url", "social_media_url", "facebook_url",
    "other_social_media_used", "other_social_used", "other_social_media_5_years",
    "other_social_history", "other_social_media_history", "other_social_media_detail",
)

SUPPLEMENTAL_DOCUMENT_REGISTRY: tuple[DocTypeDef, ...] = (
    DocTypeDef(
        code="ds260_customer_form",
        display_name="DS-260 (khách khai)",
        filename_tokens=("ds260", "ds 260", "ds-260"),
        form_section="DS-260 toàn bộ worksheet khách khai",
        extract_keys=tuple(),  # dynamic — see get_extract_keys_for_doc_type()
        profile_keys=(),
    ),
    DocTypeDef(
        code="application_form",
        display_name="Application form",
        filename_tokens=(
            "application form",
            "immigrant application",
            "don nop",
            "don xin",
            "application",
        ),
        form_section="DS-260 D — Work / Education / Training",
        extract_keys=(
            "current_address",
            "address_city",
            "address_state",
            "postal_code",
            "address_country",
            "primary_phone_number",
            "email_address",
            "primary_occupation",
            "occupation_other_specify",
            "present_employer",
            "employer_name",
            "employer_address",
            "employer_address_line1",
            "employer_city",
            "employer_state",
            "employer_postal_code",
            "employer_country",
            "job_title",
            "employment_start_date",
            "start_date",
            "other_occupation_used",
            "other_occupation_detail",
            "prior_jobs_10_years_used",
            "prior_jobs_history",
            "middle_school_name",
            "middle_school_address",
            "middle_school_period",
            "high_school_name",
            "high_school_address",
            "high_school_period",
            "college_name",
            "college_address",
            "college_major",
            "college_period",
            "date_signed",
        ),
        profile_keys=(),
    ),
    # US Visa — dán trong passport, có entry stamp Mỹ → been_in_us = Yes
    DocTypeDef(
        code="us_visa",
        display_name="US Visa",
        filename_tokens=("us visa", "visa my", "visa usa", "visa mỹ", "entry stamp"),
        form_section="DS-260 C — Lịch sử đến Mỹ",
        extract_keys=(
            "visa_type",
            "visa_number",
            "visa_issue_date",
            "visa_expiration_date",
            "entry_date",
            "entry_stamp",
            "us_address",
        ),
        profile_keys=(),
    ),
    # Phiếu mô tả & danh sách hồ sơ — checklist thành viên và giấy tờ
    DocTypeDef(
        code="document_checklist",
        display_name="Phiếu mô tả & danh sách hồ sơ",
        filename_tokens=(
            "phieu mo ta & danh sach ho so",
            "phieu mo ta danh sach ho so",
            "phieu mo ta va danh sach ho so",
            "phieu mo ta ho so",
            "phieu mo ta",
            "danh sach ho so",
            "checklist ho so",
            "document checklist",
            "case document checklist",
            "checklist",
            "bang ke giay to",
            "bảng kê giấy tờ",
            "phiếu mô tả & danh sách hồ sơ",
            "phiếu mô tả danh sách hồ sơ",
            "phiếu mô tả",
            "danh sách hồ sơ",
        ),
        form_section="Phiếu mô tả & danh sách hồ sơ (Checklist)",
        extract_keys=(
            "applicant_name",
            "spouse_name",
            "children_count",
            "children_names",
            "checklist_data",
            "notes",
        ),
        profile_keys=(),
    ),
)

RECORDABLE_REGISTRY_BY_CODE: dict[str, DocTypeDef] = {
    **REGISTRY_BY_CODE,
    **{d.code: d for d in SUPPLEMENTAL_DOCUMENT_REGISTRY},
}
# OCR types without full DocTypeDef — vẫn lưu doc record (form_data từ FIELD_MAP)
RECORDABLE_EXTRA_DOC_TYPES: frozenset[str] = frozenset({"address_document", "us_visa"})
RECORDABLE_DOC_TYPES: frozenset[str] = frozenset(RECORDABLE_REGISTRY_BY_CODE) | RECORDABLE_EXTRA_DOC_TYPES

# Canonical upload filename examples (standard vs exception)
CANONICAL_FILENAME_EXAMPLES: dict[str, dict[str, str]] = {
    d.code: {
        "standard": d.display_name,
        "exception": f"{d.display_name}{EXCEPTION_SUFFIX}",
    }
    for d in DOCUMENT_REGISTRY
}
CANONICAL_FILENAME_EXAMPLES["ds260_customer_form"] = {
    "standard": "ds260.pdf",
    "exception": f"DS260{EXCEPTION_SUFFIX}",
}
CANONICAL_FILENAME_EXAMPLES["application_form"] = {
    "standard": "Application form",
    "exception": f"Application form{EXCEPTION_SUFFIX}",
}
CANONICAL_FILENAME_EXAMPLES["us_visa"] = {
    "standard": "US Visa",
    "exception": f"US Visa{EXCEPTION_SUFFIX}",
}
CANONICAL_FILENAME_EXAMPLES["document_checklist"] = {
    "standard": "Phiếu mô tả & danh sách hồ sơ",
    "exception": f"Phiếu mô tả & danh sách hồ sơ{EXCEPTION_SUFFIX}",
}


def _strip_accents(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = re.sub(r"[\u0300-\u036f]", "", s)
    s = s.replace("đ", "d").replace("Đ", "d")
    return unicodedata.normalize("NFC", s).lower()


def _normalize_stem(filename: str) -> str:
    stem = unicodedata.normalize("NFC", Path(filename).stem.lower())
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem


def parse_document_filename(filename: str) -> tuple[str | None, bool]:
    """
    Detect document type and whether this is an exception file (_new suffix).

    Alias normalization: ``Birth certificate child_new.pdf`` → (birth_certificate_child, True)
    — cùng doc_type với bản standard; DS260 lấy bản mới nhất khi fill.
    """
    stem = _normalize_stem(filename)
    stem_clean = _strip_accents(stem)
    is_exception = bool(
        re.search(r"\bnew$", stem) or stem.endswith(" new") or stem_clean.endswith(" new")
    )
    if is_exception:
        stem = re.sub(r"\s+new$", "", stem).strip()
        stem_clean = re.sub(r"\s+new$", "", stem_clean).strip()

    # DS-260 worksheet khách khai — luôn nguồn đối chiếu (exception)
    if re.search(r"\bds[\s\-]?260\b", stem) or stem.replace(" ", "") == "ds260":
        return "ds260_customer_form", True

    # Application form (DS-260 D — công việc / học vấn) — Luồng 1 standard + _new
    # Bắt: "application form", "job application", "immigrant application", "don nop", "don xin"
    if re.search(r"\bapplication\s+form\b", stem) or "immigrant application" in stem:
        return "application_form", is_exception
    if re.search(r"\bjob\s+application\b", stem):
        return "application_form", is_exception
    if re.search(r"\bdon\s+(nop|xin)\b", stem) and "ds" not in stem.replace(" ", ""):
        return "application_form", is_exception

    # US Visa (dán trong passport, có entry stamp Mỹ) — standard + _new
    if re.search(r"\bus\s+visa\b", stem) or "visa my" in stem_clean or "visa usa" in stem or "visa my" in stem:
        return "us_visa", is_exception
    if re.search(r"\bentry\s+stamp\b", stem) or "entry stamp" in stem:
        return "us_visa", is_exception

    # Phiếu mô tả & danh sách hồ sơ (Checklist)
    if (
        "phieu mo ta" in stem_clean
        or "danh sach ho so" in stem_clean
        or "checklist" in stem_clean
        or "bang ke giay to" in stem_clean
        or "bang ke" in stem_clean
    ):
        return "document_checklist", is_exception

    # Longer tokens first (birth certificate child before birth certificate)
    # Quét cả SUPPLEMENTAL registry để bắt token "application" từ application_form
    all_defs = list(DOCUMENT_REGISTRY) + list(SUPPLEMENTAL_DOCUMENT_REGISTRY)
    ranked = sorted(all_defs, key=lambda d: max(len(t) for t in d.filename_tokens), reverse=True)
    for defn in ranked:
        for token in defn.filename_tokens:
            token_clean = _strip_accents(token)
            if token in stem or token_clean in stem_clean:
                return defn.code, is_exception
    return None, is_exception


def canonical_upload_name(doc_type: str, *, exception: bool = False) -> str:
    defn = REGISTRY_BY_CODE.get(doc_type)
    if not defn:
        return doc_type
    base = defn.display_name
    return f"{base}{EXCEPTION_SUFFIX}" if exception else base


# Toàn bộ giá trị coi là "Yes"/"No" hợp lệ — cả không dấu lẫn có dấu (OCR có lúc mất dấu),
# gồm cả kiểu Việt Nam theo thì ("Đã từng...chưa?" → Đã = Yes, Chưa = No).
_YES_TOKENS = frozenset({"YES", "Y", "CO", "CÓ", "TRUE", "1", "DA", "ĐÃ"})
_NO_TOKENS = frozenset({"NO", "N", "KHONG", "KHÔNG", "FALSE", "0", "CHUA", "CHƯA"})


@lru_cache(maxsize=1)
def _yes_no_field_keys() -> frozenset[str]:
    """Field key/field/alias của MỌI câu hỏi Yes/No trong ds260_mapping.json — nhận diện qua
    label có dấu "?" (quy ước nhất quán trong file mapping), thay vì đoán theo tên field
    (nhiều field như been_in_us, issued_us_visa, father_is_living không khớp pattern
    _used/is_ cũ nên trước đây không được chuẩn hoá — báo lỗi thực tế 2026-08-05)."""
    path = Path(__file__).resolve().parents[2] / "data" / "doc_schemas" / "ds260_mapping.json"
    if not path.is_file():
        return frozenset()
    data = json.loads(path.read_text(encoding="utf-8"))
    keys: set[str] = set()
    for sec in data.get("sections", []):
        for f in sec.get("fields", []):
            label = f.get("label") or ""
            if "?" not in label:
                continue
            keys.add((f.get("key") or "").lower())
            keys.add((f.get("field") or "").lower())
            for alias in f.get("aliases") or ():
                keys.add(alias.lower())
    keys.discard("")
    return frozenset(keys)


def format_field_value(key: str, value: str | None) -> str:
    """Normalize extracted values for form fill."""
    if value is None:
        return ""
    val = str(value).strip()
    if not val:
        return ""

    key_l = key.lower()
    if "date" in key_l or key_l.endswith("_dob") or key_l == "dob":
        val = _format_date(val)
    elif key_l in {"gender", "sex"}:
        normalized = normalize_gender(val)
        if normalized in {"Male", "Female"}:
            val = normalized.upper()
    elif "name" in key_l or key_l.endswith("_name"):
        val = val.upper()
    elif key_l.endswith("_used") or key_l.startswith("is_") or key_l in _yes_no_field_keys():
        u = val.upper()
        if u in _YES_TOKENS:
            val = "Yes"
        elif u in _NO_TOKENS:
            val = "No"
    return re.sub(r"\s+", " ", val).strip()


def _format_date(val: str) -> str:
    val = val.strip()
    for fmt_in, fmt_out in [
        (r"^(\d{4})-(\d{2})-(\d{2})$", r"\1-\2-\3"),
    ]:
        if re.match(fmt_in, val):
            return val
    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$", val)
    if m:
        d, mo, y = m.groups()
        return f"{y}-{mo.zfill(2)}-{d.zfill(2)}"
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y"):
        try:
            from datetime import datetime

            return datetime.strptime(val, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return val


_BIRTH_CERT_CANONICAL_ALIASES: dict[str, tuple[str, ...]] = {
    "mother_surname": ("mother_family_name", "mother_last_name"),
    "mother_given_names": ("mother_first_name", "mother_given_name"),
    "mother_name": ("mother_full_name",),
    "mother_date_of_birth": ("mother_dob", "mother_birth_date", "mother_year_of_birth"),
    # KHÔNG alias mother_city (nơi THƯỜNG TRÚ) vào mother_birth_city, và KHÔNG alias
    # mother_address/mother_residence vào mother_place_of_birth, và KHÔNG alias mother_country/
    # mother_nationality (QUỐC TỊCH) vào mother_birth_country — giấy khai sinh VN chỉ ghi nơi
    # thường trú + quốc tịch HIỆN TẠI của mẹ, KHÔNG ghi nơi/quốc gia mẹ được SINH RA. Coi
    # thường trú/quốc tịch là nơi sinh sẽ ra kết quả SAI (khách yêu cầu 2026-08-12: tránh đọc
    # thông tin thường trú/quốc tịch cha/mẹ ra thành nơi sinh của họ).
    "mother_birth_city": ("mother_city_of_birth",),
    "mother_place_of_birth": ("mother_birth_place", "mother_birth_address"),
    "mother_birth_country": (),
    "father_surname": ("father_family_name", "father_last_name"),
    "father_given_names": ("father_first_name", "father_given_name"),
    "father_name": ("father_full_name",),
    "father_date_of_birth": ("father_dob", "father_birth_date", "father_year_of_birth"),
    "father_birth_city": ("father_city_of_birth",),
    "father_place_of_birth": ("father_birth_place", "father_birth_address"),
    "father_birth_country": (),
}


def normalize_birth_certificate_raw(raw: dict[str, str]) -> dict[str, str]:
    """Gộp alias OCR → field chuẩn (cha/mẹ trên giấy khai sinh VN)."""
    out: dict[str, str] = {}
    for k, v in raw.items():
        if v is None:
            continue
        s = v.strip() if isinstance(v, str) else str(v).strip()
        if s:
            out[k] = s
    for canonical, aliases in _BIRTH_CERT_CANONICAL_ALIASES.items():
        if out.get(canonical):
            continue
        for alias in aliases:
            val = (out.get(alias) or "").strip()
            if val:
                out[canonical] = val
                break
    return out


BIRTH_CERT_CANONICAL_ALIASES = _BIRTH_CERT_CANONICAL_ALIASES


def normalize_birth_certificate_child_raw(raw: dict[str, str]) -> dict[str, str]:
    """Chuẩn hóa OCR giấy khai sinh con → keys section DS-260."""
    out = dict(raw)
    if not out.get("child_full_name"):
        for key in ("full_name", "name"):
            if out.get(key):
                out["child_full_name"] = out[key]
                break
    if not out.get("child_date_of_birth"):
        for key in ("date_of_birth", "dob"):
            if out.get(key):
                out["child_date_of_birth"] = out[key]
                break
    pob = (out.get("child_place_of_birth") or out.get("place_of_birth") or "").strip()
    if pob and not out.get("child_place_of_birth"):
        out["child_place_of_birth"] = pob
    return out


def build_form_data(doc_type: str, raw: dict[str, str]) -> dict[str, str]:
    """Map raw extract keys → formatted form-ready values."""
    if doc_type == "birth_certificate":
        raw = normalize_birth_certificate_raw(raw)
    if doc_type == "birth_certificate_child":
        raw = normalize_birth_certificate_child_raw(raw)
    if doc_type == "ds260_customer_form":
        from app.services.ds260_customer_keys import normalize_ds260_customer_raw

        raw = normalize_ds260_customer_raw(raw)

    defn = RECORDABLE_REGISTRY_BY_CODE.get(doc_type)
    if not defn:
        return {k: format_field_value(k, v) for k, v in raw.items() if v}

    out: dict[str, str] = {}
    for key in defn.extract_keys:
        if key in raw and raw[key]:
            out[key] = format_field_value(key, raw[key])
    for k, v in raw.items():
        if k not in out and v:
            out[k] = format_field_value(k, v)
    return out
