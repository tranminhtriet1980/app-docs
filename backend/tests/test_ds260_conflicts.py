"""DS-260 conflicts — document_vs_exception and document_vs_worksheet."""

import json
from types import SimpleNamespace
from uuid import uuid4

from app.services.ds260_conflicts import (
    LUONG1_DOC_TYPES,
    WORKSHEET_COMPARE_KEYS,
    build_worksheet_conflict_rows,
    conflict_type_from_field_key,
    ds260_conflict_field_key,
    norm_conflict_value,
    parse_ds260_conflict_key,
    worksheet_conflict_field_key,
    _norm_value,
)


def test_luong1_doc_types():
    assert "passport" in LUONG1_DOC_TYPES
    assert "birth_certificate" in LUONG1_DOC_TYPES
    assert "judicial_certificate" in LUONG1_DOC_TYPES
    assert "marriage_certificate" in LUONG1_DOC_TYPES
    assert "divorce" not in LUONG1_DOC_TYPES


def test_conflict_field_key():
    assert ds260_conflict_field_key("passport", "full_name") == "ds260.passport.full_name"
    assert parse_ds260_conflict_key("ds260.passport.full_name") == ("passport", "full_name")


def test_worksheet_conflict_field_key():
    assert worksheet_conflict_field_key("applicant_name") == "ds260.document_vs_worksheet.applicant_name"
    assert parse_ds260_conflict_key("ds260.document_vs_worksheet.applicant_name") == (
        "document_vs_worksheet",
        "applicant_name",
    )
    assert conflict_type_from_field_key("ds260.document_vs_worksheet.gender") == "document_vs_worksheet"
    assert conflict_type_from_field_key("ds260.passport.full_name") == "document_vs_exception"


def test_worksheet_compare_keys_cover_user_fields():
    assert len(WORKSHEET_COMPARE_KEYS) == 12
    assert "applicant_name" in WORKSHEET_COMPARE_KEYS
    assert "place_of_birth" in WORKSHEET_COMPARE_KEYS
    assert "passport_expiration_date" in WORKSHEET_COMPARE_KEYS
    assert "current_marital_status" in WORKSHEET_COMPARE_KEYS
    assert "current_address" in WORKSHEET_COMPARE_KEYS
    assert "primary_phone" in WORKSHEET_COMPARE_KEYS
    assert "email" in WORKSHEET_COMPARE_KEYS


def test_norm_value():
    assert _norm_value("  Da Nang  ") == "DA NANG"


def test_norm_conflict_value_dates_and_gender():
    assert norm_conflict_value("gender", "male") == "MALE"
    assert norm_conflict_value("gender", "F") == "FEMALE"
    assert norm_conflict_value("date_of_birth", "1990-01-15") == "1990-01-15"
    assert norm_conflict_value("date_of_birth", "15/01/1990") == "1990-01-15"


def _rec(raw: dict, doc_type: str, *, variant: str = "standard") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        doc_type=doc_type,
        variant=variant,
        source_document_id=uuid4(),
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
        updated_at=None,
    )


def test_build_worksheet_conflict_when_values_differ():
    passport_std = _rec({"full_name": "NGUYEN VAN A", "date_of_birth": "1990-01-15"}, "passport")
    ds260 = _rec(
        {
            "applicant_name": "NGUYEN VAN B",
            "date_of_birth": "1990-01-15",
        },
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([passport_std, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("applicant_name") in keys
    assert worksheet_conflict_field_key("date_of_birth") not in keys


def test_build_worksheet_conflict_skips_when_normalized_equal():
    passport_std = _rec({"full_name": "NGUYEN VAN A", "gender": "MALE"}, "passport")
    ds260 = _rec({"applicant_name": "nguyen van a", "gender": "M"}, "ds260_customer_form", variant="exception")
    rows = build_worksheet_conflict_rows([passport_std, ds260], {})
    assert rows == []


def test_build_worksheet_conflict_respects_resolved():
    passport_std = _rec({"full_name": "A"}, "passport")
    ds260 = _rec({"applicant_name": "B"}, "ds260_customer_form", variant="exception")
    fk = worksheet_conflict_field_key("applicant_name")
    rows = build_worksheet_conflict_rows([passport_std, ds260], {fk: "A"})
    assert rows == []


def test_build_worksheet_conflict_address_passport_new_vs_worksheet():
    passport_ref = _rec(
        {"current_address": "123 LE LOI"},
        "passport",
        variant="exception",
    )
    ds260 = _rec(
        {"current_address": "456 TRAN PHU"},
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([passport_ref, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("current_address") in keys
    row = next(r for r in rows if r["field_key"] == worksheet_conflict_field_key("current_address"))
    assert row["value_a"] == "123 LE LOI"
    assert row["value_b"] == "456 TRAN PHU"


def test_build_worksheet_conflict_phone_and_email():
    passport_ref = _rec(
        {"primary_phone_number": "+84901112233", "email_address": "a@example.com"},
        "passport",
        variant="exception",
    )
    ds260 = _rec(
        {"primary_phone_number": "+84909998888", "email_address": "b@example.com"},
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([passport_ref, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("primary_phone") in keys
    assert worksheet_conflict_field_key("email") in keys


def test_apply_ds260_resolved_conflicts_worksheet_and_luong1():
    from app.services.ds260_conflicts import apply_ds260_resolved_conflicts

    sections = [
        {
            "fields": [
                {"key": "applicant_name", "value": "WRONG", "source": {}},
                {"key": "gender", "value": "Male", "source": {}},
            ]
        }
    ]
    resolutions = {
        worksheet_conflict_field_key("applicant_name"): "DANG VAN HUNG",
        ds260_conflict_field_key("passport", "full_name"): "DANG VAN HUNG",
        ds260_conflict_field_key("passport", "gender"): "Female",
    }
    apply_ds260_resolved_conflicts(sections, resolutions)
    by_key = {f["key"]: f for f in sections[0]["fields"]}
    assert by_key["applicant_name"]["value"] == "DANG VAN HUNG"
    assert by_key["applicant_name"]["source"]["derived"] == "worksheet_conflict_resolution"
    assert by_key["gender"]["value"] == "Female"
    assert by_key["gender"]["source"]["derived"] == "conflict_resolution"
