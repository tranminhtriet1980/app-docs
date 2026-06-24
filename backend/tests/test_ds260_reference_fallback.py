"""Luồng 1 thiếu trường → lấy từ file đối chiếu (_new) khách upload."""

import json
from types import SimpleNamespace
from uuid import uuid4

from app.services.ds260_mapping import (
    enrich_empty_fields_from_reference_records,
    flatten_ds260_mappings,
    resolve_luong1_ds260_field,
    _resolve_ds260_field_value,
    _resolve_from_record_luong1_fallback,
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


def test_luong1_fallback_from_reference_when_standard_empty():
    standard = _rec({"full_name": "NGUYEN VAN A"}, "passport", variant="standard")
    reference = _rec(
        {"full_name": "NGUYEN VAN A", "passport_number": "P1234567"},
        "passport",
        variant="exception",
    )
    mapping = flatten_ds260_mappings()["passport_number"]
    val, sf, rec, extra = resolve_luong1_ds260_field(
        [standard, reference], "passport", mapping, {}
    )
    assert val == "P1234567"
    assert rec is reference
    assert extra.get("derived") == "reference_fallback"


def test_luong1_prefers_standard_when_both_have_value():
    standard = _rec({"passport_number": "STD111"}, "passport", variant="standard")
    reference = _rec({"passport_number": "REF222"}, "passport", variant="exception")
    mapping = flatten_ds260_mappings()["passport_number"]
    val, _, rec, extra = resolve_luong1_ds260_field(
        [standard, reference], "passport", mapping, {}
    )
    assert val == "STD111"
    assert rec is standard
    assert "reference_fallback" not in extra


def test_resolve_from_record_luong1_fallback():
    standard = _rec({"birth_city": ""}, "passport")
    reference = _rec({"birth_city": "DA NANG"}, "passport", variant="exception")
    assert (
        _resolve_from_record_luong1_fallback(standard, reference, "birth_city", ())
        == "DA NANG"
    )


def test_ds260_key_applicant_name_on_reference():
    """Form khách upload dùng applicant_name thay vì full_name."""
    reference = _rec(
        {"applicant_name": "NGUYEN VAN A", "passport_number": "P999"},
        "passport",
        variant="exception",
    )
    mapping = flatten_ds260_mappings()["applicant_name"]
    val, sf = _resolve_ds260_field_value(mapping, reference)
    assert val == "NGUYEN VAN A"
    assert sf == "applicant_name"


def test_cross_fill_father_from_passport_new():
    """Thông tin cha trong Passport_new → điền section Father khi GKS trống."""
    passport_ref = _rec(
        {
            "father_surname": "TRAN",
            "father_given_names": "VAN B",
            "father_birth_city": "HUE",
        },
        "passport",
        variant="exception",
    )
    sections = [
        {
            "id": "section_father",
            "title": "Father",
            "fields": [
                {"key": "father_surname", "value": "", "source": {}},
                {"key": "father_given_names", "value": "", "source": {}},
                {"key": "father_birth_city", "value": "", "source": {}},
            ],
        }
    ]
    enrich_empty_fields_from_reference_records(sections, [passport_ref], {})
    by_key = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert by_key["father_surname"] == "TRAN"
    assert by_key["father_given_names"] == "VAN B"
    assert by_key["father_birth_city"] == ""
