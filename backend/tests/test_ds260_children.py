"""Children section from birth certificate child + worksheet union."""

import json
from types import SimpleNamespace

from app.services.ds260_mapping import (
    enrich_children_section_from_birth_certs,
    group_child_birth_luong1_pairs,
)


def _rec(
    raw: dict,
    doc_type: str = "birth_certificate_child",
    *,
    variant: str = "standard",
    rec_id: str = "test",
    source_document_id: str | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        doc_type=doc_type,
        variant=variant,
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
        updated_at=None,
        id=rec_id,
        source_document_id=source_document_id,
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


def test_standard_and_new_same_child_count_as_one():
    """2 con × (standard + _new) = 4 file nhưng chỉ 2 slot con trên Review."""
    child_a_std = _rec(
        {"child_full_name": "NGUYEN VAN A", "child_date_of_birth": "2015-01-10"},
        rec_id="a-std",
        source_document_id="doc-a-std",
    )
    child_a_new = _rec(
        {"child_full_name": "NGUYEN VAN A", "child_date_of_birth": "2015-01-10"},
        variant="exception",
        rec_id="a-new",
        source_document_id="doc-a-new",
    )
    child_b_std = _rec(
        {"child_full_name": "NGUYEN VAN B", "child_date_of_birth": "2018-06-20"},
        rec_id="b-std",
        source_document_id="doc-b-std",
    )
    child_b_new = _rec(
        {"child_full_name": "NGUYEN VAN B", "child_date_of_birth": "2018-06-20"},
        variant="exception",
        rec_id="b-new",
        source_document_id="doc-b-new",
    )
    filename_map = {
        "doc-a-std": "03_1 BIRTH CERTIFICATE CHILD A.pdf",
        "doc-a-new": "03_1 BIRTH CERTIFICATE CHILD A_new.pdf",
        "doc-b-std": "03_2 BIRTH CERTIFICATE CHILD B.pdf",
        "doc-b-new": "03_2 BIRTH CERTIFICATE CHILD B_new.pdf",
    }
    fields = [
        {"key": "children_count", "value": "", "source": {}},
        {"key": "child_1_full_name", "value": "", "source": {}},
        {"key": "child_2_full_name", "value": "", "source": {}},
        {"key": "child_3_full_name", "value": "", "source": {}},
        {"key": "child_4_full_name", "value": "", "source": {}},
    ]
    records = [child_a_std, child_a_new, child_b_std, child_b_new]
    enrich_children_section_from_birth_certs(
        fields, records, all_records=records, filename_map=filename_map
    )
    by_key = {f["key"]: f["value"] for f in fields}
    hidden = {f["key"]: f.get("review_hidden") for f in fields if f["key"].startswith("child_")}
    assert by_key["children_count"] == "2"
    assert by_key["child_1_full_name"] == "NGUYEN VAN A"
    assert by_key["child_2_full_name"] == "NGUYEN VAN B"
    assert by_key["child_3_full_name"] == ""
    assert by_key["child_4_full_name"] == ""
    assert hidden.get("child_3_full_name") is True
    assert hidden.get("child_4_full_name") is True
    assert len(group_child_birth_luong1_pairs(records, filename_map)) == 2


def test_worksheet_noise_slot_without_name_is_ignored():
    ws = _rec(
        {
            "children_count": "3",
            "child_1_full_name": "TRAN VAN A",
            "child_1_date_of_birth": "2015-01-10",
            "child_3_lives_with": "No",
            "child_3_immigrating": "Yes",
            "child_4_birth_country": "Vietnam",
        },
        "ds260_customer_form",
        variant="exception",
    )
    fields = [
        {"key": "children_count", "value": "", "source": {}},
        {"key": "child_1_full_name", "value": "", "source": {}},
        {"key": "child_2_full_name", "value": "", "source": {}},
        {"key": "child_3_full_name", "value": "", "source": {}},
        {"key": "child_4_full_name", "value": "", "source": {}},
    ]
    enrich_children_section_from_birth_certs(fields, [], all_records=[ws])
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["children_count"] == "1"
    assert by_key["child_1_full_name"] == "TRAN VAN A"
    assert by_key["child_3_full_name"] == ""
    assert by_key["child_4_full_name"] == ""


def test_no_children_sets_no_and_hides_slots():
    fields = [
        {"key": "children_used", "value": "", "source": {}},
        {"key": "children_count", "value": "", "source": {}},
        {"key": "child_1_full_name", "value": "GHOST", "source": {}},
        {"key": "child_2_full_name", "value": "", "source": {}},
    ]
    enrich_children_section_from_birth_certs(fields, [], all_records=[])
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["children_used"] == "No"
    assert by_key["children_count"] == "0"
    assert by_key["child_1_full_name"] == ""


def test_enrich_children_from_case_members_when_grouped():
    """Thành viên con trong gia đình → điền slot con dù gộp file OCR."""
    child1 = _rec(
        {"child_full_name": "HUYNH NHAT LONG", "child_date_of_birth": "2012-04-12"},
        rec_id="long",
        source_document_id="doc-long",
    )
    child2 = _rec(
        {"child_full_name": "HUYNH NHA UYEN", "child_date_of_birth": "2019-06-22"},
        rec_id="uyen",
        source_document_id="doc-uyen",
    )
    members = [
        SimpleNamespace(role="child", display_name="HUYNH NHAT LONG"),
        SimpleNamespace(role="child", display_name="HUYNH NHA UYEN"),
    ]
    fields = [
        {"key": "children_used", "value": "", "source": {}},
        {"key": "children_count", "value": "", "source": {}},
        {"key": "child_1_full_name", "value": "", "source": {}},
        {"key": "child_2_full_name", "value": "", "source": {}},
        {"key": "child_3_full_name", "value": "", "source": {}},
    ]
    enrich_children_section_from_birth_certs(
        fields, [], all_records=[child1, child2], case_members=members
    )
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["children_used"] == "Yes"
    assert by_key["children_count"] == "2"
    assert by_key["child_1_full_name"] == "HUYNH NHAT LONG"
    assert by_key["child_2_full_name"] == "HUYNH NHA UYEN"
    assert by_key["child_3_full_name"] == ""
