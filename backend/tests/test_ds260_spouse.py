"""Spouse section from marriage certificate."""

import json
from types import SimpleNamespace

from app.services.ds260_mapping import (
    _pick_spouse_side_from_marriage,
    enrich_spouse_section_from_marriage,
)


def _rec(raw: dict, doc_type: str = "marriage_certificate", variant: str = "standard") -> SimpleNamespace:
    return SimpleNamespace(
        doc_type=doc_type,
        variant=variant,
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
        id="1",
        source_document_id=None,
        updated_at=None,
    )


def test_pick_wife_when_applicant_is_husband():
    marriage = _rec(
        {
            "husband_full_name": "DANG VAN HUNG",
            "wife_full_name": "MAI NGOC HOA",
            "marriage_date": "2006-12-21",
            "marriage_place": "Da Nang City, Vietnam",
        }
    )
    passport = _rec({"full_name": "DANG VAN HUNG", "gender": "MALE"}, "passport")
    assert _pick_spouse_side_from_marriage(marriage, passport) == "wife"


def test_pick_side_uses_gender_when_both_sides_share_surname():
    """Vợ chồng trùng họ (hoặc tên chủ hồ sơ nhiễu OCR chỉ còn lại họ) — _names_match chỉ so
    HỌ nên khớp CẢ HAI bên. Trước đây luôn chọn nhầm 'wife' (thứ tự if ưu tiên husband match) bất
    kể applicant thực ra là vợ hay chồng — giới tính hộ chiếu phải phân định đúng bên."""
    marriage = _rec(
        {
            "husband_full_name": "TRAN VAN HUNG",
            "wife_full_name": "TRAN THI HOA",
            "marriage_date": "2006-12-21",
        }
    )
    male_applicant = _rec({"full_name": "TRAN VAN HUNG", "gender": "MALE"}, "passport")
    assert _pick_spouse_side_from_marriage(marriage, male_applicant) == "wife"

    female_applicant = _rec({"full_name": "TRAN THI HOA", "gender": "FEMALE"}, "passport")
    assert _pick_spouse_side_from_marriage(marriage, female_applicant) == "husband"


def test_pick_side_returns_empty_when_ambiguous_and_gender_unknown():
    marriage = _rec(
        {"husband_full_name": "TRAN VAN HUNG", "wife_full_name": "TRAN THI HOA"}
    )
    applicant = _rec({"full_name": "TRAN VAN HUNG", "gender": ""}, "passport")
    assert _pick_spouse_side_from_marriage(marriage, applicant) == ""


def test_enrich_spouse_dob_from_worksheet_not_marriage():
    """spouse_date_of_birth không lấy từ marriage_certificate (lấy từ worksheet/GKS phối ngẫu)."""
    marriage = _rec(
        {
            "husband_full_name": "DANG VAN HUNG",
            "wife_date_of_birth": "1979-07-19",
        }
    )
    passport = _rec({"full_name": "DANG VAN HUNG", "gender": "MALE"}, "passport")
    fields = [
        {"key": "spouse_date_of_birth", "value": "", "source": {}},
        {"key": "spouse_surname", "value": "", "source": {}},
    ]
    enrich_spouse_section_from_marriage(fields, marriage, passport)
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["spouse_date_of_birth"] == ""  # không lấy từ giấy kết hôn



def test_split_vn_person_name_various_lengths():
    from app.services.ds260_mapping import _split_vn_person_name

    assert _split_vn_person_name("TRAN AN") == ("TRAN", "AN")
    assert _split_vn_person_name("TRAN VAN AN") == ("TRAN", "VAN AN")
    assert _split_vn_person_name("TRAN THI VAN AN") == ("TRAN", "THI VAN AN")
    assert _split_vn_person_name("TRAN") == ("TRAN", "")
    assert _split_vn_person_name("") == ("", "")
    assert _split_vn_person_name("  TRAN   VAN   AN  ") == ("TRAN", "VAN AN")


def test_enrich_spouse_fields():
    marriage = _rec(
        {
            "husband_full_name": "DANG VAN HUNG",
            "wife_full_name": "MAI NGOC HOA",
            "wife_date_of_birth": "1979-07-19",
            "marriage_date": "2006-12-21",
            "marriage_place": "People's Committee, Hai Chau District, Da Nang City, Vietnam",
        }
    )
    passport = _rec({"full_name": "DANG VAN HUNG", "gender": "Male"}, "passport")
    fields = [
        {"key": "spouse_surname", "value": "", "source": {}},
        {"key": "spouse_given_names", "value": "", "source": {}},
        {"key": "spouse_marriage_date", "value": "", "source": {}},
        {"key": "spouse_marriage_city", "value": "", "source": {}},
    ]
    enrich_spouse_section_from_marriage(fields, marriage, passport)
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["spouse_surname"] == "MAI"
    assert by_key["spouse_given_names"] == "NGOC HOA"
    assert by_key["spouse_marriage_date"] == "2006-12-21"
    assert by_key.get("spouse_marriage_city") or by_key.get("spouse_marriage_state")


