"""Full DS-260 worksheet key normalization and cross-fill."""

import json
from types import SimpleNamespace
from uuid import uuid4

from app.services.ds260_customer_keys import (
    build_ds260_customer_extract_keys,
    coerce_ds260_customer_extraction,
    normalize_ds260_customer_raw,
)
from app.services.ds260_mapping import (
    enrich_empty_fields_from_all_doc_records,
    flatten_ds260_mappings,
)


def test_extract_keys_include_personal_and_passport():
    keys = build_ds260_customer_extract_keys()
    assert "applicant_name" in keys
    assert "passport_number" in keys
    assert "father_surname" in keys
    assert "primary_phone_number" in keys
    assert len(keys) > 80


def test_normalize_remaps_passport_and_personal():
    raw = normalize_ds260_customer_raw(
        {
            "full_name": "NGUYEN VAN A",
            "sex": "MALE",
            "passport_id": "B1234567",
            "date_of_issue": "2020-01-01",
            "expiration_date": "2030-01-01",
        }
    )
    assert raw["applicant_name"] == "NGUYEN VAN A"
    assert raw["gender"] == "MALE"
    assert raw["passport_number"] == "B1234567"
    assert raw["passport_issue_date"] == "2020-01-01"
    assert raw["passport_expiration_date"] == "2030-01-01"


def test_bare_document_number_does_not_become_passport_number():
    raw = normalize_ds260_customer_raw({"document_number": "JUD-999"})
    assert "passport_number" not in raw


def test_document_number_maps_to_passport_with_passport_context():
    raw = normalize_ds260_customer_raw(
        {
            "document_number": "B1234567",
            "passport_type": "P",
            "date_of_issue": "2020-01-01",
        }
    )
    assert raw["passport_number"] == "B1234567"


def test_judicial_document_number_does_not_map_to_passport():
    raw = normalize_ds260_customer_raw(
        {
            "document_number": "10609/LLTP-HSNV",
            "judicial_full_name": "NGUYEN VAN A",
            "certificate_number": "10609/LLTP-HSNV",
        }
    )
    assert "passport_number" not in raw
    assert raw["judicial_certificate_number"] == "10609/LLTP-HSNV"


def test_divorce_document_number_does_not_map_to_passport():
    raw = normalize_ds260_customer_raw(
        {
            "document_number": "41/2025/QDST-HNGD",
            "divorce_husband_name": "TRAN VAN A",
            "divorce_wife_name": "LE THI B",
        }
    )
    assert "passport_number" not in raw
    assert raw["divorce_document_number"] == "41/2025/QDST-HNGD"


def test_military_document_number_does_not_map_to_passport():
    raw = normalize_ds260_customer_raw(
        {
            "document_number": "209/QD-TD",
            "military_branch": "Army",
            "military_rank": "Private",
        }
    )
    assert "passport_number" not in raw
    assert raw["military_document_number"] == "209/QD-TD"


def test_passport_document_number_always_maps():
    raw = normalize_ds260_customer_raw({"passport_document_number": "C0509328"})
    assert raw["passport_number"] == "C0509328"


def test_coerce_does_not_promote_judicial_document_number_to_passport():
    out = coerce_ds260_customer_extraction(
        {
            "fields": {
                "document_number": {"value": "10609/LLTP-HSNV", "confidence": 0.9},
                "judicial_full_name": {"value": "NGUYEN VAN A", "confidence": 0.9},
            }
        }
    )
    fields = {k: v["value"] for k, v in out["fields"].items() if isinstance(v, dict) and v.get("value")}
    assert "passport_number" not in fields
    assert fields.get("judicial_certificate_number") == "10609/LLTP-HSNV"


def test_coerce_extraction_adds_mapping_keys():
    out = coerce_ds260_customer_extraction(
        {
            "fields": {
                "full_name": {"value": "TRAN THI B", "confidence": 0.9},
                "father_surname": {"value": "TRAN", "confidence": 0.9},
            }
        }
    )
    fields = {k: v["value"] for k, v in out["fields"].items() if isinstance(v, dict) and v.get("value")}
    assert fields.get("applicant_name") == "TRAN THI B"
    assert fields.get("father_surname") == "TRAN"


def _ds260_rec(raw: dict) -> SimpleNamespace:
    normalized = normalize_ds260_customer_raw(raw)
    return SimpleNamespace(
        id=uuid4(),
        doc_type="ds260_customer_form",
        variant="exception",
        source_document_id=uuid4(),
        form_data=json.dumps(normalized),
        raw_data=json.dumps(normalized),
        updated_at=None,
    )


def test_worksheet_fills_passport_and_father_gaps():
    rec = _ds260_rec(
        {
            "applicant_name": "NGUYEN VAN A",
            "date_of_birth": "1990-01-15",
            "passport_number": "B9999999",
            "father_surname": "NGUYEN",
            "father_given_names": "VAN C",
            "current_address": "123 LE LOI",
            "primary_phone_number": "+84901234567",
        }
    )
    sections = [
        {
            "id": "section_a_personal",
            "fields": [
                {"key": "applicant_name", "value": "", "source": {}},
                {"key": "date_of_birth", "value": "", "source": {}},
            ],
        },
        {
            "id": "section_a_passport",
            "fields": [{"key": "passport_number", "value": "", "source": {}}],
        },
        {
            "id": "section_father",
            "fields": [
                {"key": "father_surname", "value": "", "source": {}},
                {"key": "father_given_names", "value": "", "source": {}},
            ],
        },
        {
            "id": "section_address",
            "fields": [{"key": "current_address", "value": "", "source": {}}],
        },
        {
            "id": "section_contact",
            "fields": [{"key": "primary_phone", "value": "", "source": {}}],
        },
    ]
    enrich_empty_fields_from_all_doc_records(sections, [rec], {})
    personal = {f["key"]: f["value"] for f in sections[0]["fields"]}
    passport = {f["key"]: f["value"] for f in sections[1]["fields"]}
    father = {f["key"]: f["value"] for f in sections[2]["fields"]}
    assert personal["applicant_name"] == "NGUYEN VAN A"
    assert personal["date_of_birth"] == "1990-01-15"
    assert passport["passport_number"] == ""
    assert father["father_surname"] == "NGUYEN"
    assert sections[3]["fields"][0]["value"] == "123 LE LOI"
    mappings = flatten_ds260_mappings()
    assert sections[4]["fields"][0]["source"].get("derived") == "ds260_worksheet_fill"
