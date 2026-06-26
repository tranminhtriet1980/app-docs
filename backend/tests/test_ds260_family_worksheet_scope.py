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

    scoped = scope_worksheets_to_person(records, "VĂN THỊ HƯƠNG")  # khác dấu vẫn khớp
    ws = [r for r in scoped if r.doc_type == "ds260_customer_form"]
    assert len(ws) == 1
    assert ws[0].id == "w2"


def test_scope_worksheets_no_person_returns_all():
    from app.services.ds260_mapping import scope_worksheets_to_person

    records = [_ws("A B C", "Yes", "w1"), _ws("D E F", "No", "w2")]
    assert len(scope_worksheets_to_person(records, "")) == 2


def test_parent_is_living_respects_worksheet_no():
    from app.services.ds260_mapping import enrich_parent_is_living

    bc = SimpleNamespace(
        doc_type="birth_certificate",
        variant="standard",
        id="bc",
        raw_data=json.dumps({"mother_name": "HOANG THI CAM"}),
        form_data="{}",
    )
    fields = [{"key": "mother_is_living", "value": "No", "source": {}}]  # worksheet đã khai No
    enrich_parent_is_living(fields, bc, "mother")
    assert fields[0]["value"] == "No"  # KHÔNG bị ghi đè thành Yes


def test_con_song_maps_to_yes():
    from app.services.ds260_english_output import format_ds260_field_value

    assert format_ds260_field_value("father_is_living", "CÒN SỐNG") == "Yes"
    assert format_ds260_field_value("mother_is_living", "ĐÃ MẤT") == "No"
