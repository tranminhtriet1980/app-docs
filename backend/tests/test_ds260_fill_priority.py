"""_record_fill_priority — official docs outrank DS-260 worksheet."""

import json
from types import SimpleNamespace
from uuid import uuid4

from app.services.ds260_mapping import (
    _record_fill_priority,
    enrich_empty_fields_from_all_doc_records,
    flatten_ds260_mappings,
)


def _rec(doc_type: str, *, variant: str = "standard") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        doc_type=doc_type,
        variant=variant,
        source_document_id=uuid4(),
        form_data="{}",
        raw_data="{}",
        updated_at=None,
    )


def _tier(rec: SimpleNamespace, mapping_key: str) -> int:
    mapping = flatten_ds260_mappings()[mapping_key]
    return _record_fill_priority(rec, mapping)[0]


def test_same_doc_standard_beats_exception():
    std = _rec("passport", variant="standard")
    exc = _rec("passport", variant="exception")
    assert _tier(std, "applicant_name") < _tier(exc, "applicant_name")


def test_same_doc_exception_beats_other_luong1_exception():
    passport_exc = _rec("passport", variant="exception")
    judicial_exc = _rec("judicial_certificate", variant="exception")
    assert _tier(passport_exc, "applicant_name") < _tier(judicial_exc, "applicant_name")


def test_other_luong1_exception_beats_ds260():
    judicial_exc = _rec("judicial_certificate", variant="exception")
    ds260 = _rec("ds260_customer_form", variant="exception")
    assert _tier(judicial_exc, "applicant_name") < _tier(ds260, "applicant_name")


def test_other_luong1_standard_beats_ds260():
    bc_std = _rec("birth_certificate", variant="standard")
    ds260 = _rec("ds260_customer_form", variant="exception")
    assert _tier(bc_std, "applicant_name") < _tier(ds260, "applicant_name")


def test_ds260_beats_supplemental_customer_form():
    ds260 = _rec("ds260_customer_form", variant="exception")
    addr = _rec("address_document", variant="exception")
    assert _tier(ds260, "current_address") < _tier(addr, "current_address")


def test_supplemental_beats_fallback():
    addr = _rec("address_document", variant="exception")
    divorce = _rec("divorce", variant="standard")
    assert _tier(addr, "current_address") < _tier(divorce, "current_address")


def test_full_priority_ordering():
    mapping = flatten_ds260_mappings()["applicant_name"]
    records = [
        _rec("ds260_customer_form", variant="exception"),
        _rec("passport", variant="standard"),
        _rec("passport", variant="exception"),
        _rec("birth_certificate", variant="exception"),
        _rec("marriage_certificate", variant="standard"),
        _rec("address_document", variant="exception"),
        _rec("divorce", variant="standard"),
    ]
    ordered = sorted(records, key=lambda r: _record_fill_priority(r, mapping))
    assert [r.doc_type for r in ordered] == [
        "passport",
        "passport",
        "birth_certificate",
        "marriage_certificate",
        "ds260_customer_form",
        "address_document",
        "divorce",
    ]
    assert ordered[0].variant == "standard"
    assert ordered[1].variant == "exception"


def test_enrich_prefers_passport_new_over_ds260_worksheet():
    passport_ref = SimpleNamespace(
        id=uuid4(),
        doc_type="passport",
        variant="exception",
        source_document_id=uuid4(),
        form_data=json.dumps({"full_name": "FROM PASSPORT NEW"}),
        raw_data=json.dumps({"full_name": "FROM PASSPORT NEW"}),
        updated_at=None,
    )
    ds260 = SimpleNamespace(
        id=uuid4(),
        doc_type="ds260_customer_form",
        variant="exception",
        source_document_id=uuid4(),
        form_data=json.dumps({"applicant_name": "FROM DS260 WORKSHEET"}),
        raw_data=json.dumps({"applicant_name": "FROM DS260 WORKSHEET"}),
        updated_at=None,
    )
    sections = [
        {
            "id": "section_a_personal",
            "fields": [{"key": "applicant_name", "value": "", "source": {}}],
        }
    ]
    enrich_empty_fields_from_all_doc_records(sections, [ds260, passport_ref], {})
    field = sections[0]["fields"][0]
    assert field["value"] == "FROM PASSPORT NEW"
    assert field["source"]["document_type"] == "passport"
    assert field["source"]["variant"] == "exception"


def test_enrich_uses_ds260_when_no_official_source():
    ds260 = SimpleNamespace(
        id=uuid4(),
        doc_type="ds260_customer_form",
        variant="exception",
        source_document_id=uuid4(),
        form_data=json.dumps({"applicant_name": "ONLY ON WORKSHEET"}),
        raw_data=json.dumps({"applicant_name": "ONLY ON WORKSHEET"}),
        updated_at=None,
    )
    sections = [
        {
            "id": "section_a_personal",
            "fields": [{"key": "applicant_name", "value": "", "source": {}}],
        }
    ]
    enrich_empty_fields_from_all_doc_records(sections, [ds260], {})
    field = sections[0]["fields"][0]
    assert field["value"] == "ONLY ON WORKSHEET"
    assert field["source"]["document_type"] == "ds260_customer_form"
    assert field["source"]["derived"] == "ds260_worksheet_fill"