def test_spouse_birth_place_from_spouse_birth_certificate():
    from app.services.ds260_mapping import (
        enrich_spouse_birth_place_from_birth_certificate,
        pick_spouse_birth_certificate,
    )

    marriage = _rec(
        {
            "husband_full_name": "NGUYEN PHUC THIEN",
            "wife_full_name": "NGUYEN KIEU TRINH",
            "marriage_date": "2018-12-04",
        }
    )
    passport = _rec({"full_name": "NGUYEN PHUC THIEN", "gender": "Male"}, "passport")
    spouse_bc = _rec(
        {
            "full_name": "NGUYEN KIEU TRINH",
            "date_of_birth": "1998-03-25",
            "place_of_birth": "LOC THANG, BAO LOC, LAM DONG",
        },
        "birth_certificate",
    )
    applicant_bc = _rec(
        {"full_name": "NGUYEN PHUC THIEN", "place_of_birth": "LAM DONG HOSPITAL II, BAO LOC TOWN"},
        "birth_certificate",
    )
    assert pick_spouse_birth_certificate(marriage, passport, [applicant_bc, spouse_bc]) is spouse_bc

    fields = [
        {"key": "spouse_birth_city", "value": "", "source": {}},
        {"key": "spouse_birth_state", "value": "", "source": {}},
        {"key": "spouse_date_of_birth", "value": "", "source": {}},
    ]
    enrich_spouse_birth_place_from_birth_certificate(
        fields, marriage, passport, [applicant_bc, spouse_bc]
    )
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["spouse_birth_city"] == "BAO LOC"
    assert by_key["spouse_birth_state"] == "LAM DONG"
    assert by_key["spouse_date_of_birth"] == "1998-03-25"


def test_occupation_from_profile_map():
    from app.services.ds260_mapping import _occupation_from_profile_map

    out = _occupation_from_profile_map(
        {
            "employment.primary_occupation": "Homemaker",
            "employment.occupation_other_specify": "Housewife",
        }
    )
    assert out["spouse_occupation"] == "Homemaker"
    assert out["spouse_occupation_other"] == "Housewife"


def test_spouse_section_cleared_without_applicable_marriage():
    from app.services.ds260_mapping import (
        clear_spouse_section_fields,
        enrich_empty_fields_from_all_doc_records,
        has_applicable_marriage_certificate,
    )

    wrong_marriage = _rec(
        {
            "husband_full_name": "DONG TRONG DUY",
            "wife_full_name": "TRUONG THI MY LE",
            "marriage_date": "2016-04-15",
            "marriage_place": "Binh Duong",
        }
    )
    passport = _rec({"full_name": "DANG VAN HUNG", "gender": "MALE"}, "passport")
    worksheet = _rec(
        {
            "spouse_surname": "TRUONG",
            "spouse_given_names": "THI MY LE",
            "spouse_date_of_birth": "1984-06-02",
            "spouse_immigrating": "Yes",
        },
        "ds260_customer_form",
    )
    assert not has_applicable_marriage_certificate(wrong_marriage, None, passport, None)

    fields = [
        {"key": "spouse_surname", "value": "TRUONG", "source": {"document_type": "marriage_certificate"}},
        {"key": "spouse_given_names", "value": "THI MY LE", "source": {}},
        {"key": "spouse_date_of_birth", "value": "1984-06-02", "source": {}},
        {"key": "spouse_immigrating", "value": "Yes", "source": {}},
    ]
    clear_spouse_section_fields(fields)
    sections = [{"id": "section_spouse", "fields": fields}]
    enrich_empty_fields_from_all_doc_records(sections, [wrong_marriage, passport, worksheet], {})
    clear_spouse_section_fields(sections[0]["fields"])
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["spouse_surname"] == ""
    assert by_key["spouse_given_names"] == ""
    assert by_key["spouse_date_of_birth"] == ""
    assert by_key["spouse_immigrating"] == ""


def test_spouse_section_fill_stats_exclude_review_hidden():
    from app.services.ds260_mapping import _attach_section_fill_stats

    sections = [
        {
            "id": "section_spouse",
            "fields": [
                {"key": "spouse_surname", "value": "MAI", "review_hidden": False},
                {"key": "spouse_given_names", "value": "THI HUONG", "review_hidden": False},
                {"key": "marriage_husband_name", "value": "DANG VAN HUNG", "review_hidden": True},
                {"key": "marriage_wife_name", "value": "MAI THI HUONG", "review_hidden": True},
            ],
        }
    ]
    filled, total, app_filled, app_total = _attach_section_fill_stats(sections, [])
    assert total == 2
    assert filled == 2
    assert sections[0]["total_count"] == 2
    assert sections[0]["filled_count"] == 2
    assert app_total == 0  # no marriage_certificate uploaded
    import uuid

    from app.services.ds260_mapping import pick_applicant_by_spouse_name

    wife_id = uuid.uuid4()
    husband_id = uuid.uuid4()
    wife = SimpleNamespace(id=wife_id, display_name="NGUYEN KIEU TRINH")
    husband = SimpleNamespace(id=husband_id, display_name="NGUYEN PHUC THIEN")
    picked = pick_applicant_by_spouse_name(
        [husband, wife],
        "NGUYEN KIEU TRINH",
        {str(husband_id): "NGUYEN PHUC THIEN", str(wife_id): "NGUYEN KIEU TRINH"},
    )
    assert picked is wife


