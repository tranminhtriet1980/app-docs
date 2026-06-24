"""Children section from birth certificate child + worksheet union."""

import json
from types import SimpleNamespace

from app.services.ds260_mapping import enrich_children_section_from_birth_certs


def _rec(raw: dict, doc_type: str = "birth_certificate_child", *, variant: str = "standard") -> SimpleNamespace:
    return SimpleNamespace(
        doc_type=doc_type,
        variant=variant,
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
        updated_at=None,
        id="test",
        source_document_id=None,
    )


def test_enrich_single_child_only_fills_slot_one():
    child = _rec(
        {
            "child_full_name": "LE CHI KHANG",
            "child_date_of_birth": "2015-01-10",
            "child_place_of_birth": "Ho Chi Minh City, Vietnam",
        }
    )
    fields = [
        {"key": "children_count", "value": "", "source": {}},
        {"key": "child_1_full_name", "value": "", "source": {}},
        {"key": "child_2_full_name", "value": "LE CHI KHANG", "source": {}},
        {"key": "child_3_full_name", "value": "LE CHI KHANG", "source": {}},
    ]
    enrich_children_section_from_birth_certs(fields, [child])
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["children_count"] == "1"
    assert by_key["child_1_full_name"] == "LE CHI KHANG"
    assert by_key["child_2_full_name"] == ""
    assert by_key["child_3_full_name"] == ""


def test_enrich_two_children():
    child1 = _rec(
        {
            "child_full_name": "DANG MAI PHUONG THAO",
            "child_date_of_birth": "2007-04-02",
            "child_place_of_birth": "Da Nang City, Vietnam",
        }
    )
    child2 = _rec(
        {
            "child_full_name": "DANG KHOI NGUYEN",
            "child_date_of_birth": "2009-08-04",
            "child_place_of_birth": "Da Nang, Vietnam",
        }
    )
    fields = [
        {"key": "children_used", "value": "", "source": {}},
        {"key": "children_count", "value": "", "source": {}},
        {"key": "child_1_full_name", "value": "", "source": {}},
        {"key": "child_1_date_of_birth", "value": "", "source": {}},
        {"key": "child_1_birth_city", "value": "", "source": {}},
        {"key": "child_2_full_name", "value": "", "source": {}},
        {"key": "child_2_date_of_birth", "value": "", "source": {}},
    ]
    enrich_children_section_from_birth_certs(fields, [child2, child1])
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["children_used"] == "Yes"
    assert by_key["children_count"] == "2"
    assert by_key["child_1_full_name"] == "DANG MAI PHUONG THAO"
    assert by_key["child_1_date_of_birth"] == "2007-04-02"
    assert by_key["child_2_full_name"] == "DANG KHOI NGUYEN"


def test_union_worksheet_and_birth_certs_dedupe():
    child1 = _rec(
        {"child_full_name": "LE VAN A", "child_date_of_birth": "2015-01-10"},
    )
    child2 = _rec(
        {"child_full_name": "LE VAN B", "child_date_of_birth": "2018-06-20"},
    )
    ws = _rec(
        {
            "children_count": "4",
            "child_1_full_name": "LE VAN A",
            "child_1_date_of_birth": "2015-01-10",
            "child_3_full_name": "LE VAN C",
            "child_3_date_of_birth": "2020-03-01",
            "child_4_full_name": "LE VAN D",
            "child_4_date_of_birth": "2022-11-11",
        },
        "ds260_customer_form",
        variant="exception",
    )
    fields = [
        {"key": "children_count", "value": "", "source": {}},
        {"key": "child_1_full_name", "value": "", "source": {}},
        {"key": "child_2_full_name", "value": "", "source": {}},
        {"key": "child_3_full_name", "value": "", "source": {}},
    ]
    enrich_children_section_from_birth_certs(fields, [child1, child2], all_records=[child1, child2, ws])
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["children_count"] == "4"
    assert by_key["child_1_full_name"] == "LE VAN A"
    assert by_key["child_2_full_name"] == "LE VAN B"
    assert by_key["child_3_full_name"] == "LE VAN C"
