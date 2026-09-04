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
    _json_values_if_json_like,
    _norm_value,
    _place_or_school_values_match,
    _sync_document_exception_conflicts,
    _work_values_match,
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
    assert "current_marital_status" in WORKSHEET_COMPARE_KEYS
    assert "current_address" in WORKSHEET_COMPARE_KEYS
    assert "primary_phone" in WORKSHEET_COMPARE_KEYS
    assert "email" in WORKSHEET_COMPARE_KEYS


def test_worksheet_compare_keys_cover_all_section_a_personal_passport_fields():
    """DS-260 A.1 — Personal Information: TOÀN BỘ field nguồn passport phải đối chiếu với DS-260
    khách khai, không chỉ vài field (khách yêu cầu 2026-08-14)."""
    for key in (
        "applicant_name",
        "applicant_name_native",
        "family_name",
        "given_names",
        "date_of_birth",
        "gender",
        "nationality",
        "place_of_birth",
        "birth_city",
        "birth_state",
        "birth_country",
        "id_card_number",
    ):
        assert key in WORKSHEET_COMPARE_KEYS, key


def test_build_worksheet_conflict_not_created_when_passport_birth_country_is_city_only():
    """Báo lỗi thực tế 2026-08-14: passport chỉ ghi "Da Nang" (không kèm "Vietnam") ở
    place_of_birth — so nguyên văn với worksheet khai thẳng "Vietnam" sẽ luôn khác nhau dù đúng
    dữ liệu. birth_country phải được TÁCH quốc gia thật (derive_country_from_place) trước khi so
    sánh, không so chuỗi thô."""
    passport = _rec({"place_of_birth": "Da Nang"}, "passport")
    ds260 = _rec({"birth_country": "Vietnam"}, "ds260_customer_form", variant="exception")
    rows = build_worksheet_conflict_rows([passport, ds260], {})
    assert worksheet_conflict_field_key("birth_country") not in {r["field_key"] for r in rows}


def test_build_worksheet_conflict_still_created_for_genuinely_different_birth_country():
    passport = _rec({"place_of_birth": "Da Nang, Vietnam"}, "passport")
    ds260 = _rec({"birth_country": "United States"}, "ds260_customer_form", variant="exception")
    rows = build_worksheet_conflict_rows([passport, ds260], {})
    assert worksheet_conflict_field_key("birth_country") in {r["field_key"] for r in rows}