def test_enrich_spouse_occupation_from_spouse_worksheet_in_family_case():
    """Hồ sơ gia đình: NGUYEN DANG DANG (chồng/chủ hồ sơ), NGUYEN HOANG YEN (vợ/phối ngẫu).
    Giấy kết hôn không ghi nghề nghiệp -> nghề nghiệp phối ngẫu được lấy từ worksheet của NGUYEN HOANG YEN.
    """
    from app.services.ds260_mapping import (
        enrich_spouse_occupation_from_spouse_records,
        sync_spouse_fields_from_spouse_records,
    )

    dang_dang_ws = _rec(
        {
            "applicant_name_native": "NGUYỄN ĐĂNG ĐĂNG",
            "applicant_name": "NGUYEN DANG DANG",
            "work_primary_occupation": "Driver",
        },
        "ds260_customer_form",
    )
    hoang_yen_ws = _rec(
        {
            "applicant_name_native": "NGUYỄN HOÀNG YẾN",
            "applicant_name": "NGUYEN HOANG YEN",
            "work_primary_occupation": "OTHER",
            "work_occupation_other_specify": "Nội trợ",
            "birth_city": "Chau Duc",
            "birth_state": "Ba Ria-Vung Tau",
            "birth_country": "Vietnam",
        },
        "ds260_customer_form",
    )

    records = [dang_dang_ws, hoang_yen_ws]

    fields = [
        {"key": "spouse_surname", "value": "NGUYEN", "source": {}},
        {"key": "spouse_given_names", "value": "HOANG YEN", "source": {}},
        {"key": "spouse_occupation", "value": "", "source": {}},
        {"key": "spouse_occupation_other", "value": "", "source": {}},
    ]

    enrich_spouse_occupation_from_spouse_records(
        fields, records, "NGUYEN HOANG YEN", person_name="NGUYEN DANG DANG"
    )

    by_key = {f["key"]: f["value"] for f in fields}
    by_source = {f["key"]: f.get("source", {}) for f in fields}

    assert by_key["spouse_occupation"] == "OTHER"
    assert by_key["spouse_occupation_other"] == "Nội trợ"
    assert by_source["spouse_occupation"].get("derived") == "spouse_occupation_from_spouse_ds260"


def test_sync_spouse_fields_from_spouse_worksheet():
    """Sync các trường spouse còn thiếu từ worksheet của phối ngẫu."""
    from app.services.ds260_mapping import sync_spouse_fields_from_spouse_records

    hoang_yen_ws = _rec(
        {
            "applicant_name_native": "NGUYỄN HOÀNG YẾN",
            "applicant_name": "NGUYEN HOANG YEN",
            "family_name": "NGUYEN",
            "given_names": "HOANG YEN",
            "date_of_birth": "2001-01-03",
            "birth_city": "Chau Duc",
            "birth_state": "Ba Ria-Vung Tau",
            "birth_country": "Vietnam",
            "current_address": "123 Le Loi, Phuong Ben Nghe, Quan 1, TP. Ho Chi Minh",
            "work_primary_occupation": "ACCOUNTING",
        },
        "ds260_customer_form",
    )

    records = [hoang_yen_ws]

    fields = [
        {"key": "spouse_surname", "value": "", "source": {}},
        {"key": "spouse_given_names", "value": "", "source": {}},
        {"key": "spouse_date_of_birth", "value": "", "source": {}},
        {"key": "spouse_birth_city", "value": "", "source": {}},
        {"key": "spouse_birth_state", "value": "", "source": {}},
        {"key": "spouse_birth_country", "value": "", "source": {}},
        {"key": "spouse_address", "value": "", "source": {}},
        {"key": "spouse_occupation", "value": "", "source": {}},
    ]

    sync_spouse_fields_from_spouse_records(fields, records, "NGUYEN HOANG YEN")

    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["spouse_surname"] == "NGUYEN"
    assert by_key["spouse_given_names"] == "HOANG YEN"
    assert by_key["spouse_date_of_birth"] == "2001-01-03"
    assert by_key["spouse_birth_city"] == "Chau Duc"
    assert by_key["spouse_birth_state"] == "Ba Ria-Vung Tau"
    assert by_key["spouse_birth_country"] == "Vietnam"
    assert "123 Le Loi" in by_key["spouse_address"]
    assert by_key["spouse_occupation"] == "ACCOUNTING"


