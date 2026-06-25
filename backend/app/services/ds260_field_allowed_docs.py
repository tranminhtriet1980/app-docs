"""Field-level enrich allowlist — cross-fill chỉ từ doc types được khai báo rõ."""

from __future__ import annotations

from functools import lru_cache

_WS = "ds260_customer_form"
_PASS = "passport"
_BC = "birth_certificate"
_JUD = "judicial_certificate"
_MARR = "marriage_certificate"
_DIV = "divorce"
_DEATH = "death_certificate"
_CHILD = "birth_certificate_child"
_APP = "application_form"
_MIL = "military_discharge"
_ADDR = "address_document"

# Field-level overrides. Key không có → default (mapping.document + ds260_customer_form).
_FIELD_ALLOWED_DOCS: dict[str, tuple[str, ...]] = {
    # --- A.1 Personal (passport primary; birth cert corroboration) ---
    "applicant_name": (_PASS, _BC, _WS),
    "applicant_name_native": (_PASS, _BC, _WS),
    "other_name_used": (_WS,),
    "other_names": (_WS,),
    "family_name": (_PASS, _BC, _WS),
    "given_names": (_PASS, _BC, _WS),
    "date_of_birth": (_PASS, _BC, _WS),
    "place_of_birth": (_PASS, _BC, _WS),
    "birth_city": (_PASS, _BC, _WS),
    "birth_state": (_PASS, _BC, _WS),
    "birth_country": (_PASS, _BC, _WS),
    "gender": (_PASS, _BC, _WS),
    "nationality": (_PASS, _BC, _WS),
    "id_card_number": (_PASS, _WS),
    "current_marital_status": (_WS, _DIV, _MARR, _PASS),
    # --- A.2 Passport (strict — không cross-fill từ giấy tờ khác) ---
    "passport_type": (_PASS, _WS),
    "country_code": (_PASS, _WS),
    "passport_number": (_PASS,),
    "passport_issue_date": (_PASS, _WS),
    "passport_expiration_date": (_PASS, _WS),
    "passport_place_of_issue": (_PASS, _WS),
    "passport_issuing_country": (_PASS, _WS),
    "other_nationality_used": (_WS,),
    "other_nationality_history": (_WS,),
    # --- Birth certificate section ---
    "birth_cert_full_name": (_BC, _PASS, _WS),
    "birth_cert_date_of_birth": (_BC, _PASS, _WS),
    "birth_cert_place_of_birth": (_BC, _PASS, _WS),
    "birth_cert_gender": (_BC, _PASS, _WS),
    "birth_cert_father_name": (_BC, _WS),
    "birth_cert_mother_name": (_BC, _WS),
    "birth_cert_registration_number": (_BC, _WS),
    # --- Father / Mother (Passport_new có thể bổ sung) ---
    "father_surname": (_BC, _PASS, _WS),
    "father_given_names": (_BC, _PASS, _WS),
    "father_date_of_birth": (_BC, _WS),
    "father_birth_city": (_BC, _WS),
    "father_birth_state": (_BC, _WS),
    "father_birth_country": (_BC, _WS),
    "father_full_name": (_BC, _PASS, _WS),
    "father_is_living": (_BC, _WS),
    "father_death_year": (_WS, _DEATH),
    "father_address": (_WS,),
    "father_city": (_WS,),
    "father_state": (_WS,),
    "father_postal_code": (_WS,),
    "father_country": (_WS,),
    "mother_surname": (_BC, _PASS, _WS),
    "mother_given_names": (_BC, _PASS, _WS),
    "mother_date_of_birth": (_BC, _WS),
    "mother_birth_city": (_BC, _WS),
    "mother_birth_state": (_BC, _WS),
    "mother_birth_country": (_BC, _WS),
    "mother_full_name": (_BC, _PASS, _WS),
    "mother_is_living": (_BC, _WS),
    "mother_death_year": (_WS, _DEATH),
    "mother_address": (_WS, _BC),
    "mother_city": (_WS,),
    "mother_state": (_WS,),
    "mother_postal_code": (_WS,),
    "mother_country": (_WS,),
    # --- Address (3): street có thể từ Passport_new; city/zip chỉ worksheet ---
    "current_address": (_WS, _PASS, _ADDR),
    "current_city": (_WS,),
    "current_state": (_WS,),
    "postal_code": (_WS,),
    "current_country": (_WS,),
    "address_from_date": (_WS,),
    "other_addresses_used": (_WS,),
    "other_addresses_history": (_WS,),
    # --- Contact (4): chỉ worksheet ---
    "primary_phone": (_WS,),
    "secondary_phone": (_WS,),
    "work_phone": (_WS,),
    "other_phones_used": (_WS,),
    "other_phones_history": (_WS,),
    "email": (_WS,),
    "other_emails_used": (_WS,),
    "other_emails_history": (_WS,),
    # --- Social (5): chỉ worksheet ---
    "social_media_platform": (_WS,),
    "social_media_identifier": (_WS,),
    "other_social_media_used": (_WS,),
    "other_social_history": (_WS,),
    # --- Judicial ---
    "judicial_full_name": (_JUD, _WS),
    "judicial_date_of_birth": (_JUD, _WS),
    "judicial_nationality": (_JUD, _WS),
    "judicial_certificate_number": (_JUD, _WS),
    "judicial_issue_date": (_JUD, _WS),
    # --- Divorce / previous spouse ---
    "divorce_husband_name": (_DIV, _WS),
    "divorce_wife_name": (_DIV, _WS),
    "divorce_marriage_date": (_DIV, _WS),
    "divorce_date": (_DIV, _WS),
    "divorce_document_number": (_DIV, _WS),
    "previous_spouses_used": (_DIV, _WS),
    "previous_spouse_full_name": (_DIV, _WS),
    "previous_spouse_date_of_birth": (_DIV, _WS),
    "previous_divorce_date": (_DIV, _WS),
    "previous_marriage_date": (_DIV, _WS),
    # --- Spouse ---
    "spouse_surname": (_MARR, _WS),
    "spouse_given_names": (_MARR, _WS),
    "spouse_full_name": (_MARR, _WS),
    "spouse_date_of_birth": (_MARR, _WS),
    "spouse_birth_city": (_MARR, _BC, _WS),
    "spouse_birth_state": (_MARR, _BC, _WS),
    "spouse_birth_country": (_MARR, _BC, _WS),
    "spouse_address": (_MARR, _WS),
    "spouse_occupation": (_MARR, _WS),
    "spouse_occupation_other": (_MARR, _WS),
    "spouse_immigrating": (_WS,),
    "spouse_marriage_date": (_MARR, _WS),
    "spouse_marriage_city": (_MARR, _WS),
    "spouse_marriage_state": (_MARR, _WS),
    "spouse_marriage_country": (_MARR, _WS),
    "marriage_husband_name": (_MARR, _WS),
    "marriage_wife_name": (_MARR, _WS),
    "marriage_document_number": (_MARR, _WS),
    # --- Death ---
    "death_deceased_name": (_DEATH, _WS),
    "death_date": (_DEATH, _WS),
    "death_place": (_DEATH, _WS),
    "death_relationship": (_DEATH, _WS),
    "death_document_number": (_DEATH, _WS),
    # --- Work / Education (D) ---
    "work_primary_occupation": (_APP, _WS),
    "work_occupation_other_specify": (_APP, _WS),
    "work_present_employer": (_APP, _WS),
    "work_employer_address": (_APP, _WS),
    "work_employer_city": (_APP, _WS),
    "work_employer_state": (_APP, _WS),
    "work_employer_postal_code": (_APP, _WS),
    "work_employer_country": (_APP, _WS),
    "work_job_title": (_APP, _WS),
    "work_start_date": (_APP, _WS),
    "work_other_occupation_used": (_WS,),
    "work_other_occupation_detail": (_WS, _APP),
    "work_prior_jobs_used": (_WS,),
    "work_prior_jobs_history": (_APP, _WS),
    "edu_middle_school_name": (_APP, _WS),
    "edu_middle_school_address": (_APP, _WS),
    "edu_middle_school_period": (_APP, _WS),
    "edu_high_school_name": (_APP, _WS),
    "edu_high_school_address": (_APP, _WS),
    "edu_high_school_period": (_APP, _WS),
    "edu_college_name": (_APP, _WS),
    "edu_college_address": (_APP, _WS),
    "edu_college_major": (_APP, _WS),
    "edu_college_period": (_APP, _WS),
    # --- Children ---
    "children_used": (_CHILD, _WS),
    "children_count": (_CHILD, _WS),
    "child_1_full_name": (_CHILD, _WS),
    "child_1_date_of_birth": (_CHILD, _WS),
    "child_1_birth_city": (_CHILD, _WS),
    "child_1_birth_state": (_CHILD, _WS),
    "child_1_birth_country": (_CHILD, _WS),
    "child_2_full_name": (_CHILD, _WS),
    "child_2_date_of_birth": (_CHILD, _WS),
    "child_2_birth_city": (_CHILD, _WS),
    "child_2_birth_state": (_CHILD, _WS),
    "child_2_birth_country": (_CHILD, _WS),
    "child_3_full_name": (_CHILD, _WS),
    "child_3_date_of_birth": (_CHILD, _WS),
    "child_3_birth_city": (_CHILD, _WS),
    "child_3_birth_state": (_CHILD, _WS),
    "child_3_birth_country": (_CHILD, _WS),
    "child_4_full_name": (_CHILD, _WS),
    "child_4_date_of_birth": (_CHILD, _WS),
    "child_4_birth_city": (_CHILD, _WS),
    "child_4_birth_state": (_CHILD, _WS),
    "child_4_birth_country": (_CHILD, _WS),
    # --- Child worksheet-only (lives with / immigrating) ---
    **{
        f"child_{i}_{suffix}": (_WS,)
        for i in range(1, 5)
        for suffix in ("lives_with", "current_address", "immigrating", "immigrating_future")
    },
    # --- Military ---
    "military_served": (_WS, _MIL),
    "military_full_name": (_MIL, _WS),
    "military_country": (_MIL, _WS),
    "military_branch": (_MIL, _WS),
    "military_rank": (_MIL, _WS),
    "military_specialty": (_MIL, _WS),
    "military_service_start": (_MIL, _WS),
    "military_service_end": (_MIL, _WS),
    "military_document_number": (_MIL, _WS),
}


