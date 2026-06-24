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
