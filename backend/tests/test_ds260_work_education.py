"""DS-260 Part D — Work / Education / Training mapping."""

import json
from types import SimpleNamespace

from app.services.document_registry import parse_document_filename
from app.services.ds260_customer_keys import normalize_ds260_customer_raw
from app.services.ds260_mapping import (
    enrich_empty_fields_from_all_doc_records,
    enrich_work_education_from_worksheet,
    load_ds260_sections,
)


def _ws(raw: dict) -> SimpleNamespace:
    return SimpleNamespace(
        doc_type="ds260_customer_form",
        variant="exception",
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
        updated_at=None,
        id="ws",
        source_document_id="ws-doc",
    )


def test_work_education_section_in_mapping():
    sections = {s.id: s for s in load_ds260_sections()}
    assert "section_work_education" in sections
    sec = sections["section_work_education"]
    keys = {f.key for f in sec.fields}
    assert "work_primary_occupation" in keys
    assert "edu_college_name" in keys
    assert len(sec.fields) >= 20


def test_application_form_filename_detection():
    assert parse_document_filename("01_7 Application form.pdf") == ("application_form", False)
    assert parse_document_filename("Application form_new.pdf") == ("application_form", True)
    assert parse_document_filename("DS260_new.pdf") == ("ds260_customer_form", True)


def test_normalize_education_from_profile_dot_keys():
    raw = {
        "education.middle_school_name": "Le Do Secondary School",
        "education.high_school_name": "Hoang Hoa Tham High School",
        "education.college_name": "Hanoi Open University",
        "education.college_major": "Business Administration",
    }
    out = normalize_ds260_customer_raw(raw)
    assert out["edu_middle_school_name"] == "Le Do Secondary School"
    assert out["edu_high_school_name"] == "Hoang Hoa Tham High School"
    assert out["edu_college_name"] == "Hanoi Open University"
    assert out["edu_college_major"] == "Business Administration"


def test_work_education_fills_from_worksheet_without_application_form():
    """CHIEM ANH HANG pattern: chỉ có DS-260 khách khai, chưa có Application form."""
    ws = _ws(
        {
            "education.middle_school_name": "Le Quy Don Secondary School",
            "education.middle_school_address": "Da Nang, Vietnam",
            "education.middle_school_period": "1990 - 1994",
            "education.high_school_name": "Phan Chau Trinh High School",
            "education.high_school_address": "Da Nang, Vietnam",
            "education.high_school_period": "1994 - 1997",
            "education.college_name": "Da Nang University",
            "education.college_major": "Accounting",
            "employment.primary_occupation": "Accountant",
            "employment.present_employer": "ABC Company",
        }
    )
    sections = [
        {
            "id": "section_work_education",
            "fields": [
                {"key": "work_primary_occupation", "value": "", "source": {}},
                {"key": "work_present_employer", "value": "", "source": {}},
                {"key": "edu_middle_school_name", "value": "", "source": {}},
                {"key": "edu_high_school_name", "value": "", "source": {}},
                {"key": "edu_college_name", "value": "", "source": {}},
                {"key": "edu_college_major", "value": "", "source": {}},
            ],
        }
    ]
    enrich_empty_fields_from_all_doc_records(sections, [ws], {})
    enrich_work_education_from_worksheet(sections[0]["fields"], [ws], {})
    by_key = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert by_key["edu_middle_school_name"] == "Le Quy Don Secondary School"
    assert by_key["edu_high_school_name"] == "Phan Chau Trinh High School"
    assert by_key["edu_college_name"] == "Da Nang University"
    assert by_key["edu_college_major"] == "Accounting"
    assert by_key["work_primary_occupation"] == "Accountant"
    assert by_key["work_present_employer"] == "ABC Company"
