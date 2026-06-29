"""DS-260 worksheet khách khai — keys OCR, chuẩn hóa field → mapping DS-260."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

# OCR hay trả tên field giấy tờ → key DS-260 mapping.
# Không map document_number → passport_number ở đây — chỉ khi có ngữ cảnh passport
# (xem _allow_document_number_for_field / _should_map_document_number_to_passport).
DS260_CUSTOMER_KEY_REMAP: dict[str, str] = {
    "full_name": "applicant_name",
    "name": "applicant_name",
    "full_name_native": "applicant_name_native",
    "name_native_language": "applicant_name_native",
    "native_full_name": "applicant_name_native",
    "sex": "gender",
    "marital_status": "current_marital_status",
    "dob": "date_of_birth",
    "birth_date": "date_of_birth",
    "city_of_birth": "birth_city",
    "state_of_birth": "birth_state",
    "country_of_birth": "birth_country",
    "country_of_nationality": "nationality",
    "passport_no": "passport_number",
    "passport_id": "passport_number",
    "passport_document_number": "passport_number",
    "date_of_issue": "passport_issue_date",
    "passport_issue_date": "passport_issue_date",
    "date_of_expiry": "passport_expiration_date",
    "expiry_date": "passport_expiration_date",
    "expiration_date": "passport_expiration_date",
    "passport_expiry_date": "passport_expiration_date",
    "country_of_issue": "passport_issuing_country",
    "issuing_country": "passport_issuing_country",
    "issuing_authority": "passport_place_of_issue",
    "authority": "passport_place_of_issue",
    "place_of_issue": "passport_place_of_issue",
    "father_name": "father_full_name",
    "father_family_name": "father_surname",
    "father_last_name": "father_surname",
    "father_first_name": "father_given_names",
    "father_given_name": "father_given_names",
    "father_dob": "father_date_of_birth",
    "father_birth_date": "father_date_of_birth",
    "father_city_of_birth": "father_birth_city",
    "father_birth_state": "father_birth_state",
    "father_birth_country": "father_birth_country",
    "father_address_line1": "father_address",
    "father_death_year": "father_death_year",
    "father_postal_code": "father_postal_code",
    "mother_name": "mother_full_name",
    "mother_family_name": "mother_surname",
    "mother_last_name": "mother_surname",
    "mother_first_name": "mother_given_names",
    "mother_given_name": "mother_given_names",
    "mother_dob": "mother_date_of_birth",
    "mother_birth_date": "mother_date_of_birth",
    "mother_year_of_birth": "mother_date_of_birth",
    "mother_city_of_birth": "mother_birth_city",
    "mother_birth_state": "mother_birth_state",
    "mother_birth_country": "mother_birth_country",
    "mother_address_line1": "mother_address",
    "mother_death_year": "mother_death_year",
    "mother_postal_code": "mother_postal_code",
    "wife_full_name": "spouse_full_name",
    "husband_full_name": "spouse_full_name",
    "spouse_name": "spouse_full_name",
    "wife_surname": "spouse_surname",
    "husband_surname": "spouse_surname",
    "wife_given_names": "spouse_given_names",
    "husband_given_names": "spouse_given_names",
    "spouse_dob": "spouse_date_of_birth",
    "wife_date_of_birth": "spouse_date_of_birth",
    "husband_date_of_birth": "spouse_date_of_birth",
    "date_of_marriage": "spouse_marriage_date",
    "marriage_date": "spouse_marriage_date",
    "marriage_place": "spouse_marriage_city",
    "marriage_city": "spouse_marriage_city",
    "marriage_state": "spouse_marriage_state",
    "marriage_country": "spouse_marriage_country",
    "child_full_name": "child_1_full_name",
    "child_date_of_birth": "child_1_date_of_birth",
    "child_birth_city": "child_1_birth_city",
    "child_birth_state": "child_1_birth_state",
    "child_birth_country": "child_1_birth_country",
    "service_from_date": "military_service_start",
    "service_to_date": "military_service_end",
    "service_from": "military_service_start",
    "service_to": "military_service_end",
    "from_date": "address_from_date",
    "residence_from": "address_from_date",
    "lived_since": "address_from_date",
    # Work / Education (DS-260 D) — ImmiPath / DS-160 profile keys
    "primary_occupation": "work_primary_occupation",
    "occupation_other_specify": "work_occupation_other_specify",
    "present_employer": "work_present_employer",
    "employer_name": "work_present_employer",
    "employer_address": "work_employer_address",
    "employer_address_line1": "work_employer_address",
    "employer_city": "work_employer_city",
    "employer_state": "work_employer_state",
    "employer_postal_code": "work_employer_postal_code",
    "employer_country": "work_employer_country",
    "job_title": "work_job_title",
    "employment_start_date": "work_start_date",
    "employment_start": "work_start_date",
    "prior_jobs_10_years_used": "work_prior_jobs_used",
    "prior_jobs_history": "work_prior_jobs_history",
    "middle_school_name": "edu_middle_school_name",
    "middle_school_address": "edu_middle_school_address",
    "middle_school_period": "edu_middle_school_period",
    "middle_school_dates": "edu_middle_school_period",
    "high_school_name": "edu_high_school_name",
    "highschool_name": "edu_high_school_name",
    "high_school_address": "edu_high_school_address",
    "high_school_period": "edu_high_school_period",
    "high_school_dates": "edu_high_school_period",
    "college_name": "edu_college_name",
    "university_name": "edu_college_name",
    "college_address": "edu_college_address",
    "college_major": "edu_college_major",
    "major": "edu_college_major",
    "field_of_study": "edu_college_major",
    "college_period": "edu_college_period",
    "college_dates": "edu_college_period",
}

# education.* / employment.* (profile OCR) → DS-260 mapping keys
_PROFILE_DOT_TO_DS260: dict[str, str] = {
    "employment.primary_occupation": "work_primary_occupation",
    "employment.occupation_other_specify": "work_occupation_other_specify",
    "employment.present_employer": "work_present_employer",
    "employment.employer_name": "work_present_employer",
    "employment.employer_address_line1": "work_employer_address",
    "employment.employer_city": "work_employer_city",
    "employment.employer_state": "work_employer_state",
    "employment.employer_postal_code": "work_employer_postal_code",
    "employment.employer_country": "work_employer_country",
    "employment.job_title": "work_job_title",
    "employment.start_date": "work_start_date",
    "employment.other_occupation_used": "work_other_occupation_used",
    "employment.other_occupation_detail": "work_other_occupation_detail",
    "employment.prior_jobs_10_years_used": "work_prior_jobs_used",
    "employment.prior_jobs_history": "work_prior_jobs_history",
    "education.middle_school_name": "edu_middle_school_name",
    "education.middle_school_address": "edu_middle_school_address",
    "education.middle_school_period": "edu_middle_school_period",
    "education.high_school_name": "edu_high_school_name",
    "education.high_school_address": "edu_high_school_address",
    "education.high_school_period": "edu_high_school_period",
    "education.college_name": "edu_college_name",
    "education.college_address": "edu_college_address",
    "education.college_major": "edu_college_major",
    "education.college_period": "edu_college_period",
}

# ImmiPath worksheet labels (OCR snake_case) — Middle school (Cấp 2), etc.
_IMMI_PATH_WORK_EDU_REMAP: dict[str, str] = {
    "middle_school_cap_2": "edu_middle_school_name",
    "middle_school_cap_2_name": "edu_middle_school_name",
    "middle_school_cap_2_address": "edu_middle_school_address",
    "middle_school_cap_2_period": "edu_middle_school_period",
    "middle_school_grade_2": "edu_middle_school_name",
    # Cấp 2 = Trung học cơ sở (THCS)
    "trung_hoc_co_so": "edu_middle_school_name",
    "trung_hoc_co_so_name": "edu_middle_school_name",
    "trung_hoc_co_so_address": "edu_middle_school_address",
    "trung_hoc_co_so_period": "edu_middle_school_period",
    "thcs": "edu_middle_school_name",
    "thcs_name": "edu_middle_school_name",
    "thcs_address": "edu_middle_school_address",
    "thcs_period": "edu_middle_school_period",
    "high_school_cap_3": "edu_high_school_name",
    "highschool_cap_3": "edu_high_school_name",
    "high_school_cap_3_name": "edu_high_school_name",
    "high_school_cap_3_address": "edu_high_school_address",
    "high_school_cap_3_period": "edu_high_school_period",
    "highschool_cap_3_name": "edu_high_school_name",
    # Cấp 3 = Trung học phổ thông (THPT)
    "trung_hoc_pho_thong": "edu_high_school_name",
    "trung_hoc_pho_thong_name": "edu_high_school_name",
    "trung_hoc_pho_thong_address": "edu_high_school_address",
    "trung_hoc_pho_thong_period": "edu_high_school_period",
    "thpt": "edu_high_school_name",
    "thpt_name": "edu_high_school_name",
    "thpt_address": "edu_high_school_address",
    "thpt_period": "edu_high_school_period",
    "college_university": "edu_college_name",
    "college_university_name": "edu_college_name",
    "college_university_address": "edu_college_address",
    "college_university_major": "edu_college_major",
    "college_university_period": "edu_college_period",
    "university_college": "edu_college_name",
}

# Keys that indicate a document-number value belongs to a specific DS-260 section.
_PASSPORT_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "passport_number",
        "passport_no",
        "passport_id",
        "passport_document_number",
        "passport_type",
        "country_code",
        "passport_issue_date",
        "date_of_issue",
        "passport_expiration_date",
        "expiration_date",
        "date_of_expiry",
        "passport_expiry_date",
        "passport_place_of_issue",
        "place_of_issue",
        "issuing_authority",
        "passport_issuing_country",
        "issuing_country",
        "country_of_issue",
    }
)

_JUDICIAL_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "judicial_full_name",
        "judicial_date_of_birth",
        "judicial_nationality",
        "judicial_certificate_number",
        "judicial_issue_date",
        "certificate_number",
    }
)

_DIVORCE_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "divorce_husband_name",
        "divorce_wife_name",
        "divorce_date",
        "divorce_marriage_date",
        "divorce_document_number",
        "previous_spouse_full_name",
        "previous_spouse_date_of_birth",
        "previous_divorce_date",
        "previous_marriage_date",
    }
)

_MILITARY_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "military_full_name",
        "military_country",
        "military_branch",
        "military_rank",
        "military_specialty",
        "military_service_start",
        "military_service_end",
        "military_document_number",
        "service_from_date",
        "service_to_date",
        "service_from",
        "service_to",
    }
)

_MARRIAGE_DOC_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "marriage_husband_name",
        "marriage_wife_name",
        "marriage_document_number",
        "spouse_marriage_date",
        "marriage_date",
        "date_of_marriage",
        "registration_number",
    }
)

_DEATH_CONTEXT_KEYS: frozenset[str] = frozenset(
    {
        "death_deceased_name",
        "death_date",
        "death_place",
        "death_relationship",
        "death_document_number",
    }
)

_NON_PASSPORT_DOC_CONTEXT_KEYS: frozenset[str] = (
    _JUDICIAL_CONTEXT_KEYS
    | _DIVORCE_CONTEXT_KEYS
    | _MILITARY_CONTEXT_KEYS
    | _MARRIAGE_DOC_CONTEXT_KEYS
    | _DEATH_CONTEXT_KEYS
)

_DOCUMENT_NUMBER_FIELD_CONTEXT: dict[str, frozenset[str]] = {
    "passport_number": _PASSPORT_CONTEXT_KEYS,
    "judicial_certificate_number": _JUDICIAL_CONTEXT_KEYS,
    "divorce_document_number": _DIVORCE_CONTEXT_KEYS,
    "military_document_number": _MILITARY_CONTEXT_KEYS,
    "marriage_document_number": _MARRIAGE_DOC_CONTEXT_KEYS,
    "death_document_number": _DEATH_CONTEXT_KEYS,
}

_AMBIGUOUS_DOC_NUMBER_ALIASES: frozenset[str] = frozenset(
    {"document_number", "certificate_number", "registration_number"}
)


def _has_field_context(raw: dict[str, str], context_keys: frozenset[str]) -> bool:
    return any((raw.get(k) or "").strip() for k in context_keys)


def _has_non_passport_doc_context(raw: dict[str, str]) -> bool:
    return _has_field_context(raw, _NON_PASSPORT_DOC_CONTEXT_KEYS)


def _should_map_document_number_to_passport(raw: dict[str, str]) -> bool:
    """document_number → passport_number only when passport section is indicated."""
    if (raw.get("passport_number") or "").strip():
        return False
    if not (raw.get("document_number") or "").strip():
        return False
    if not _has_field_context(raw, _PASSPORT_CONTEXT_KEYS):
        return False
    if _has_non_passport_doc_context(raw):
        return False
    return True


def _allow_document_number_for_field(field_key: str, raw: dict[str, str], alias: str) -> bool:
    """Gate ambiguous doc-number aliases so judicial/divorce/military IDs do not fill passport."""
    if alias not in _AMBIGUOUS_DOC_NUMBER_ALIASES:
        return True

    if field_key == "passport_number":
        if alias == "document_number":
            return _should_map_document_number_to_passport(raw)
        return True

    if field_key == "judicial_certificate_number" and alias == "certificate_number":
        return _has_field_context(raw, _JUDICIAL_CONTEXT_KEYS) and not _has_field_context(
            raw, _MARRIAGE_DOC_CONTEXT_KEYS
        )

    if field_key == "marriage_document_number" and alias in {"certificate_number", "registration_number"}:
        return _has_field_context(raw, _MARRIAGE_DOC_CONTEXT_KEYS) and not _has_field_context(
            raw, _JUDICIAL_CONTEXT_KEYS
        )

    context = _DOCUMENT_NUMBER_FIELD_CONTEXT.get(field_key)
    if context is None:
        return True
    if alias != "document_number":
        return True
    return _has_field_context(raw, context)


def resolve_ds260_customer_key_remap(src: str, raw: dict[str, str]) -> str | None:
    """Context-aware remap for a single OCR key (used during extraction coerce)."""
    dst = DS260_CUSTOMER_KEY_REMAP.get(src)
    if not dst:
        return None
    if src == "document_number" and dst == "passport_number":
        return "passport_number" if _should_map_document_number_to_passport(raw) else None
    return dst


def _field_meta_value(meta: object) -> str:
    if isinstance(meta, dict):
        val = meta.get("value")
        return "" if val is None else str(val).strip()
    return "" if meta is None else str(meta).strip()


@lru_cache(maxsize=1)
def build_ds260_customer_extract_keys() -> frozenset[str]:
    """Mọi key DS-260 mapping + alias OCR — cho phép trích xuất full worksheet."""
    keys: set[str] = set(DS260_CUSTOMER_KEY_REMAP)
    keys.update(DS260_CUSTOMER_KEY_REMAP.values())

    mapping_path = Path(__file__).resolve().parents[2] / "data" / "doc_schemas" / "ds260_mapping.json"
    with mapping_path.open(encoding="utf-8") as f:
        data = json.load(f)
    for sec in data.get("sections", []):
        for field in sec.get("fields", []):
            keys.add(field["key"])
            keys.add(field["field"])
            keys.update(field.get("aliases") or ())

    # Keys phổ biến trên form ImmiPath / giấy tờ
    keys.update(
        {
            "other_name_used",
            "other_names",
            "other_nationality_used",
            "other_nationality_history",
            "father_is_living",
            "mother_is_living",
            "father_death_year",
            "mother_death_year",
            "father_address",
            "mother_address",
            "father_city",
            "mother_city",
            "father_state",
            "mother_state",
            "father_country",
            "mother_country",
            "father_postal_code",
            "mother_postal_code",
            "spouse_address",
            "spouse_occupation",
            "spouse_occupation_other",
            "spouse_immigrating",
            "previous_spouses_used",
            "previous_spouse_full_name",
            "previous_spouse_date_of_birth",
            "previous_divorce_date",
            "previous_marriage_date",
            "children_used",
            "children_count",
            "child_2_full_name",
            "child_2_date_of_birth",
            "child_2_birth_city",
            "child_3_full_name",
            "child_3_date_of_birth",
            "primary_occupation",
            "present_employer",
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
            "work_primary_occupation",
            "edu_middle_school_name",
            "edu_high_school_name",
            "edu_college_name",
            "id_card_number",
            "national_id",
            "passport_type",
            "country_code",
            "notes",
        }
    )
    return frozenset(k for k in keys if k)


def _expand_family_prefixed_keys(raw: dict[str, str]) -> dict[str, str]:
    """family.father_surname → father_surname (bảng khai ImmiPath / DS-160 legacy)."""
    out = dict(raw)
    for key, val in list(raw.items()):
        if not val or not key.startswith("family."):
            continue
        short = key[7:].strip()
        if short and short not in out:
            out[short] = val
        # family.father_name → father_full_name
        if short == "father_name" and "father_full_name" not in out:
            out["father_full_name"] = val
        if short == "mother_name" and "mother_full_name" not in out:
            out["mother_full_name"] = val
        if short == "father_address_line1" and "father_address" not in out:
            out["father_address"] = val
        if short == "mother_address_line1" and "mother_address" not in out:
            out["mother_address"] = val
    return out


def _expand_profile_dotted_keys(raw: dict[str, str]) -> dict[str, str]:
    """employment.* / education.* → work_* / edu_* mapping keys."""
    out = dict(raw)
    for src, dst in _PROFILE_DOT_TO_DS260.items():
        if out.get(dst):
            continue
        val = (out.get(src) or "").strip()
        if val:
            out[dst] = val
    return out


def _expand_immipath_work_edu_keys(raw: dict[str, str]) -> dict[str, str]:
    out = dict(raw)
    for src, dst in _IMMI_PATH_WORK_EDU_REMAP.items():
        if out.get(dst):
            continue
        val = (out.get(src) or "").strip()
        if val:
            out[dst] = val
    return out


def normalize_ds260_customer_raw(raw: dict[str, str]) -> dict[str, str]:
    """Gộp alias OCR → key DS-260 mapping (applicant_name, passport_issue_date, …)."""
    out: dict[str, str] = {}
    for k, v in raw.items():
        if v is None:
            continue
        s = str(v).strip()
        if s:
            out[k] = s

    out = _expand_family_prefixed_keys(out)
    out = _expand_profile_dotted_keys(out)
    out = _expand_immipath_work_edu_keys(out)
    for src, dst in DS260_CUSTOMER_KEY_REMAP.items():
        if out.get(dst):
            continue
        val = (out.get(src) or "").strip()
        if val:
            out[dst] = val

    mapping_path = Path(__file__).resolve().parents[2] / "data" / "doc_schemas" / "ds260_mapping.json"
    with mapping_path.open(encoding="utf-8") as f:
        data = json.load(f)
    for sec in data.get("sections", []):
        for field in sec.get("fields", []):
            key = field["key"]
            if out.get(key):
                continue
            for alias in (field["field"], *(field.get("aliases") or ())):
                if not _allow_document_number_for_field(key, out, alias):
                    continue
                val = (out.get(alias) or "").strip()
                if val:
                    out[key] = val
                    break

    _clean_name_header_noise(out)
    return out


# Header tiêu đề form lẫn vào tên do OCR (vd. "DS 260 ...", "KHACH KHAI DS260 ...").
_NAME_HEADER_NOISE = re.compile(
    r"^(?:khach\s*khai\s*)?(?:bang\s*cau\s*hoi\s*)?ds[\s\-]?2?6?0?\b[\s\-]*",
    re.IGNORECASE,
)
_NAME_FIELDS_TO_CLEAN: tuple[str, ...] = (
    "applicant_name",
    "applicant_name_native",
    "full_name",
    "name",
    "family_name",
    "surname",
    "given_name",
    "given_names",
    "birth_cert_full_name",
    "judicial_full_name",
    "military_full_name",
    "father_full_name",
    "mother_full_name",
    "spouse_full_name",
)


def _clean_name_header_noise(out: dict[str, str]) -> None:
    """Bỏ tiền tố tiêu đề form ("DS 260", "KHACH KHAI"…) lẫn vào trường tên do OCR chữ tay."""
    for key in _NAME_FIELDS_TO_CLEAN:
        val = (out.get(key) or "").strip()
        if val:
            out[key] = _NAME_HEADER_NOISE.sub("", val).strip()


def coerce_ds260_customer_extraction(extraction: dict[str, Any]) -> dict[str, Any]:
    """Remap LLM keys trước khi lọc schema."""
    fields = extraction.get("fields")
    if not isinstance(fields, dict):
        return extraction

    remapped: dict[str, dict] = {}
    flat_so_far: dict[str, str] = {}
    for key, meta in fields.items():
        if not isinstance(meta, dict):
            continue
        val = _field_meta_value(meta)
        if val:
            flat_so_far[key] = val
        nk = re.sub(r"[^a-z0-9_]", "_", key.lower()).strip("_")
        if val:
            flat_so_far[nk] = val

    for key, meta in fields.items():
        if not isinstance(meta, dict):
            continue
        nk = re.sub(r"[^a-z0-9_]", "_", key.lower()).strip("_")
        targets = {key, nk}
        if key.startswith("family."):
            short = key[7:].strip()
            if short:
                targets.add(short)
        for src in (key, nk):
            dst = resolve_ds260_customer_key_remap(src, flat_so_far)
            if dst:
                targets.add(dst)
        for target in targets:
            if not target:
                continue
            existing = remapped.get(target)
            if existing and _field_meta_value(existing) and not _field_meta_value(meta):
                continue
            remapped[target] = meta

    flat = {k: _field_meta_value(v) for k, v in remapped.items()}
    normalized = normalize_ds260_customer_raw(flat)
    for key, val in normalized.items():
        if not val:
            continue
        if key not in remapped:
            remapped[key] = {"value": val, "confidence": 0.85, "source_page": "coerced"}
        elif not _field_meta_value(remapped[key]):
            remapped[key]["value"] = val

    extraction["fields"] = remapped
    extraction["document_type"] = "ds260_customer_form"
    return extraction
