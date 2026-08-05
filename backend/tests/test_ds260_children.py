"""Children section from birth certificate child + worksheet union."""

import json
from types import SimpleNamespace

from app.services.ds260_mapping import (
    build_child_identity_conflict_rows,
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


def test_dedupe_same_child_diacritics_vs_ascii_worksheet_spelling():
    """Bug thực tế 2026-08-04: giấy khai sinh ghi có dấu, worksheet gõ không dấu — cùng một
    con nhưng chuỗi tên khác nhau ở bước dedupe (trước khi hiển thị bỏ dấu ở cuối pipeline,
    lúc đó nhìn "trùng tên" nhưng đã bị tính thành 2 con riêng)."""
    child1 = _rec({"child_full_name": "Nguyễn Minh Phương", "child_date_of_birth": "2007-01-29"})
    ws = _rec(
        {
            "children_count": "1",
            "child_1_full_name": "NGUYEN MINH PHUONG",
            "child_1_date_of_birth": "2007-01-29",
        },
        "ds260_customer_form",
        variant="exception",
    )
    fields = [
        {"key": "children_count", "value": "", "source": {}},
        {"key": "child_1_full_name", "value": "", "source": {}},
        {"key": "child_2_full_name", "value": "", "source": {}},
    ]
    enrich_children_section_from_birth_certs(fields, [child1], all_records=[child1, ws])
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["children_count"] == "1"
    assert by_key["child_1_full_name"] == "Nguyễn Minh Phương"
    assert by_key["child_2_full_name"] == ""


def test_dedupe_same_child_worksheet_missing_date_of_birth():
    """Bug thực tế 2026-08-05: worksheet chỉ gõ tên con (không ghi ngày sinh), giấy khai sinh
    có ngày sinh đầy đủ — dedupe cũ so khớp cứng (tên, ngày sinh) nên "" != "2019-05-10" khiến
    hệ thống coi là 2 con khác nhau (NGUYEN MINH PHUONG xuất hiện cả child_2 và child_3)."""
    birth_cert = _rec({"child_full_name": "NGUYEN MINH PHUONG", "child_date_of_birth": "2019-05-10"})
    ws = _rec(
        {
            "children_count": "2",
            "child_1_full_name": "SOME OTHER CHILD",
            "child_1_date_of_birth": "2010-01-01",
            "child_2_full_name": "NGUYEN MINH PHUONG",
            "child_2_date_of_birth": "",
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
    enrich_children_section_from_birth_certs(fields, [birth_cert], all_records=[birth_cert, ws])
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["children_count"] == "2", "Phải là 2 con (không tách NGUYEN MINH PHUONG thành con thứ 3)"
    names = {by_key["child_1_full_name"], by_key["child_2_full_name"]}
    assert names == {"SOME OTHER CHILD", "NGUYEN MINH PHUONG"}
    assert by_key["child_3_full_name"] == ""


def test_dedupe_same_child_worksheet_partial_date_birth_cert_full_date():
    """Worksheet ghi ngày sinh không đầy đủ (chỉ năm) trong khi giấy khai sinh có ngày đầy đủ
    — vẫn phải coi là cùng một con (tên khớp, chỉ khác độ chi tiết ngày sinh)."""
    birth_cert = _rec({"child_full_name": "TRAN THI B", "child_date_of_birth": "2016-03-12"})
    ws = _rec(
        {
            "children_count": "1",
            "child_1_full_name": "TRAN THI B",
            "child_1_date_of_birth": "2016",
        },
        "ds260_customer_form",
        variant="exception",
    )
    fields = [
        {"key": "children_count", "value": "", "source": {}},
        {"key": "child_1_full_name", "value": "", "source": {}},
        {"key": "child_2_full_name", "value": "", "source": {}},
    ]
    enrich_children_section_from_birth_certs(fields, [birth_cert], all_records=[birth_cert, ws])
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["children_count"] == "1"
    assert by_key["child_1_full_name"] == "TRAN THI B"
    assert by_key["child_2_full_name"] == ""


def test_different_children_same_first_name_not_merged():
    """Hai con TÊN KHÁC NHAU (không phải cùng người) — không được gộp nhầm dù trùng họ."""
    birth_cert = _rec({"child_full_name": "NGUYEN VAN A", "child_date_of_birth": "2015-01-10"})
    ws = _rec(
        {
            "children_count": "2",
            "child_1_full_name": "NGUYEN VAN A",
            "child_1_date_of_birth": "2015-01-10",
            "child_2_full_name": "NGUYEN VAN B",
            "child_2_date_of_birth": "2018-06-20",
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
    enrich_children_section_from_birth_certs(fields, [birth_cert], all_records=[birth_cert, ws])
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["children_count"] == "2"
    names = {by_key["child_1_full_name"], by_key["child_2_full_name"]}
    assert names == {"NGUYEN VAN A", "NGUYEN VAN B"}


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


def test_worksheet_no_children_rejects_applicant_name_bleed():
    """CHIEM ANH HANG: không có con — worksheet khai No nhưng OCR điền tên chủ hồ sơ vào slot con."""
    ws = _rec(
        {
            "children_used": "No",
            "children_count": "0",
            "child_1_full_name": "CHIEM ANH HANG",
            "child_1_date_of_birth": "1980-05-15",
            "child_1_birth_city": "Ho Chi Minh City",
        },
        "ds260_customer_form",
        variant="exception",
    )
    fields = [
        {"key": "children_used", "value": "", "source": {}},
        {"key": "children_count", "value": "", "source": {}},
        {"key": "child_1_full_name", "value": "CHIEM ANH HANG", "source": {}},
        {"key": "child_1_date_of_birth", "value": "1980-05-15", "source": {}},
        {"key": "child_2_full_name", "value": "", "source": {}},
    ]
    enrich_children_section_from_birth_certs(
        fields, [], all_records=[ws], applicant_name="CHIEM ANH HANG"
    )
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["children_used"] == "No"
    assert by_key["children_count"] == "0"
    assert by_key["child_1_full_name"] == ""
    assert by_key["child_1_date_of_birth"] == ""


def test_worksheet_children_count_without_real_children_does_not_force_yes():
    """children_count > 0 trên worksheet không được ép Yes khi không có tên con hợp lệ."""
    ws = _rec(
        {
            "children_count": "2",
            "child_1_full_name": "CHIEM ANH HANG",
            "child_2_immigrating": "Yes",
        },
        "ds260_customer_form",
        variant="exception",
    )
    fields = [
        {"key": "children_used", "value": "", "source": {}},
        {"key": "children_count", "value": "", "source": {}},
        {"key": "child_1_full_name", "value": "", "source": {}},
        {"key": "child_2_full_name", "value": "", "source": {}},
    ]
    enrich_children_section_from_birth_certs(
        fields, [], all_records=[ws], applicant_name="CHIEM ANH HANG"
    )
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["children_used"] == "No"
    assert by_key["children_count"] == "0"
    assert by_key["child_1_full_name"] == ""


def test_ocr_misread_birth_year_does_not_split_child_into_two_slots():
    """Báo lỗi thực tế 2026-08-05 (NGUYEN MINH PHUONG): giấy khai sinh con bị OCR đọc nhầm số
    quyển ("208/2015") thành ngày sinh (01/01/2015); worksheet ghi đúng 29/01/2007 (khớp hộ
    chiếu). Cùng 1 tên → phải gộp về 1 slot con duy nhất, KHÔNG tách thành child_2/child_3."""
    birth_cert = _rec(
        {"child_full_name": "NGUYEN MINH PHUONG", "child_date_of_birth": "2015-01-01"},
        source_document_id="bc-doc",
    )
    ws = _rec(
        {
            "children_count": "1",
            "child_1_full_name": "NGUYEN MINH PHUONG",
            "child_1_date_of_birth": "2007-01-29",
        },
        "ds260_customer_form",
        variant="exception",
        source_document_id="ws-doc",
    )
    fields = [
        {"key": "children_count", "value": "", "source": {}},
        {"key": "child_1_full_name", "value": "", "source": {}},
        {"key": "child_1_date_of_birth", "value": "", "source": {}},
        {"key": "child_2_full_name", "value": "", "source": {}},
    ]
    enrich_children_section_from_birth_certs(fields, [birth_cert], all_records=[birth_cert, ws])
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["children_count"] == "1", "Phải gộp thành 1 con duy nhất, không tách 2"
    assert by_key["child_1_full_name"] == "NGUYEN MINH PHUONG"
    assert by_key["child_2_full_name"] == ""


def test_child_identity_conflict_created_for_mismatched_date_of_birth():
    """Khi tên khớp nhưng ngày sinh khác nhau giữa giấy khai sinh và worksheet → phải tạo
    Conflict (child_identity) để nhân viên chọn giá trị đúng — KHÔNG được âm thầm bỏ qua."""
    birth_cert = _rec(
        {"child_full_name": "NGUYEN MINH PHUONG", "child_date_of_birth": "2015-01-01"},
        source_document_id="bc-doc",
    )
    ws = _rec(
        {
            "children_count": "1",
            "child_1_full_name": "NGUYEN MINH PHUONG",
            "child_1_date_of_birth": "2007-01-29",
        },
        "ds260_customer_form",
        variant="exception",
        source_document_id="ws-doc",
    )
    rows = build_child_identity_conflict_rows([birth_cert, ws], {})
    dob_rows = [r for r in rows if r["field_key"].endswith(".date_of_birth")]
    assert len(dob_rows) == 1, f"Phải có đúng 1 conflict ngày sinh, thấy: {rows}"
    row = dob_rows[0]
    assert "child_identity" in row["field_key"]
    assert "NGUYEN_MINH_PHUONG" in row["field_key"]
    values = {row["value_a"], row["value_b"]}
    assert values == {"2015-01-01", "2007-01-29"}
    assert row["document_a_id"] == "bc-doc" or row["document_b_id"] == "bc-doc"
    assert row["document_a_id"] == "ws-doc" or row["document_b_id"] == "ws-doc"


def test_child_identity_no_conflict_when_dates_match():
    """Ngày sinh khớp giữa 2 nguồn — không tạo conflict thừa."""
    birth_cert = _rec(
        {"child_full_name": "NGUYEN MINH PHUONG", "child_date_of_birth": "2007-01-29"},
        source_document_id="bc-doc",
    )
    ws = _rec(
        {
            "children_count": "1",
            "child_1_full_name": "NGUYEN MINH PHUONG",
            "child_1_date_of_birth": "2007-01-29",
        },
        "ds260_customer_form",
        variant="exception",
        source_document_id="ws-doc",
    )
    rows = build_child_identity_conflict_rows([birth_cert, ws], {})
    assert rows == []


def test_child_identity_conflict_resolved_not_recreated():
    """Conflict ngày sinh đã được nhân viên chọn (resolutions) — không tạo lại."""
    from app.services.ds260_conflicts import child_identity_conflict_field_key

    birth_cert = _rec(
        {"child_full_name": "NGUYEN MINH PHUONG", "child_date_of_birth": "2015-01-01"},
        source_document_id="bc-doc",
    )
    ws = _rec(
        {
            "children_count": "1",
            "child_1_full_name": "NGUYEN MINH PHUONG",
            "child_1_date_of_birth": "2007-01-29",
        },
        "ds260_customer_form",
        variant="exception",
        source_document_id="ws-doc",
    )
    fk = child_identity_conflict_field_key("NGUYEN MINH PHUONG", "date_of_birth")
    rows = build_child_identity_conflict_rows([birth_cert, ws], {fk: "2007-01-29"})
    assert rows == []


def test_child_identity_different_children_not_compared():
    """2 con khác tên — không so sánh ngày sinh chéo giữa họ (không tạo conflict giả)."""
    child_a = _rec(
        {"child_full_name": "NGUYEN VAN A", "child_date_of_birth": "2010-01-01"},
        source_document_id="a-doc",
    )
    child_b = _rec(
        {"child_full_name": "NGUYEN VAN B", "child_date_of_birth": "2015-06-06"},
        source_document_id="b-doc",
    )
    rows = build_child_identity_conflict_rows([child_a, child_b], {})
    assert rows == []
