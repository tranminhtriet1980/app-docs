"""FIELD_ALLOWED_DOCS — enrich must not cross-fill from unrelated doc types."""

import json
from types import SimpleNamespace
from uuid import uuid4

from app.services.ds260_mapping import (
    FIELD_ALLOWED_DOCS,
    enrich_empty_fields_from_all_doc_records,
)


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


def test_passport_number_whitelist_excludes_judicial_and_divorce():
    assert set(FIELD_ALLOWED_DOCS["passport_number"]) == {"passport"}
    assert "judicial_certificate" not in FIELD_ALLOWED_DOCS["passport_number"]
    assert "divorce" not in FIELD_ALLOWED_DOCS["passport_number"]
    assert "ds260_customer_form" not in FIELD_ALLOWED_DOCS["passport_number"]


def test_nationality_allows_passport_and_birth_certificate():
    assert set(FIELD_ALLOWED_DOCS["nationality"]) == {
        "passport",
        "birth_certificate",
        "ds260_customer_form",
    }


def test_address_city_and_phone_are_worksheet_only():
    assert FIELD_ALLOWED_DOCS["current_city"] == ["ds260_customer_form"]
    assert FIELD_ALLOWED_DOCS["postal_code"] == ["ds260_customer_form"]
    assert FIELD_ALLOWED_DOCS["primary_phone"] == ["ds260_customer_form"]
    assert FIELD_ALLOWED_DOCS["email"] == ["ds260_customer_form"]


def test_current_address_allows_passport_not_city_from_passport():
    assert set(FIELD_ALLOWED_DOCS["current_address"]) == {
        "ds260_customer_form",
        "passport",
        "address_document",
    }
    passport_ref = _rec(
        {
            "current_address": "123 LE LOI",
            "address_city": "DA NANG",
            "postal_code": "550000",
        },
        "passport",
        variant="exception",
    )
    sections = [
        {
            "id": "section_address",
            "fields": [
                {"key": "current_address", "value": "", "source": {}},
                {"key": "current_city", "value": "", "source": {}},
                {"key": "postal_code", "value": "", "source": {}},
            ],
        }
    ]
    enrich_empty_fields_from_all_doc_records(sections, [passport_ref], {})
    by_key = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert by_key["current_address"] == "123 LE LOI"
    assert by_key["current_city"] == ""
    assert by_key["postal_code"] == ""


def test_judicial_certificate_number_whitelist_is_strict():
    allowed = set(FIELD_ALLOWED_DOCS["judicial_certificate_number"])
    assert allowed == {"judicial_certificate", "ds260_customer_form"}


def test_judicial_document_number_does_not_fill_passport_number():
    judicial = _rec(
        {"document_number": "JUD-999", "certificate_number": "JUD-999"},
        "judicial_certificate",
    )
    divorce = _rec({"document_number": "DIV-888"}, "divorce")
    sections = [
        {
            "id": "section_a_passport",
            "fields": [{"key": "passport_number", "value": "", "source": {}}],
        }
    ]
    enrich_empty_fields_from_all_doc_records(sections, [judicial, divorce], {})
    assert sections[0]["fields"][0]["value"] == ""


def test_divorce_document_number_does_not_fill_unrelated_fields():
    divorce = _rec({"document_number": "DIV-777"}, "divorce")
    sections = [
        {
            "id": "section_a_passport",
            "fields": [
                {"key": "passport_number", "value": "", "source": {}},
                {"key": "passport_issue_date", "value": "", "source": {}},
            ],
        }
    ]
    enrich_empty_fields_from_all_doc_records(sections, [divorce], {})
    for field in sections[0]["fields"]:
        assert field["value"] == ""


def test_passport_new_still_fills_father_cross_fill():
    passport_ref = _rec(
        {"father_surname": "TRAN", "father_given_names": "VAN B"},
        "passport",
        variant="exception",
    )
    sections = [
        {
            "id": "section_father",
            "fields": [
                {"key": "father_surname", "value": "", "source": {}},
                {"key": "father_given_names", "value": "", "source": {}},
            ],
        }
    ]
    enrich_empty_fields_from_all_doc_records(sections, [passport_ref], {})
    by_key = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert by_key["father_surname"] == "TRAN"
    assert by_key["father_given_names"] == "VAN B"


def test_judicial_loose_match_does_not_fill_applicant_name():
    judicial = _rec(
        {"full_name": "FROM JUDICIAL", "document_number": "J-123"},
        "judicial_certificate",
    )
    sections = [
        {
            "id": "section_a_personal",
            "fields": [{"key": "applicant_name", "value": "", "source": {}}],
        }
    ]
    enrich_empty_fields_from_all_doc_records(sections, [judicial], {})
    assert sections[0]["fields"][0]["value"] == ""
