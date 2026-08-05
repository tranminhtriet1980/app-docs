"""DS-260 conflicts — document_vs_exception and document_vs_worksheet."""

import json
from types import SimpleNamespace
from uuid import uuid4

from app.services.ds260_conflicts import (
    LUONG1_DOC_TYPES,
    WORKSHEET_COMPARE_KEYS,
    build_worksheet_conflict_rows,
    conflict_label_vi,
    conflict_type_from_field_key,
    ds260_conflict_field_key,
    norm_conflict_value,
    parse_ds260_conflict_key,
    worksheet_conflict_field_key,
    _norm_value,
)


def test_luong1_doc_types():
    assert "passport" in LUONG1_DOC_TYPES
    assert "birth_certificate" in LUONG1_DOC_TYPES
    assert "judicial_certificate" in LUONG1_DOC_TYPES
    assert "marriage_certificate" in LUONG1_DOC_TYPES
    assert "divorce" not in LUONG1_DOC_TYPES


def test_conflict_field_key():
    assert ds260_conflict_field_key("passport", "full_name") == "ds260.passport.full_name"
    assert parse_ds260_conflict_key("ds260.passport.full_name") == ("passport", "full_name")


def test_worksheet_conflict_field_key():
    assert worksheet_conflict_field_key("applicant_name") == "ds260.document_vs_worksheet.applicant_name"
    assert parse_ds260_conflict_key("ds260.document_vs_worksheet.applicant_name") == (
        "document_vs_worksheet",
        "applicant_name",
    )
    assert conflict_type_from_field_key("ds260.document_vs_worksheet.gender") == "document_vs_worksheet"
    assert conflict_type_from_field_key("ds260.passport.full_name") == "document_vs_exception"


def test_worksheet_conflict_label_shows_ds260_section_not_just_generic_worksheet():
    """Yêu cầu thực tế 2026-08-04: "ở mục gì trong cái DS260 luôn á" — nhãn conflict phải ghi
    rõ MỤC (section) trên form DS-260, không chỉ nói chung chung "DS-260 worksheet"."""
    label = conflict_label_vi(worksheet_conflict_field_key("current_state"))
    assert "DS-260 3" in label
    assert "ADDRESS" in label
    assert "State/Province" in label

    label_work = conflict_label_vi(worksheet_conflict_field_key("work_job_title"))
    assert "DS-260 D" in label_work
    assert "Work" in label_work


def test_worksheet_compare_keys_cover_user_fields():
    assert "applicant_name" in WORKSHEET_COMPARE_KEYS
    assert "place_of_birth" in WORKSHEET_COMPARE_KEYS
    assert "passport_expiration_date" in WORKSHEET_COMPARE_KEYS
    assert "current_marital_status" in WORKSHEET_COMPARE_KEYS
    assert "current_address" in WORKSHEET_COMPARE_KEYS
    assert "primary_phone" in WORKSHEET_COMPARE_KEYS
    assert "email" in WORKSHEET_COMPARE_KEYS


def test_worksheet_compare_keys_include_section_d_work_education():
    """Job Application (application_form) Section D — trừ narrative tự do work_prior_jobs_history."""
    assert "work_primary_occupation" in WORKSHEET_COMPARE_KEYS
    assert "work_present_employer" in WORKSHEET_COMPARE_KEYS
    assert "work_job_title" in WORKSHEET_COMPARE_KEYS
    assert "edu_college_name" in WORKSHEET_COMPARE_KEYS
    assert "work_prior_jobs_history" not in WORKSHEET_COMPARE_KEYS
    # Không lẫn field nguồn ds260_customer_form (so worksheet với chính nó là vô nghĩa)
    assert "work_other_occupation_used" not in WORKSHEET_COMPARE_KEYS


def test_norm_value():
    assert _norm_value("  Da Nang  ") == "DA NANG"


def test_norm_conflict_value_dates_and_gender():
    assert norm_conflict_value("gender", "male") == "MALE"
    assert norm_conflict_value("gender", "F") == "FEMALE"
    assert norm_conflict_value("date_of_birth", "1990-01-15") == "1990-01-15"
    assert norm_conflict_value("date_of_birth", "15/01/1990") == "1990-01-15"


def _rec(raw: dict, doc_type: str, *, variant: str = "standard") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        doc_type=doc_type,
        variant=variant,
        source_document_id=uuid4(),
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
        updated_at=None,
    )