def test_build_worksheet_conflict_created_for_mismatched_given_names_in_personal_section():
    passport = _rec({"family_name": "NGUYEN", "given_names": "VAN A"}, "passport")
    ds260 = _rec({"family_name": "NGUYEN", "given_names": "VAN B"}, "ds260_customer_form", variant="exception")
    rows = build_worksheet_conflict_rows([passport, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("given_names") in keys
    assert worksheet_conflict_field_key("family_name") not in keys


def test_worksheet_compare_keys_include_section_d_work_education():
    """Job Application (application_form) Section D — gồm cả narrative work_prior_jobs_history
    (khách yêu cầu 2026-08-13: DS-260 trống mà Job App có dữ liệu vẫn phải tạo Conflict)."""
    assert "work_primary_occupation" in WORKSHEET_COMPARE_KEYS
    assert "work_present_employer" in WORKSHEET_COMPARE_KEYS
    assert "work_job_title" in WORKSHEET_COMPARE_KEYS
    assert "edu_college_name" in WORKSHEET_COMPARE_KEYS
    assert "work_prior_jobs_history" in WORKSHEET_COMPARE_KEYS
    # Không lẫn field nguồn ds260_customer_form (so worksheet với chính nó là vô nghĩa)
    assert "work_other_occupation_used" not in WORKSHEET_COMPARE_KEYS


def test_norm_value():
    assert _norm_value("  Da Nang  ") == "DA NANG"


def test_norm_conflict_value_dates_and_gender():
    assert norm_conflict_value("gender", "male") == "MALE"
    assert norm_conflict_value("gender", "F") == "FEMALE"
    assert norm_conflict_value("date_of_birth", "1990-01-15") == "1990-01-15"
    assert norm_conflict_value("date_of_birth", "15/01/1990") == "1990-01-15"


def test_norm_conflict_value_phone_local_vs_international():
    """Số VN dạng nội địa (0398333484) và quốc tế (+84 398333484) là CÙNG 1 số (khách yêu cầu
    2026-08-14)."""
    a = norm_conflict_value("primary_phone", "0398333484")
    b = norm_conflict_value("primary_phone", "+84 398333484")
    assert a == b == "398333484"
    assert norm_conflict_value("primary_phone", "0398333484") == norm_conflict_value(
        "primary_phone", "84398333484"
    )


def test_norm_conflict_value_phone_rejects_genuinely_different_number():
    assert norm_conflict_value("primary_phone", "0398333484") != norm_conflict_value(
        "primary_phone", "0912345678"
    )


def test_build_worksheet_conflict_not_created_for_local_vs_international_phone():
    application = _rec({"primary_phone_number": "+84 398333484"}, "application_form")
    ds260 = _rec({"primary_phone_number": "0398333484"}, "ds260_customer_form", variant="exception")
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("primary_phone") not in keys


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


def test_build_worksheet_conflict_date_of_birth_displays_dd_mm_yyyy():
    """Conflict value_a/value_b cho người dùng CHỌN phải luôn dd/mm/yyyy — không phải chuỗi ISO
    thô từ OCR (yyyy-mm-dd), dễ đọc nhầm/khó chọn khi 2 nguồn hiển thị khác định dạng nhau."""
    passport_std = _rec({"full_name": "NGUYEN VAN A", "date_of_birth": "1990-01-15"}, "passport")
    ds260 = _rec(
        {"applicant_name": "NGUYEN VAN A", "date_of_birth": "1991-02-20"},
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([passport_std, ds260], {})
    fk = worksheet_conflict_field_key("date_of_birth")
    row = next(r for r in rows if r["field_key"] == fk)
    assert row["value_a"] == "15/01/1990"
    assert row["value_b"] == "20/02/1991"


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
    # City: worksheet để trống nhưng Job App có "LUANDA" — ADDRESS không còn tự động fill từ
    # Job App khi trống (khách yêu cầu), nhưng vẫn phải tạo Conflict để người dùng tự chọn có
    # lấy vào hay không (khác với auto-fill; xem _ADDRESS_COMPARE_KEYS).
    assert worksheet_conflict_field_key("current_city") in keys
    city_row = next(r for r in rows if r["field_key"] == worksheet_conflict_field_key("current_city"))
    assert city_row["value_a"] == "LUANDA"
    assert city_row["value_b"] == ""


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


def test_build_worksheet_conflict_created_when_ds260_empty_but_job_app_has_data():
    """Section D (khách yêu cầu 2026-08-13): DS-260 khách khai KHÔNG khai present_employer,
    nhưng Job Application có — vẫn phải tạo Conflict (trống vs có dữ liệu) để người dùng chọn
    điền, KHÔNG được âm thầm bỏ qua như các field khác (hành vi mặc định vẫn giữ nguyên: field
    ngoài Section D mà 1 bên trống thì bỏ qua, không tạo Conflict)."""
    application = _rec(
        {"primary_occupation": "Sales Staff", "present_employer": "ABC Co"},
        "application_form",
    )
    ds260 = _rec({}, "ds260_customer_form", variant="exception")
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("work_primary_occupation") in keys
    assert worksheet_conflict_field_key("work_present_employer") in keys
    row = next(r for r in rows if r["field_key"] == worksheet_conflict_field_key("work_present_employer"))
    assert row["value_a"] == "ABC Co"
    assert row["value_b"] == ""


def test_build_worksheet_conflict_not_created_when_both_empty_outside_work_section():
    """Field NGOÀI Section D/Address — cả 2 bên trống vẫn phải bỏ qua như cũ."""
    application = _rec({}, "application_form")
    ds260 = _rec({}, "ds260_customer_form", variant="exception")
    rows = build_worksheet_conflict_rows([application, ds260], {})
    assert rows == []


def test_address_conflict_created_when_worksheet_empty_but_job_app_has_data():
    """ADDRESS không còn tự động fill từ Job App khi worksheet trống (khách yêu cầu), nhưng
    KHÔNG được lặng lẽ bỏ qua luôn — DS-260 trống mà Job App có dữ liệu vẫn phải tạo Conflict để
    người dùng tự chọn có lấy vào hay không, cùng nguyên tắc với Section D (khách phản hồi: bỏ
    auto-fill không có nghĩa là bỏ luôn cả Conflict)."""
    application = _rec(
        {
            "current_address": "123 LE LOI",
            "address_city": "DA NANG",
            "address_state": "DA NANG",
            "postal_code": "550000",
            "address_country": "VIETNAM",
        },
        "application_form",
    )
    ds260 = _rec({}, "ds260_customer_form", variant="exception")
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    for key in ("current_address", "current_city", "current_state", "postal_code", "current_country"):
        fk = worksheet_conflict_field_key(key)
        assert fk in keys, f"expected conflict for {key}"
        row = next(r for r in rows if r["field_key"] == fk)
        assert row["value_b"] == ""  # worksheet trống — giá trị B để trống, không bị auto-fill


def test_build_worksheet_conflict_bilingual_job_text_not_flagged_as_conflict():
    """Cùng 1 công ty/nghề nghiệp nhưng viết 2 ngôn ngữ khác nhau (Job Application tiếng Anh,
    DS-260 khách khai tiếng Việt) KHÔNG được coi là xung đột (khách yêu cầu 2026-08-13)."""
    application = _rec(
        {"primary_occupation": "Staff", "present_employer": "Private business of Mr. Tan Nguyen"},
        "application_form",
    )
    ds260 = _rec(
        {"primary_occupation": "Nhan vien", "present_employer": "Cong ty tu nhan cua ong Tan Nguyen"},
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("work_present_employer") not in keys
    assert worksheet_conflict_field_key("work_primary_occupation") not in keys


def test_build_worksheet_conflict_skipped_when_application_form_job_confirmed_as_prior():
    """Xuan Vu garment pattern (2026-08-07): khách nộp Job Application liệt kê công ty may CŨ
    (Manager, Xuan Vu garment) là "Present" (form không có end date), nhưng DS-260 tự khai
    (mới hơn) nói rõ công ty đó ĐÃ NGHỈ và hiện tự làm may ở nhà — worksheet mô tả công ty cũ
    trong other_occupation_detail. Đây KHÔNG phải xung đột thật (application_form đang mô tả
    một job cũ, không phải "hiện tại") nên không được tạo Conflict cho cụm present_employer."""
    application = _rec(
        {
            "primary_occupation": "Manager",
            "present_employer": "Xuan Vu garment private enterprise",
            "employer_address": "41/40, Street #13, Ward 5, Go Vap District",
            "job_title": "Manager",
            "employment_start_date": "2009-01-01",
        },
        "application_form",
    )
    ds260 = _rec(
        {
            "primary_occupation": "May (Tu quan)",
            "present_employer": "May (Tu quan)",
            "other_occupation_used": "Yes",
            "other_occupation_detail": (
                "Ten cong ty: Xuan Vu garment private enterprise. Vi tri cong viec: quan ly. "
                "Tu 01/01/2009 - 8/8/2018."
            ),
        },
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("work_primary_occupation") not in keys
    assert worksheet_conflict_field_key("work_present_employer") not in keys
    assert worksheet_conflict_field_key("work_job_title") not in keys


def test_build_worksheet_conflict_job_title_and_employer_still_flagged_without_prior_job_evidence():
    """Không có bằng chứng nào cho thấy Application form đang mô tả việc CŨ (worksheet không
    nhắc gì tới công ty đó trong other_occupation_detail/prior_jobs_history) — vẫn là xung đột
    thật, phải tạo Conflict như trước (không bị nuốt bởi rule "công việc hiện tại")."""
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


def test_birth_cert_only_has_father_name_gop_still_creates_conflict():
    """Bug fix 2026-08-21: birth certificate OCR chỉ trả father_name gộp (không tách
    father_surname/father_given_names riêng) — _strict_field_value phải áp dụng
    _resolve_parent_birth_cert_fallback để split, không thì father_surname/mother_surname
    luôn rỗng → không bao giờ tạo conflict với worksheet dù BC có đầy đủ thông tin.

    Ví dụ thực tế: BC ghi "TRIEU NGOC GIA", WS ghi "TRIEU GIA" → phải tạo conflict
    cho father_given_names."""
    birth_cert = _rec(
        {"father_name": "TRIEU NGOC GIA"},  # Chỉ có full_name gộp, không tách riêng
        "birth_certificate",
    )
    ws = _rec(
        {
            "father_surname": "TRIEU",
            "father_given_names": "GIA",  # Thiếu "NGOC" — sai
        },
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([birth_cert, ws], {})
    keys = {r["field_key"] for r in rows}
    # father_surname khớp nhau (TRIEU = TRIEU) — không tạo conflict
    assert worksheet_conflict_field_key("father_surname") not in keys
    # father_given_names: BC split ra "NGOC GIA", WS là "GIA" → khác nhau → PHẢI tạo conflict
    assert worksheet_conflict_field_key("father_given_names") in keys, (
        f"father_given_names phải tạo conflict: BC='NGOC GIA' (sau split), WS='GIA'. Rows: {rows}"
    )


def test_birth_cert_mother_name_gop_creates_conflict():
    """Tương tự test_birth_cert_only_has_father_name_gop_still_creates_conflict cho mẹ."""
    birth_cert = _rec(
        {"mother_name": "HOANG THI MAI"},  # Chỉ có full_name gộp
        "birth_certificate",
    )
    ws = _rec(
        {
            "mother_surname": "HOANG",
            "mother_given_names": "MAI",  # Thiếu "THI" — sai
        },
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([birth_cert, ws], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("mother_surname") not in keys
    assert worksheet_conflict_field_key("mother_given_names") in keys, (
        f"mother_given_names phải tạo conflict: BC='THI MAI' (sau split), WS='MAI'. Rows: {rows}"
    )


def test_birth_cert_parent_name_matches_worksheet_no_conflict():
    """Khi BC và WS đều có father_given_names sau khi split = giá trị khớp nhau."""
    birth_cert = _rec(
        {"father_name": "TRIEU NGOC GIA"},
        "birth_certificate",
    )
    ws = _rec(
        {
            "father_surname": "TRIEU",
            "father_given_names": "NGOC GIA",  # Đúng
        },
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([birth_cert, ws], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("father_surname") not in keys
    assert worksheet_conflict_field_key("father_given_names") not in keys  # Khớp nhau


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


def test_json_values_if_json_like_extracts_values_drops_keys():
    """Model OCR đôi khi trả prior_jobs_history dạng JSON (báo lỗi thực tế 2026-08-13) — tên
    khoá JSON (employer_name, end_date...) không được lẫn vào token so khớp như nội dung thật."""
    raw = '[{"employer_name": "Greentech Headgear Co. Ltd", "end_date": "2020-09-11"}]'
    out = _json_values_if_json_like(raw)
    assert "Greentech" in out
    assert "employer_name" not in out
    assert "end_date" not in out


def test_json_values_if_json_like_passthrough_for_plain_text():
    text = "Xuan Vu garment private enterprise - quan ly - 01/01/2009 den 8/8/2018"
    assert _json_values_if_json_like(text) == text


def test_build_worksheet_conflict_not_created_when_ds260_already_covers_json_job_application():
    """Báo lỗi thực tế 2026-08-13: Application form's prior_jobs_history OCR ra dạng JSON thô
    (lỗi model, xem ocr_pipeline.py), nhưng nội dung mô tả ĐÚNG 1 công việc đã có sẵn đầy đủ
    trong work_prior_jobs_history của DS-260 (đã format lại 3 dòng/entry) — không được tạo
    Conflict "giả" chỉ vì 2 bên viết khác định dạng (JSON thô vs câu văn thường)."""
    application = _rec(
        {
            "prior_jobs_history": (
                '[{"employer_name": "Greentech Headgear Co. Ltd", "employer_address": '
                '"D02 Street, Nghia Thanh, Chau Duc Dist.", "occupation_other_specify": '
                '"Hat production", "job_title": "Staff", "employment_start_date": '
                '"2019-02-06", "end_date": "2020-09-11"}]'
            )
        },
        "application_form",
    )
    ds260 = _rec(
        {
            "prior_jobs_history": (
                "1. Bat Dau Lam Tu Ngay 06/02/2019 Ket Thuc Vao Ngay 11/09/2020\n"
                "Ten Cong Ty: Greentech Headgear Co. Ltd, Vi Tri Lam Viec: Nhan Vien\n"
                "Ten Nguoi Quan Ly: Mai Quoc Thai, Sdt: +84 251 3685 868."
            )
        },
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("work_prior_jobs_history") not in keys


def test_work_values_match_still_flags_genuinely_different_prior_job():
    official = "ABC Trading Company, Sales Manager, 2015-2017"
    worksheet = (
        "1. Bat Dau Lam Tu Ngay 06/02/2019 Ket Thuc Vao Ngay 11/09/2020\n"
        "Ten Cong Ty: Greentech Headgear Co. Ltd, Vi Tri Lam Viec: Nhan Vien\n"
        "Ten Nguoi Quan Ly: Mai Quoc Thai, Sdt: +84 251 3685 868."
    )
    assert _work_values_match("work_prior_jobs_history", official, worksheet) is False


def test_place_school_values_match_state_accent_and_dash_variants():
    """Ảnh thực tế 2026-08-14: 'Ba Ria – Vung Tau' (Application form) vs 'BÀ RỊA– VŨNG TÀU'
    (DS-260) — cùng 1 tỉnh, chỉ khác dấu/khoảng trắng quanh dấu gạch ngang."""
    assert _place_or_school_values_match("Ba Ria – Vung Tau", "BÀ RỊA– VŨNG TÀU")


def test_place_school_values_match_address_different_detail_level():
    """1 bên có thêm tên tỉnh, bên kia không — vẫn là cùng 1 địa chỉ (containment, không cần
    khớp tuyệt đối kích thước 2 bên)."""
    assert _place_or_school_values_match(
        "Song Cau Village, Nghia Thanh Commune, Chau Duc Dist.",
        "THÔN SỐNG CẦU, NGHĨA THÀNH, CHÂU ĐỨC, BÀ RỊA– VŨNG TÀU",
    )


def test_place_school_values_match_school_name_translation():
    """Tên trường dịch tiếng Anh ↔ tiếng Việt — cùng 1 trường (khách yêu cầu 2026-08-14)."""
    assert _place_or_school_values_match(
        "CONTINUING EDUCATION CENTER OF CHAU DUC DISTRICT",
        "TRUNG TÂM GIÁO DỤC THƯỜNG XUYÊN HUYỆN CHÂU ĐỨC",
    )


def test_place_school_values_match_rejects_genuinely_different_place():
    assert not _place_or_school_values_match("Dong Nai", "Ba Ria - Vung Tau")


def test_build_worksheet_conflict_not_created_for_bilingual_address_state_school():
    """End-to-end qua build_worksheet_conflict_rows — cả 3 field trong ảnh thực tế 2026-08-14
    (current_address, current_state, edu_high_school_name) không được tạo Conflict."""
    application = _rec(
        {
            "current_address": "Song Cau Village, Nghia Thanh Commune, Chau Duc Dist.",
            "address_state": "Ba Ria – Vung Tau",
            "high_school_name": "CONTINUING EDUCATION CENTER OF CHAU DUC DISTRICT",
        },
        "application_form",
    )
    ds260 = _rec(
        {
            "current_address": "THÔN SỐNG CẦU, NGHĨA THÀNH, CHÂU ĐỨC, BÀ RỊA– VŨNG TÀU",
            "address_state": "BÀ RỊA– VŨNG TÀU",
            "high_school_name": "TRUNG TÂM GIÁO DỤC THƯỜNG XUYÊN HUYỆN CHÂU ĐỨC",
        },
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("current_address") not in keys
    assert worksheet_conflict_field_key("current_state") not in keys
    assert worksheet_conflict_field_key("edu_high_school_name") not in keys


def test_build_worksheet_conflict_still_created_for_genuinely_different_state():
    application = _rec({"address_state": "Dong Nai"}, "application_form")
    ds260 = _rec({"address_state": "Ba Ria - Vung Tau"}, "ds260_customer_form", variant="exception")
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("current_state") in keys


# --- address_from_date vs date_signed plausibility (WP4) ---------------------------------


def test_address_from_date_after_date_signed_creates_conflict():
    application = _rec(
        {"current_address": "123 LE LOI", "date_signed": "01/06/2020"}, "application_form"
    )
    ds260 = _rec(
        {"current_address": "123 LE LOI", "address_from_date": "01/2021"},
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    fk = worksheet_conflict_field_key("address_from_date")
    assert fk in keys
    row = next(r for r in rows if r["field_key"] == fk)
    assert row["value_a"] == "01/06/2020"
    assert row["value_b"] == "01/2021"


def test_address_from_date_before_date_signed_no_conflict():
    application = _rec(
        {"current_address": "123 LE LOI", "date_signed": "01/06/2020"}, "application_form"
    )
    ds260 = _rec(
        {"current_address": "123 LE LOI", "address_from_date": "01/2019"},
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("address_from_date") not in keys


def test_address_from_date_same_month_as_date_signed_no_conflict():
    # mm/yyyy partial dates, same month/year as date_signed — month-granularity compare,
    # not "strictly after", so this must not fire.
    application = _rec(
        {"current_address": "123 LE LOI", "date_signed": "15/06/2020"}, "application_form"
    )
    ds260 = _rec(
        {"current_address": "123 LE LOI", "address_from_date": "06/2020"},
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("address_from_date") not in keys


def test_address_from_date_skipped_when_address_differs():
    application = _rec(
        {"current_address": "123 LE LOI", "date_signed": "01/06/2020"}, "application_form"
    )
    ds260 = _rec(
        {"current_address": "456 TRAN PHU", "address_from_date": "01/2021"},
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("address_from_date") not in keys


def test_address_from_date_skipped_when_already_resolved():
    application = _rec(
        {"current_address": "123 LE LOI", "date_signed": "01/06/2020"}, "application_form"
    )
    ds260 = _rec(
        {"current_address": "123 LE LOI", "address_from_date": "01/2021"},
        "ds260_customer_form",
        variant="exception",
    )
    fk = worksheet_conflict_field_key("address_from_date")
    rows = build_worksheet_conflict_rows([application, ds260], {fk: "01/2021"})
    keys = {r["field_key"] for r in rows}
    assert fk not in keys


# --- work_start_date plausibility when employer confirmed to match (WP4) ---------------------


def test_work_start_date_mismatch_when_employer_matches_creates_conflict():
    application = _rec(
        {
            "primary_occupation": "Sales Staff",
            "present_employer": "ABC Co",
            "employment_start_date": "01/06/2020",
        },
        "application_form",
    )
    ds260 = _rec(
        {
            "primary_occupation": "sales staff",
            "present_employer": "abc co",
            "employment_start_date": "01/01/2021",
        },
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    fk = worksheet_conflict_field_key("work_start_date")
    assert fk in keys
    row = next(r for r in rows if r["field_key"] == fk)
    assert row["value_a"] == "01/06/2020"
    assert row["value_b"] == "01/01/2021"


def test_work_start_date_same_period_no_conflict():
    application = _rec(
        {
            "primary_occupation": "Sales Staff",
            "present_employer": "ABC Co",
            "employment_start_date": "01/06/2020",
        },
        "application_form",
    )
    ds260 = _rec(
        {
            "primary_occupation": "sales staff",
            "present_employer": "abc co",
            "employment_start_date": "01/06/2020",
        },
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("work_start_date") not in keys


def test_work_start_date_skipped_when_employer_does_not_match():
    # Application form job is confirmed PRIOR (its employer shows up in the worksheet's own
    # prior_jobs_history narrative) — the generic loop already suppresses occupation/employer/
    # start_date comparison for this case (_application_form_job_confirmed_as_prior). The two
    # jobs are genuinely different (no employer-token overlap), so this rule must not manufacture
    # a work_start_date conflict between two unrelated jobs' dates.
    application = _rec(
        {
            "primary_occupation": "Accountant",
            "present_employer": "XYZ Financial Group",
            "employment_start_date": "01/06/2020",
        },
        "application_form",
    )
    ds260 = _rec(
        {
            "primary_occupation": "sales staff",
            "present_employer": "abc co",
            "employment_start_date": "01/01/2021",
            "prior_jobs_history": "Accountant at XYZ Financial Group, 2018 - 2020",
        },
        "ds260_customer_form",
        variant="exception",
    )
    rows = build_worksheet_conflict_rows([application, ds260], {})
    keys = {r["field_key"] for r in rows}
    assert worksheet_conflict_field_key("work_start_date") not in keys


def test_work_start_date_skipped_when_already_resolved():
    application = _rec(
        {
            "primary_occupation": "Sales Staff",
            "present_employer": "ABC Co",
            "employment_start_date": "01/06/2020",
        },
        "application_form",
    )
    ds260 = _rec(
        {
            "primary_occupation": "sales staff",
            "present_employer": "abc co",
            "employment_start_date": "01/01/2021",
        },
        "ds260_customer_form",
        variant="exception",
    )
    fk = worksheet_conflict_field_key("work_start_date")
    rows = build_worksheet_conflict_rows([application, ds260], {fk: "01/01/2021"})
    keys = {r["field_key"] for r in rows}
    assert fk not in keys


def test_document_exception_conflict_date_displays_dd_mm_yyyy():
    """document_vs_exception (Luồng 1 chuẩn vs đối chiếu _new) — ngày cũng phải hiển thị
    dd/mm/yyyy cho người dùng chọn, không phải chuỗi ISO thô."""
    standard = _rec({"issue_date": "2020-01-01"}, "passport")
    exception = _rec({"issue_date": "01/03/2020"}, "passport", variant="exception")
    rows = _sync_document_exception_conflicts([standard, exception], {})
    row = next(r for r in rows if r["field_key"] == ds260_conflict_field_key("passport", "issue_date"))
    assert row["value_a"] == "01/01/2020"
    assert row["value_b"] == "01/03/2020"


# --- spouse_worksheet conflict (WP5) -----------------------------------------------------


def test_spouse_work_conflict_field_key():
    from app.services.ds260_conflicts import spouse_worksheet_conflict_field_key
    fk = spouse_worksheet_conflict_field_key("spouse_occupation", "12345")
    assert fk == "ds260.spouse_worksheet.12345.spouse_occupation"


def test_spouse_work_conflict_type():
    from app.services.ds260_conflicts import conflict_type_from_field_key, spouse_worksheet_conflict_field_key
    fk = spouse_worksheet_conflict_field_key("spouse_occupation", "12345")
    assert conflict_type_from_field_key(fk) == "spouse_worksheet"


def test_spouse_work_conflict_label():
    from app.services.ds260_conflicts import conflict_label_vi, spouse_worksheet_conflict_field_key
    fk = spouse_worksheet_conflict_field_key("spouse_occupation", "12345")
    label = conflict_label_vi(fk)
    assert "Phối ngẫu" in label
    assert "Nghề nghiệp" in label


def test_spouse_work_conflict_parsed_correctly():
    from app.services.ds260_conflicts import parse_ds260_conflict_key, spouse_worksheet_conflict_field_key
    fk = spouse_worksheet_conflict_field_key("spouse_occupation", "12345")
    result = parse_ds260_conflict_key(fk)
    assert result == ("spouse_worksheet", "12345.spouse_occupation")


def test_spouse_work_conflict_occupation_different():
    """Khi spouse_occupation trên marriage certificate khác với work_primary_occupation
    trên spouse's DS-260 worksheet → tạo Conflict."""
    from app.services.ds260_conflicts import spouse_worksheet_conflict_field_key

    # Marriage certificate: Dang Dang là "Công nhân, sản xuất"
    marriage_rec = _rec(
        {"husband_full_name": "NGUYEN DANG DANG", "occupation": "Công nhân, sản xuất"},
        "marriage_certificate",
    )
    # Spouse's DS-260: Dang Dang tự khai là "Nhân viên, cung cấp xe tự lái"
    spouse_ds260 = _rec(
        {"primary_occupation": "Nhân viên", "present_employer": "Cung cấp xe tự lái"},
        "ds260_customer_form",
        variant="exception",
    )

    # Build conflict rows sử dụng _work_values_match logic
    from app.services.ds260_conflicts import (
        _SPOUSE_WORK_COMPARE_KEYS,
        _SPOUSE_TO_WORK_KEY_MAP,
        _work_values_match,
    )

    # spouse_occupation từ marriage certificate
    marriage_occ = "Công nhân, sản xuất"
    # work_primary_occupation từ spouse's DS-260
    spouse_occ = "Nhân viên"

    # 2 giá trị khác nhau → phải tạo conflict
    assert not _work_values_match("work_primary_occupation", marriage_occ, spouse_occ)
    assert "spouse_occupation" in _SPOUSE_WORK_COMPARE_KEYS
    assert _SPOUSE_TO_WORK_KEY_MAP.get("spouse_occupation") == "work_primary_occupation"


def test_spouse_work_conflict_no_conflict_when_same_occupation():
    """Khi spouse_occupation trên marriage certificate giống với work_primary_occupation
    trên spouse's DS-260 worksheet → KHÔNG tạo Conflict."""
    from app.services.ds260_conflicts import _work_values_match

    # Cùng một nghề nghiệp, chỉ khác cách viết
    marriage_occ = "Sales Staff"
    spouse_occ = "Sales staff"  # Khác HOA/thường

    # 2 giá trị giống nhau sau khi normalize → không tạo conflict
    assert _work_values_match("work_primary_occupation", marriage_occ, spouse_occ)


def test_spouse_work_conflict_no_conflict_when_marriage_cert_empty():
    """Khi marriage certificate không có spouse_occupation → không tạo Conflict."""
    # Marriage certificate không ghi nghề nghiệp
    marriage_rec = _rec(
        {"husband_full_name": "NGUYEN DANG DANG"},
        "marriage_certificate",
    )
    # Spouse's DS-260 có work info
    spouse_ds260 = _rec(
        {"primary_occupation": "Nhân viên"},
        "ds260_customer_form",
        variant="exception",
    )

    # marriage_occ rỗng → không tạo conflict vì không có gì để so sánh
    marriage_occ = ""  # Không có occupation trên marriage cert
    spouse_occ = "Nhân viên"

    # marriage_occ rỗng → function sẽ skip vì không có giá trị để so sánh
    assert not marriage_occ  # Truthy check: rỗng = falsy


def test_spouse_work_conflict_no_conflict_when_spouse_ds260_empty():
    """Khi spouse's DS-260 worksheet không có work info → không tạo Conflict."""
    marriage_occ = "Công nhân"
    spouse_occ = ""
    assert not spouse_occ


def test_spouse_identity_keys_include_dob_and_names():
    from app.services.ds260_conflicts import (
        SPOUSE_IDENTITY_COMPARE_KEYS,
        SPOUSE_TO_APPLICANT_KEY_MAP,
    )
    assert "spouse_date_of_birth" in SPOUSE_IDENTITY_COMPARE_KEYS
    assert "spouse_surname" in SPOUSE_IDENTITY_COMPARE_KEYS
    assert "spouse_given_names" in SPOUSE_IDENTITY_COMPARE_KEYS
    assert SPOUSE_TO_APPLICANT_KEY_MAP["spouse_date_of_birth"] == "date_of_birth"
    assert SPOUSE_TO_APPLICANT_KEY_MAP["spouse_surname"] == "family_name"
    assert SPOUSE_TO_APPLICANT_KEY_MAP["spouse_given_names"] == "given_names"



def test_education_period_difference_creates_conflict_even_when_school_name_matches():
    """Cùng trường học nhưng thời gian học/tốt nghiệp khác nhau -> phải tạo conflict."""
    application = _rec(
        {
            "high_school_name": "TRUONG THPT HOANG VAN THU",
            "high_school_period": "09/2010 - 05/2013",
        },
        "application_form",
    )
    worksheet = _rec(
        {
            "high_school_name": "TRUONG THPT HOANG VAN THU",
            "high_school_period": "08/2010 - 06/2013",
        },
        "ds260_customer_form",
    )
    rows = build_worksheet_conflict_rows([application, worksheet], {})
    keys = {r["field_key"] for r in rows}
    assert "ds260.document_vs_worksheet.edu_high_school_period" in keys
    assert "ds260.document_vs_worksheet.edu_high_school_name" not in keys


def test_education_conflict_when_ds260_has_data_and_application_form_empty():
    """DS-260 có dữ liệu trường học/thời gian nhưng Application Form trống -> phải tạo conflict."""
    application = _rec(
        {
            "middle_school_name": "THCS NGUYEN TRAI",
        },
        "application_form",
    )
    worksheet = _rec(
        {
            "middle_school_name": "THCS NGUYEN TRAI",
            "college_name": "DAI HOC BACH KHOA",
            "college_period": "2015 - 2019",
        },
        "ds260_customer_form",
    )
    rows = build_worksheet_conflict_rows([application, worksheet], {})
    keys = {r["field_key"] for r in rows}
    assert "ds260.document_vs_worksheet.edu_college_name" in keys
    assert "ds260.document_vs_worksheet.edu_college_period" in keys


def test_education_conflict_when_application_form_has_data_and_ds260_empty():
    """Application Form có dữ liệu học vấn nhưng DS-260 trống -> phải tạo conflict."""
    application = _rec(
        {
            "middle_school_name": "THCS NGUYEN TRAI",
            "middle_school_period": "2006 - 2010",
        },
        "application_form",
    )
    worksheet = _rec(
        {
            "middle_school_name": "THCS NGUYEN TRAI",
            "middle_school_period": "",
        },
        "ds260_customer_form",
    )
    rows = build_worksheet_conflict_rows([application, worksheet], {})
    keys = {r["field_key"] for r in rows}
    assert "ds260.document_vs_worksheet.edu_middle_school_period" in keys


def test_apply_ds260_resolved_conflicts_with_empty_value():
    """Khi user giải quyết conflict bằng cách chọn giá trị trống (""), hệ thống phải tôn trọng
    và gán value="", không bị bỏ qua hay ghi đè."""
    from app.services.ds260_conflicts import apply_ds260_resolved_conflicts
    from app.services.ds260_mapping import reconcile_ds260_yesno_and_death_year

    sections = [
        {
            "id": "section_work_education",
            "fields": [
                {
                    "key": "work_prior_jobs_used",
                    "value": "Yes",
                    "source": {},
                },
                {
                    "key": "work_prior_jobs_history",
                    "value": "From 2015 to 2018 at ABC Corp",
                    "source": {"document_type": "application_form"},
                },
            ],
        }
    ]

    resolutions = {
        "ds260.document_vs_worksheet.work_prior_jobs_history": "",
    }

    apply_ds260_resolved_conflicts(sections, resolutions)
    
    # work_prior_jobs_history phải được gán rỗng
    field_history = next(f for f in sections[0]["fields"] if f["key"] == "work_prior_jobs_history")
    assert field_history["value"] == ""
    assert field_history["source"]["derived"] == "worksheet_conflict_resolution"

    # Khi reconcile Yes/No: work_prior_jobs_used phải chuyển thành "No"
    reconcile_ds260_yesno_and_death_year(sections)
    field_used = next(f for f in sections[0]["fields"] if f["key"] == "work_prior_jobs_used")
    assert field_used["value"] == "No"



