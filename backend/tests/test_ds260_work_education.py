"""DS-260 Part D — Work / Education / Training mapping."""

import json
from datetime import date
from types import SimpleNamespace

from app.services.document_registry import parse_document_filename
from app.services.ds260_customer_keys import normalize_ds260_customer_raw
from app.services.ds260_mapping import (
    detect_work_period_issues,
    enrich_empty_fields_from_all_doc_records,
    enrich_work_education_from_worksheet,
    flatten_ds260_mappings,
    format_prior_jobs_history_display,
    load_ds260_sections,
    parse_work_periods_from_text,
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


def test_current_job_uses_worksheet_value():
    """work_primary_occupation/work_present_employer PHẢI lấy từ DS-260 worksheet khi worksheet
    đã khai (khách yêu cầu 2026-08-13: DS-260 là nguồn duy nhất, Application form chỉ dùng để
    đối chiếu/tạo Conflict, không dùng để điền/bổ sung field nữa)."""
    app_form = _app_form(
        {
            "primary_occupation": "Manager",
            "present_employer": "Xuan Vu garment private enterprise",
            "employer_address": "41/40, Street #13, Ward 5, Go Vap District",
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
    assert occ_extra["derived"] == "ds260_worksheet_only"


def test_current_job_stays_empty_when_worksheet_missing_no_application_form_fallback():
    """Khi DS-260 worksheet KHÔNG khai Primary Occupation/Present Employer, field phải để TRỐNG
    — KHÔNG còn rơi về Application form nữa (thay đổi hành vi 2026-08-13, trước đây có fallback).
    Application form vẫn còn dữ liệu → build_worksheet_conflict_rows (ds260_conflicts.py) sẽ tạo
    Conflict để người dùng tự chọn điền, chứ field không tự động lấy."""
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

    assert occ_value == ""
    assert occ_rec is not None and occ_rec.doc_type == "ds260_customer_form"
    assert occ_extra["derived"] == "ds260_worksheet_only"


def test_current_job_subfields_never_come_from_application_form():
    """employer_address (và mọi field _WORK_CURRENT_JOB_KEYS khác) KHÔNG còn được bổ sung từ
    Application form nữa dù công việc trùng khớp — worksheet không khai thì để trống, chấm hết."""
    app_form = _app_form(
        {
            "primary_occupation": "Tailor",
            "present_employer": "Xuan Vu Garment Private Enterprise",
            "employer_address": "41/40, Street #13, Ward 5, Go Vap District",
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

    addr_value, _, addr_rec, addr_extra = resolve_work_current_job_field(
        records, mappings["work_employer_address"], {}
    )

    assert addr_value == ""
    assert addr_rec is not None and addr_rec.doc_type == "ds260_customer_form"
    assert addr_extra["derived"] == "ds260_worksheet_only"


def test_prior_jobs_history_uses_worksheet_value():
    """work_prior_jobs_history PHẢI lấy từ DS-260 worksheet khi worksheet đã khai — không còn
    ưu tiên/so sánh gì với Application form ở bước điền field (2026-08-13)."""
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
    assert extra["derived"] == "ds260_worksheet_only"


def test_prior_jobs_history_stays_empty_when_worksheet_missing_no_application_form_fallback():
    app_form = _app_form({"prior_jobs_history": "ABC Co - Staff - 2015-2018"})
    ws = _ws({"employment.primary_occupation": "May (Tu quan)"})
    records = [app_form, ws]
    mappings = flatten_ds260_mappings()

    value, _, rec, extra = resolve_work_prior_jobs_field(records, mappings["work_prior_jobs_history"], {})

    assert value == ""
    assert rec is not None and rec.doc_type == "ds260_customer_form"
    assert extra["derived"] == "ds260_worksheet_only"


def test_job_identity_tokens_matches_across_vietnamese_and_english():
    """So khớp mờ cùng công việc dù viết 2 ngôn ngữ khác nhau (dùng cho Conflict — khách yêu cầu
    2026-08-13: 'Công ty tư nhân của ông Tân Nguyên' và 'Private business of Mr. Tan Nguyen' là
    CÙNG 1 công ty, không phải 2 công ty khác nhau)."""
    from app.services.ds260_mapping import _job_identity_tokens

    vi_tokens = _job_identity_tokens("Nhân viên", "Công ty tư nhân của ông Tân Nguyên")
    en_tokens = _job_identity_tokens("Staff", "Private business of Mr. Tan Nguyen")
    overlap = len(vi_tokens & en_tokens) / len(vi_tokens | en_tokens)
    assert overlap >= 0.5


def test_parse_work_periods_dash_separated_vietnamese():
    text = "Xuan Vu garment private enterprise - quan ly - 01/01/2009 den 8/8/2018"
    periods = parse_work_periods_from_text(text)
    assert periods == [(date(2009, 1, 1), date(2018, 8, 8))]


def test_parse_work_periods_labeled_multi_entry_example_from_customer():
    """Ví dụ thật khách đưa 2026-08-13 — 2 entry, kiểu nhãn 'Bat Dau Lam Tu Ngay ... Ket Thuc
    Vao Ngay ...' và entry thứ 2 kết thúc mở ('Den Hien Tai')."""
    text = (
        "1. Ten Cong Ty : Greentech Headgear Co. Ltd Dia Chi : D02 Street, Nghia Thanh, "
        "Chau Duc Dist Vi Tri Lam Viec : Nhan Vien Ten Nguoi Quan Ly : Mai Quoc Thai "
        "Sdt : +84 251 3685 868 Bat Dau Lam Tu Ngay 06/02/2019 Ket Thuc Vao Ngay 11/09/2020; "
        "2. Ten Cong Ty : Cong Ty Tu Nhan Cua Ong Tan Nguyen Dia Chi : Thon Song Cau, Xa "
        "Nghia Thanh, Huyen Chau Duc Vi Tri Lam Viec : Nhan Vien Ten Nguoi Quan Ly : Nguyen "
        "Dang Tan Sdt : +84 908632451 Bat Dau Lam Tu Ngay : 11/11/2020 Den Hien Tai"
    )
    periods = parse_work_periods_from_text(text)
    assert periods == [
        (date(2019, 2, 6), date(2020, 9, 11)),
        (date(2020, 11, 11), None),
    ]


def _ws_period(raw: dict) -> SimpleNamespace:
    return SimpleNamespace(
        doc_type="ds260_customer_form",
        variant="exception",
        form_data="{}",
        raw_data=json.dumps(raw),
        updated_at=None,
        id="ws",
        source_document_id="ws-doc",
    )


def _app_period(raw: dict) -> SimpleNamespace:
    return SimpleNamespace(
        doc_type="application_form",
        variant="standard",
        form_data="{}",
        raw_data=json.dumps(raw),
        updated_at=None,
        id="app",
        source_document_id="app-doc",
    )


def test_detect_work_period_issues_start_after_date_signed():
    """Ngày bắt đầu công việc hiện tại SAU ngày ký (Date signed) trên Application form → cảnh
    báo hệ thống (khách yêu cầu 2026-08-13), không phải Conflict."""
    ws = _ws_period(
        {
            "employment.primary_occupation": "Nhan vien",
            "employment.present_employer": "ABC Co",
            "work_start_date": "01/01/2026",
        }
    )
    app_form = _app_period({"date_signed": "01/06/2025"})
    issues = detect_work_period_issues([ws, app_form], {}, person_name="A")
    assert issues["start_after_signed"] == {"start": "01/01/2026", "date_signed": "01/06/2025"}


def test_detect_work_period_issues_no_warning_when_start_before_signed():
    ws = _ws_period(
        {
            "employment.primary_occupation": "Nhan vien",
            "employment.present_employer": "ABC Co",
            "work_start_date": "01/01/2024",
        }
    )
    app_form = _app_period({"date_signed": "01/06/2025"})
    issues = detect_work_period_issues([ws, app_form], {}, person_name="A")
    assert "start_after_signed" not in issues


def test_detect_work_period_issues_overlapping_jobs():
    """Khách khai ≥ 2 công việc trùng thời điểm → warning "overlapping_periods", không phải
    Conflict (khách yêu cầu 2026-08-13)."""
    ws = _ws_period(
        {
            "employment.primary_occupation": "Nhan vien",
            "employment.present_employer": "DEF Co",
            "work_start_date": "01/01/2020",
            "employment.prior_jobs_history": "Cong ty ABC - 01/06/2019 den 01/06/2021",
        }
    )
    issues = detect_work_period_issues([ws], {}, person_name="A")
    assert "overlapping_periods" in issues
    assert len(issues["overlapping_periods"]) == 1


def test_detect_work_period_issues_no_overlap_when_sequential():
    ws = _ws_period(
        {
            "employment.primary_occupation": "Nhan vien",
            "employment.present_employer": "DEF Co",
            "work_start_date": "01/01/2022",
            "employment.prior_jobs_history": "Cong ty ABC - 01/06/2019 den 01/06/2021",
        }
    )
    issues = detect_work_period_issues([ws], {}, person_name="A")
    assert "overlapping_periods" not in issues


def test_detect_work_period_issues_current_matches_closed_prior_entry():
    """Công việc "hiện tại" trùng công ty với 1 entry ĐÃ có ngày kết thúc trong lịch sử — dấu
    hiệu khách ghi nhầm, việc đó thực ra đã nghỉ (khách yêu cầu 2026-08-13)."""
    ws = _ws_period(
        {
            "employment.primary_occupation": "Nhan vien",
            "employment.present_employer": "Greentech Headgear Co",
            "work_start_date": "01/01/2022",
            "employment.prior_jobs_history": (
                "Bat Dau Lam Tu Ngay 06/02/2019 Ket Thuc Vao Ngay 11/09/2020 Ten Cong Ty "
                "Greentech Headgear Co"
            ),
        }
    )
    issues = detect_work_period_issues([ws], {}, person_name="A")
    assert "current_matches_closed_prior" in issues


_PRIOR_JOBS_CUSTOMER_EXAMPLE = (
    "1. Ten Cong Ty : Greentech Headgear Co. Ltd Dia Chi : D02 Street, Nghia Thanh, "
    "Chau Duc Dist Vi Tri Lam Viec : Nhan Vien Ten Nguoi Quan Ly : Mai Quoc Thai "
    "Sdt : +84 251 3685 868 Bat Dau Lam Tu Ngay 06/02/2019 Ket Thuc Vao Ngay 11/09/2020; "
    "2. Ten Cong Ty : Cong Ty Tu Nhan Cua Ong Tan Nguyen Dia Chi : Thon Song Cau, Xa "
    "Nghia Thanh, Huyen Chau Duc Vi Tri Lam Viec : Nhan Vien Ten Nguoi Quan Ly : Nguyen "
    "Dang Tan Sdt : +84 908632451 Bat Dau Lam Tu Ngay : 11/11/2020 Den Hien Tai"
)


def test_format_prior_jobs_history_reformats_each_entry_to_three_lines():
    """Ví dụ thật khách đưa 2026-08-13 — mỗi entry viết lại 3 dòng: ngày lên đầu, rồi công ty +
    vị trí, rồi quản lý + SĐT."""
    out = format_prior_jobs_history_display(_PRIOR_JOBS_CUSTOMER_EXAMPLE)
    lines = out.split("\n")
    assert lines[0] == "1. Bat Dau Lam Tu Ngay 06/02/2019 Ket Thuc Vao Ngay 11/09/2020"
    assert "Ten Cong Ty: Greentech Headgear Co. Ltd" in lines[1]
    assert "Vi Tri Lam Viec: Nhan Vien" in lines[1]
    assert "Sdt: +84 251 3685 868." in lines[2]
    assert lines[3] == "2. Bat Dau Lam Tu Ngay 11/11/2020 Den Hien Tai"


def test_format_prior_jobs_history_removes_open_ended_duplicate_of_current_job():
    """Entry trùng công việc HIỆN TẠI và KHÔNG có ngày kết thúc cụ thể (khoảng mở/Present) bị
    loại khỏi lịch sử — công việc đang làm không thuộc "lịch sử" (khách yêu cầu 2026-08-13)."""
    out = format_prior_jobs_history_display(
        _PRIOR_JOBS_CUSTOMER_EXAMPLE,
        current_occupation="Nhan vien",
        current_employer="Cong Ty Tu Nhan Cua Ong Tan Nguyen",
    )
    assert "Tan Nguyen" not in out
    assert "Greentech" in out
    assert not out.startswith("2.")
    assert out.count("\n") == 2  # chỉ còn đúng 1 entry (3 dòng)


def test_format_prior_jobs_history_keeps_entry_with_definite_end_date_even_if_matches_current():
    """Entry trùng công việc hiện tại NHƯNG CÓ ngày kết thúc rõ ràng KHÔNG bị loại — đây là dấu
    hiệu khách ghi nhầm (việc "hiện tại" có thể đã nghỉ) mà detect_work_period_issues() cần thấy
    để cảnh báo; xoá đi sẽ giấu mất bằng chứng (khách yêu cầu 2026-08-13)."""
    out = format_prior_jobs_history_display(
        _PRIOR_JOBS_CUSTOMER_EXAMPLE,
        current_occupation="Nhan vien",
        current_employer="Greentech Headgear Co",
    )
    assert "Greentech" in out
    assert "Tan Nguyen" in out  # cả 2 entry vẫn còn


def test_format_prior_jobs_history_preserves_vietnamese_diacritics():
    """Khách khai tiếng Việt có dấu thì OCR ra vẫn giữ nguyên có dấu, KHÔNG tự bỏ dấu (khách
    yêu cầu 2026-08-13)."""
    text = (
        "1. Tên Công Ty : Xưởng May Xuân Vũ Vị Trí Làm Việc : Nhân viên "
        "Bắt Đầu Làm Từ Ngày 01/01/2018 Kết Thúc Vào Ngày 01/01/2020"
    )
    out = format_prior_jobs_history_display(text)
    assert "Xưởng May Xuân Vũ" in out
    assert "Nhân viên" in out


def test_format_prior_jobs_history_unrecognized_text_kept_as_is():
    """Text không theo mẫu nhãn quen thuộc → giữ nguyên văn, không cố ép cấu trúc lên nó."""
    text = "Đã từng đi phụ hồ một thời gian, không nhớ rõ công ty."
    assert format_prior_jobs_history_display(text) == text


def test_resolve_work_prior_jobs_field_applies_formatting_and_dedup():
    """Đường thật (qua resolve_work_prior_jobs_field, không gọi hàm format trực tiếp) — worksheet
    khai cả công việc hiện tại lẫn lịch sử, entry trùng công việc hiện tại (khoảng mở) phải bị
    loại khỏi giá trị field cuối cùng."""
    ws = _ws(
        {
            "employment.primary_occupation": "Nhan vien",
            "employment.present_employer": "Cong Ty Tu Nhan Cua Ong Tan Nguyen",
            "employment.prior_jobs_history": _PRIOR_JOBS_CUSTOMER_EXAMPLE,
        }
    )
    records = [ws]
    mappings = flatten_ds260_mappings()
    value, *_ = resolve_work_prior_jobs_field(records, mappings["work_prior_jobs_history"], {})
    assert "Greentech" in value
    assert "Tan Nguyen" not in value
