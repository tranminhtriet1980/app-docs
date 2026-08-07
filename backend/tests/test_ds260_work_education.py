"""DS-260 Part D — Work / Education / Training mapping."""

import json
from types import SimpleNamespace

from app.services.document_registry import parse_document_filename
from app.services.ds260_customer_keys import normalize_ds260_customer_raw
from app.services.ds260_mapping import (
    enrich_empty_fields_from_all_doc_records,
    enrich_work_education_from_worksheet,
    flatten_ds260_mappings,
    load_ds260_sections,
    resolve_work_current_job_field,
    resolve_work_prior_jobs_field,
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


def _app_form(raw: dict) -> SimpleNamespace:
    return SimpleNamespace(
        doc_type="application_form",
        variant="standard",
        form_data=json.dumps(raw),
        raw_data="{}",
        updated_at=None,
        id="app",
        source_document_id="app-doc",
    )


def test_current_job_prefers_worksheet_over_stale_application_form():
    """Khách nộp Job Application cũ (liệt kê công ty may cũ là 'Present' vì form không có
    trường end date), nhưng DS-260 tự khai (mới hơn) nói rõ công ty đó ĐÃ NGHỈ (01/01/2009 -
    8/8/2018) và nghề nghiệp hiện tại là 'May (Tự quản)' / tự làm. work_primary_occupation
    và work_present_employer phải lấy từ DS-260 worksheet, không phải Application form."""
    app_form = _app_form(
        {
            "primary_occupation": "Manager",
            "present_employer": "Xuan Vu garment private enterprise",
            "employer_address": "41/40, Street #13, Ward 5, Go Vap District",
            "employer_city": "Ho Chi Minh",
            "employer_country": "Vietnam",
            "job_title": "Manager",
            "employment_start_date": "2009-01-01",
        }
    )
    ws = _ws(
        {
            "employment.primary_occupation": "May (Tu quan)",
            "employment.present_employer": "May (Tu quan)",
            "employment.other_occupation_used": "Yes",
            "employment.other_occupation_detail": (
                "Ten cong ty: Xuan Vu garment private enterprise. Vi tri cong viec: quan ly. "
                "Tu 01/01/2009 - 8/8/2018."
            ),
        }
    )
    records = [app_form, ws]
    mappings = flatten_ds260_mappings()

    occ_value, _, occ_rec, occ_extra = resolve_work_current_job_field(
        records, mappings["work_primary_occupation"], {}
    )
    emp_value, _, emp_rec, _ = resolve_work_current_job_field(
        records, mappings["work_present_employer"], {}
    )

    assert occ_value == "May (Tu quan)"
    assert emp_value == "May (Tu quan)"
    assert occ_rec.doc_type == "ds260_customer_form"
    assert emp_rec.doc_type == "ds260_customer_form"
    assert occ_extra["derived"] == "ds260_worksheet_current_job_priority"

    # công ty may cũ vẫn phải còn — nhưng chỉ trong Other occupation details
    other_detail = mappings["work_other_occupation_detail"]
    from app.services.ds260_mapping import resolve_customer_form_field

    detail_value, *_ = resolve_customer_form_field(records, "ds260_customer_form", other_detail)
    assert "Xuan Vu garment" in detail_value


def test_current_job_falls_back_to_application_form_when_worksheet_empty():
    """Khi DS-260 worksheet không khai Primary Occupation/Present Employer, vẫn phải rơi về
    Application form như hành vi cũ."""
    app_form = _app_form(
        {
            "primary_occupation": "Sales Staff",
            "present_employer": "Dung Grocery Store",
        }
    )
    ws = _ws({"employment.other_occupation_used": "No"})
    records = [app_form, ws]
    mappings = flatten_ds260_mappings()

    occ_value, _, occ_rec, occ_extra = resolve_work_current_job_field(
        records, mappings["work_primary_occupation"], {}
    )

    assert occ_value == "Sales Staff"
    assert occ_rec.doc_type == "application_form"
    assert "derived" not in occ_extra or occ_extra.get("derived") != "ds260_worksheet_current_job_priority"


def test_current_job_subfields_from_application_form_skipped_when_different_job():
    """Worksheet đã khai nghề hiện tại (May tự quản) khác hẳn công ty trong Application form
    (Xuan Vu garment, công ty CŨ) — dù worksheet không có employer_address riêng, KHÔNG được
    lấy địa chỉ công ty may cũ từ Application form gán vào công việc hiện tại."""
    app_form = _app_form(
        {
            "primary_occupation": "Manager",
            "present_employer": "Xuan Vu garment private enterprise",
            "employer_address": "41/40, Street #13, Ward 5, Go Vap District",
            "employer_city": "Ho Chi Minh",
        }
    )
    ws = _ws(
        {
            "employment.primary_occupation": "May (Tu quan)",
            "employment.present_employer": "May (Tu quan)",
        }
    )
    records = [app_form, ws]
    mappings = flatten_ds260_mappings()

    addr_value, _, addr_rec, addr_extra = resolve_work_current_job_field(
        records, mappings["work_employer_address"], {}
    )

    assert addr_value == ""
    assert addr_rec is None
    assert addr_extra.get("derived") == "application_form_stale_job_skipped"


def test_current_job_subfields_from_application_form_used_when_same_job():
    """Cùng công việc (chỉ khác cách viết) giữa DS-260 và Application form — vẫn phải lấy bổ
    sung địa chỉ/chi tiết từ Application form khi worksheet không khai riêng."""
    app_form = _app_form(
        {
            "primary_occupation": "Tailor",
            "present_employer": "Xuan Vu Garment Private Enterprise",
            "employer_address": "41/40, Street #13, Ward 5, Go Vap District",
            "employer_city": "Ho Chi Minh",
        }
    )
    ws = _ws(
        {
            "employment.primary_occupation": "Tho may",
            "employment.present_employer": "Xuan Vu garment",
        }
    )
    records = [app_form, ws]
    mappings = flatten_ds260_mappings()

    addr_value, _, addr_rec, _ = resolve_work_current_job_field(
        records, mappings["work_employer_address"], {}
    )

    assert addr_value == "41/40, Street #13, Ward 5, Go Vap District"
    assert addr_rec.doc_type == "application_form"


def test_prior_jobs_history_prefers_worksheet_over_application_form():
    """DS-260 worksheet khai lịch sử việc làm cũ MỚI HƠN và có ngày kết thúc rõ ràng — phải ưu
    tiên hơn Application form (thường ghi "Present" vì form không có trường end date)."""
    app_form = _app_form(
        {
            "prior_jobs_history": "Xuan Vu garment private enterprise - Manager - from 2009 - Present"
        }
    )
    ws = _ws(
        {
            "employment.prior_jobs_history": (
                "Xuan Vu garment private enterprise - quan ly - 01/01/2009 den 8/8/2018"
            )
        }
    )
    records = [app_form, ws]
    mappings = flatten_ds260_mappings()

    value, _, rec, extra = resolve_work_prior_jobs_field(records, mappings["work_prior_jobs_history"], {})

    assert value == "Xuan Vu garment private enterprise - quan ly - 01/01/2009 den 8/8/2018"
    assert rec.doc_type == "ds260_customer_form"
    assert extra["derived"] == "ds260_worksheet_prior_jobs_priority"


def test_prior_jobs_history_falls_back_to_application_form_when_worksheet_empty():
    app_form = _app_form({"prior_jobs_history": "ABC Co - Staff - 2015-2018"})
    ws = _ws({"employment.primary_occupation": "May (Tu quan)"})
    records = [app_form, ws]
    mappings = flatten_ds260_mappings()

    value, _, rec, extra = resolve_work_prior_jobs_field(records, mappings["work_prior_jobs_history"], {})

    assert value == "ABC Co - Staff - 2015-2018"
    assert rec.doc_type == "application_form"
    assert extra.get("derived") != "ds260_worksheet_prior_jobs_priority"
