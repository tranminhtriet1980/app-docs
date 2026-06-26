"""Nhóm 7/8: city canonical, child worksheet-only merge, lives-with Yes, partial-date upgrade, period split."""

import json
from types import SimpleNamespace


def _rec(doc_type, variant, raw):
    return SimpleNamespace(
        doc_type=doc_type,
        variant=variant,
        id=f"{doc_type}-{variant}",
        source_document_id=None,
        updated_at=None,
        raw_data=json.dumps(raw),
        form_data="{}",
    )


def test_canonical_vn_city_municipality_only():
    from app.services.birth_location import canonical_vn_city

    assert canonical_vn_city("Hcm") == "Ho Chi Minh"
    assert canonical_vn_city("HCMC") == "Ho Chi Minh"
    assert canonical_vn_city("Tp HCM") == "Ho Chi Minh"
    # 'Hue' là thành phố thuộc tỉnh — KHÔNG biến thành tên tỉnh.
    assert canonical_vn_city("Hue") == ""
    assert canonical_vn_city("Bien Hoa") == ""


def test_city_field_english_output_canonicalizes():
    from app.services.ds260_english_output import format_ds260_field_value

    assert format_ds260_field_value("current_city", "HCM") == "Ho Chi Minh"
    assert format_ds260_field_value("mother_city", "Hue") == "Hue"


def test_lives_with_vietnamese_affirmative_is_yes():
    from app.services.ds260_english_output import format_ds260_field_value

    assert format_ds260_field_value("child_1_lives_with", "ĐANG Ở CÙNG BỐ MẸ") == "Yes"
    assert format_ds260_field_value("child_2_lives_with", "Đang ở") == "Yes"


def test_dedupe_children_merges_worksheet_only_fields():
    from app.services.ds260_mapping import _dedupe_children

    bc = {"full_name": "HO BAO HAN", "date_of_birth": "2009-11-11", "lives_with": "", "immigrating": ""}
    ws = {"full_name": "HO BAO HAN", "date_of_birth": "2009-11-11", "lives_with": "YES", "immigrating": "YES"}
    out = _dedupe_children([(bc, "birth_certificate_child", None), (ws, "ds260_customer_form", None)])
    assert len(out) == 1
    data, source, _ = out[0]
    assert source == "birth_certificate_child"  # giấy khai sinh vẫn là nguồn chính
    assert data["lives_with"] == "YES"  # nhưng field worksheet-only được gộp vào
    assert data["immigrating"] == "YES"


def test_upgrade_partial_date_from_worksheet():
    from app.services.ds260_mapping import upgrade_partial_dates_from_worksheet

    ws = _rec("ds260_customer_form", "exception", {"mother_date_of_birth": "1954-12-30"})
    sections = [
        {
            "id": "section_mother",
            "fields": [
                {"key": "mother_date_of_birth", "value": "1954", "source": {}},
            ],
        }
    ]
    upgrade_partial_dates_from_worksheet(sections, [ws])
    assert sections[0]["fields"][0]["value"] == "1954-12-30"


def test_period_from_to_split():
    from app.services.export_ds260 import _fill_period_from_to

    line = "Period (Thời gian học): from (từ)      to (đến):"
    out = _fill_period_from_to(line, "05/09/1991 - 30/05/1994")
    assert "from (từ) 05 September 1991" in out
    assert "to (đến): 30 May 1994" in out
