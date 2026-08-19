"""Hồ sơ gia đình: worksheet DS-260 phải scope đúng người + tôn trọng câu trả lời worksheet."""

import json
from types import SimpleNamespace


def _ws(native, mother_living, did):
    raw = {"applicant_name_native": native, "applicant_name": f"DS260 {native}", "mother_is_living": mother_living}
    return SimpleNamespace(
        doc_type="ds260_customer_form",
        variant="exception",
        id=did,
        source_document_id=None,
        updated_at=did,
        raw_data=json.dumps(raw),
        form_data="{}",
    )


def test_scope_worksheets_to_person_keeps_only_matching():
    from app.services.ds260_mapping import scope_worksheets_to_person

    long_ws = _ws("HỒ CÔNG BẢO LONG", "Yes", "w1")
    wife_ws = _ws("VĂN THỊ HƯỜNG", "No", "w2")
    records = [long_ws, wife_ws]

    scoped = scope_worksheets_to_person(records, "VĂN THỊ HƯƠNG", is_family_case=True)  # khác dấu vẫn khớp
    ws = [r for r in scoped if r.doc_type == "ds260_customer_form"]
    assert len(ws) == 1
    assert ws[0].id == "w2"


def test_scope_worksheets_no_person_returns_all():
    from app.services.ds260_mapping import scope_worksheets_to_person

    records = [_ws("A B C", "Yes", "w1"), _ws("D E F", "No", "w2")]
    assert len(scope_worksheets_to_person(records, "")) == 2


def test_scope_worksheets_single_member_case_keeps_lone_worksheet():
    """Hồ sơ ĐƠN (is_family_case=False, mặc định): chỉ 1 người trong cả case → 1 worksheet
    nghiễm nhiên là của người đó, dù tên không khớp/không truyền tên."""
    from app.services.ds260_mapping import scope_worksheets_to_person

    records = [_ws("NGUYEN VAN A", "Yes", "w1")]
    scoped = scope_worksheets_to_person(records, "TEN KHONG KHOP")
    assert len([r for r in scoped if r.doc_type == "ds260_customer_form"]) == 1


def test_scope_worksheets_family_case_excludes_lone_foreign_worksheet():
    """Báo lỗi thực tế 2026-08-12: hồ sơ gia đình chỉ có 1 worksheet (của thành viên A) — khi
    resolve DS-260 cho thành viên B, worksheet đó phải bị LOẠI (không phải trả nguyên vẹn), nếu
    không applicant_name của B sẽ bị điền nhầm tên A."""
    from app.services.ds260_mapping import scope_worksheets_to_person

    records = [_ws("NGUYEN DANG DANG", "Yes", "w1")]
    scoped = scope_worksheets_to_person(records, "NGUYEN HOANG YEN", is_family_case=True)
    assert [r for r in scoped if r.doc_type == "ds260_customer_form"] == []


def test_scope_worksheets_family_case_no_name_excludes_all():
    """Hồ sơ gia đình mà không xác định được đang xem ai (person_name rỗng) → không dám đoán,
    loại hết worksheet thay vì trả nguyên vẹn."""
    from app.services.ds260_mapping import scope_worksheets_to_person

    records = [_ws("A B C", "Yes", "w1"), _ws("D E F", "No", "w2")]
    scoped = scope_worksheets_to_person(records, "", is_family_case=True)
    assert [r for r in scoped if r.doc_type == "ds260_customer_form"] == []


def test_con_song_maps_to_yes():
    from app.services.ds260_english_output import format_ds260_field_value

    assert format_ds260_field_value("father_is_living", "CÒN SỐNG") == "Yes"
    assert format_ds260_field_value("mother_is_living", "ĐÃ MẤT") == "No"