@lru_cache(maxsize=1)
def build_field_allowed_docs() -> dict[str, frozenset[str]]:
    """Merge explicit field rules with mapping defaults."""
    import json
    from pathlib import Path

    mapping_path = Path(__file__).resolve().parents[2] / "data" / "doc_schemas" / "ds260_mapping.json"
    with mapping_path.open(encoding="utf-8") as f:
        data = json.load(f)

    out: dict[str, frozenset[str]] = {}
    for sec in data.get("sections", []):
        for field in sec.get("fields", []):
            key = field["key"]
            document = field["document"]
            if document == "spouse_applicant_profile":
                continue
            explicit = _FIELD_ALLOWED_DOCS.get(key)
            if explicit is not None:
                out[key] = frozenset(explicit)
            else:
                out[key] = frozenset({document, _WS})
    return out


def allowed_doc_types_for_field(field_key: str, mapping: object | None = None) -> frozenset[str]:
    allowed = build_field_allowed_docs().get(field_key)
    if allowed is not None:
        return allowed
    if mapping is not None:
        doc = getattr(mapping, "document", None)
        if doc:
            return frozenset({doc, _WS})
    return frozenset({_WS})


def field_allowed_docs_public() -> dict[str, list[str]]:
    return {key: sorted(docs) for key, docs in build_field_allowed_docs().items()}