def test_build_worksheet_conflict_when_values_differ():
    passport_std = _rec({"full_name": "NGUYEN VAN A", "date_of_birth": "1990-01-15"}, "passport")
    ds260 = _rec(
        {
            "applicant_name": "NGUYEN VAN B",
            "date_of_birth": "1990-01-15",
        },
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([passport_std, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("applicant_name") in keys
    assert worksheet_conflict_field_key("date_of_birth") not in keys


def test_build_worksheet_conflict_skips_when_normalized_equal():
    passport_std = _rec({"full_name": "NGUYEN VAN A", "gender": "MALE"}, "passport")
    ds260 = _rec({"applicant_name": "nguyen van a", "gender": "M"}, "ds260_customer_form", variant="exception")
    rows = build_worksheet_conflict_rows([passport_std, ds260], {})
    assert rows == []


def test_build_worksheet_conflict_respects_resolved():
    passport_std = _rec({"full_name": "A"}, "passport")
    ds260 = _rec({"applicant_name": "B"}, "ds260_customer_form", variant="exception")
    fk = worksheet_conflict_field_key("applicant_name")
    rows = build_worksheet_conflict_rows([passport_std, ds260], {fk: "A"})
    assert rows == []


def test_build_worksheet_conflict_address_application_form_vs_worksheet():
    """current_address đối chiếu với Job Application (application_form), không phải passport.

    passport KHÔNG có current_address — trước đây override trỏ vào "passport" nên
    _official_value_for_worksheet_compare luôn trả rỗng và field này KHÔNG BAO GIỜ tạo
    Conflict dù worksheet với giấy tờ khác nhau (báo lỗi thực tế 2026-08-04, "cứ điền rồi
    fill" không hề đối chiếu).
    """
    application = _rec(
        {"current_address": "123 LE LOI"},
        "application_form",
    )
    ds260 = _rec(
        {"current_address": "456 TRAN PHU"},
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("current_address") in keys
    row = next(r for r in rows if r["field_key"] == worksheet_conflict_field_key("current_address"))
    assert row["value_a"] == "123 LE LOI"
    assert row["value_b"] == "456 TRAN PHU"


def test_build_worksheet_conflict_address_passport_no_longer_used_as_source():
    """passport không còn được dùng làm nguồn đối chiếu current_address — không tạo Conflict
    dù worksheet khác giá trị, vì official_val luôn rỗng (passport không có field này)."""
    passport_ref = _rec({"current_address": "123 LE LOI"}, "passport", variant="exception")
    ds260 = _rec({"current_address": "456 TRAN PHU"}, "ds260_customer_form", variant="exception")
    rows = build_worksheet_conflict_rows([passport_ref, ds260], {})
    assert rows == []


def test_build_worksheet_conflict_phone_and_email():
    """Nguồn đối chiếu SĐT/email là application_form (Job Application, mục Applicant's
    Information) — KHÔNG phải passport (passport không có số điện thoại/email; override cũ
    trỏ "passport" là bug cùng lớp với current_address, sửa 2026-08-05)."""
    application_form_ref = _rec(
        {"primary_phone_number": "+84901112233", "email_address": "a@example.com"},
        "application_form",
        variant="standard",
    )
    ds260 = _rec(
        {"primary_phone_number": "+84909998888", "email_address": "b@example.com"},
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([application_form_ref, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("primary_phone") in keys
    assert worksheet_conflict_field_key("email") in keys


def test_application_form_extract_schema_has_personal_current_address():
    """Trước đây application_form chỉ có employer_address (địa chỉ CÔNG TY) — thiếu
    current_address cá nhân nên OCR không đọc được field này dù có trên giấy, và
    _filter_extraction_to_schema (ocr_pipeline.py) sẽ âm thầm loại field lạ khỏi kết quả."""
    from app.services.ocr_pipeline import get_extract_keys_for_doc_type

    keys = get_extract_keys_for_doc_type("application_form")
    assert "current_address" in keys
    assert "address_city" in keys
    assert "address_state" in keys
    assert "address_country" in keys
    # Employer address vẫn còn — không bị thay thế, chỉ thêm field cá nhân.
    assert "employer_address" in keys


def test_build_worksheet_conflict_address_city_state_postal_from_real_case():
    """Ca thật 2026-08-04 (TRIEU THI DUYEN): Job Application mục 1 và worksheet DS-260 mục 3
    ghi lệch nhau — City/State bị đảo, Postal Code worksheet ghi tên khu vực thay vì để trống
    như application_form. Phải tạo Conflict cho City/State/Postal, KHÔNG tự điền worksheet."""
    application = _rec(
        {
            "current_address": "KIMBANGO",
            "address_city": "LUANDA",
            "address_state": "KIMBANGO",
            "address_country": "ANGOLA",
            "postal_code": "N/A",
        },
        "application_form",
    )
    ds260 = _rec(
        {
            "current_state": "LUANDA",
            "postal_code": "KILAMBA - KIAXI - KIMBANGO",
            "current_country": "ANGOLA",
        },
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}

    # State bị đảo với City (Job App: state=KIMBANGO; worksheet: state=LUANDA) → conflict.
    assert worksheet_conflict_field_key("current_state") in keys
    # Postal Code: N/A (Job App) vs tên khu vực (worksheet) → conflict.
    assert worksheet_conflict_field_key("postal_code") in keys
    # Country khớp nhau (ANGOLA cả hai) → không tạo conflict thừa.
    assert worksheet_conflict_field_key("current_country") not in keys
    # City: worksheet để trống (không ghi) → không đủ dữ liệu để so, không tạo conflict.
    assert worksheet_conflict_field_key("current_city") not in keys


def test_build_worksheet_conflict_job_title_and_employer():
    application = _rec(
        {"primary_occupation": "Sales Staff", "present_employer": "ABC Co", "job_title": "Manager"},
        "application_form",
    )
    ds260 = _rec(
        {"primary_occupation": "Tailor", "present_employer": "XYZ Co", "job_title": "Staff"},
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("work_primary_occupation") in keys
    assert worksheet_conflict_field_key("work_present_employer") in keys
    assert worksheet_conflict_field_key("work_job_title") in keys


def test_apply_ds260_resolved_conflicts_worksheet_and_luong1():
    from app.services.ds260_conflicts import apply_ds260_resolved_conflicts

    sections = [
        {
            "fields": [
                {"key": "applicant_name", "value": "WRONG", "source": {}},
                {"key": "gender", "value": "Male", "source": {}},
            ]
        }
    ]
    resolutions = {
        worksheet_conflict_field_key("applicant_name"): "DANG VAN HUNG",
        ds260_conflict_field_key("passport", "full_name"): "DANG VAN HUNG",
        ds260_conflict_field_key("passport", "gender"): "Female",
    }
    apply_ds260_resolved_conflicts(sections, resolutions)
    by_key = {f["key"]: f for f in sections[0]["fields"]}
    assert by_key["applicant_name"]["value"] == "DANG VAN HUNG"
    assert by_key["applicant_name"]["source"]["derived"] == "worksheet_conflict_resolution"
    assert by_key["gender"]["value"] == "Female"
    assert by_key["gender"]["source"]["derived"] == "conflict_resolution"


def test_worksheet_compare_keys_include_parent_info():
    """Thông tin cha/mẹ trước đây KHÔNG có trong danh sách so worksheet — báo lỗi thực tế
    2026-08-05: birth_certificate và worksheet DS-260 khách khai chưa bao giờ được đối chiếu
    cho họ tên/ngày sinh/nơi sinh cha mẹ."""
    assert "father_full_name" in WORKSHEET_COMPARE_KEYS
    assert "father_surname" in WORKSHEET_COMPARE_KEYS
    assert "father_date_of_birth" in WORKSHEET_COMPARE_KEYS
    assert "mother_full_name" in WORKSHEET_COMPARE_KEYS
    assert "mother_surname" in WORKSHEET_COMPARE_KEYS
    assert "mother_date_of_birth" in WORKSHEET_COMPARE_KEYS


def test_principal_parent_info_conflict_uses_own_birth_certificate():
    """Đương đơn: nguồn chính thức là birth_certificate CỦA CHÍNH HỌ — khác worksheet thì
    tạo conflict như các field khác."""
    birth_cert = _rec(
        {
            "father_surname": "NGUYEN",
            "father_given_names": "VAN HUNG",
            "father_date_of_birth": "1975-05-05",
        },
        "birth_certificate",
    )
    ws = _rec(
        {
            "father_surname": "TRAN",
            "father_given_names": "VAN HUNG",
            "father_date_of_birth": "1975-05-05",
        },
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([birth_cert, ws], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("father_surname") in keys
    assert worksheet_conflict_field_key("father_given_names") not in keys  # khớp nhau — không tạo


def test_child_parent_info_conflict_falls_back_to_birth_certificate_child():
    """Con cái: không có birth_certificate riêng (chỉ có birth_certificate_child do cha/mẹ
    khai) — vẫn phải so được father_full_name/mother_full_name với worksheet CỦA CHÍNH CON,
    dùng birth_certificate_child làm nguồn chính thức thay thế."""
    child_bc = _rec(
        {"child_full_name": "NGUYEN MINH PHUONG", "father_name": "NGUYEN VAN HUNG", "mother_name": "TRIEU THI DUYEN"},
        "birth_certificate_child",
    )
    child_ws = _rec(
        {"father_full_name": "NGUYEN VAN HAI", "mother_full_name": "TRIEU THI DUYEN"},
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([child_bc, child_ws], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("father_full_name") in keys, (
        f"father_full_name phải so được qua fallback birth_certificate_child, rows={rows}"
    )
    assert worksheet_conflict_field_key("mother_full_name") not in keys  # khớp nhau


def test_child_parent_info_no_conflict_when_only_birth_cert_child_present_and_matches():
    """Con cái: worksheet khớp với birth_certificate_child — không tạo conflict thừa."""
    child_bc = _rec(
        {"child_full_name": "NGUYEN MINH PHUONG", "father_name": "NGUYEN VAN HUNG"},
        "birth_certificate_child",
    )
    child_ws = _rec(
        {"father_full_name": "NGUYEN VAN HUNG"},
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([child_bc, child_ws], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("father_full_name") not in keys
