"""Deterministic guards: birth-country cross-check + boilerplate Yes/No defaults."""

from app.services.export_ds260 import (
    _cross_check_birth_country,
    _normalize_birth_city_state,
    _normalize_vn_phone,
    _prepare_display_values,
)
from app.services.ds260_mapping import flatten_ds260_mappings


def test_vn_phone_gets_plus84():
    assert _normalize_vn_phone("0765930718") == "+84765930718"
    assert _normalize_vn_phone("0908427280") == "+84908427280"


def test_phone_already_international_or_na_unchanged():
    assert _normalize_vn_phone("+84 964 616 707") == "+84 964 616 707"
    assert _normalize_vn_phone("N/A") == "N/A"
    assert _normalize_vn_phone("") == ""


def test_municipality_birth_state_becomes_na():
    out = {"birth_city": "Can Tho", "birth_state": "Can Tho"}
    _normalize_birth_city_state(out)
    assert out["birth_state"] == "N/A"


def test_province_birth_state_unchanged():
    # Sinh ở tỉnh (không phải TP trực thuộc TW) → giữ nguyên State.
    out = {"birth_city": "N/A", "birth_state": "Ba Ria Vung Tau"}
    _normalize_birth_city_state(out)
    assert out["birth_state"] == "Ba Ria Vung Tau"


def test_prepare_display_values_phone_and_birthstate():
    out = _prepare_display_values(
        {"primary_phone": "0765930718", "birth_city": "Can Tho", "birth_state": "Can Tho"}
    )
    assert out["primary_phone"] == "+84765930718"
    assert out["birth_state"] == "N/A"


def test_vn_city_forces_vietnam_over_wrong_country():
    # Lỗi thực tế (Chiêm Ánh Hằng): birth_city='Can Tho' nhưng AI xuất birth_country='Canada'.
    out = {"birth_city": "Can Tho", "birth_country": "Canada"}
    _cross_check_birth_country(out)
    assert out["birth_country"] == "Vietnam"


def test_vn_state_forces_vietnam_when_country_blank():
    out = {"birth_state": "Ba Ria Vung Tau", "birth_country": ""}
    _cross_check_birth_country(out)
    assert out["birth_country"] == "Vietnam"


def test_parents_birth_country_guarded():
    out = {
        "father_birth_city": "Can Tho",
        "father_birth_country": "Canada",
        "mother_birth_state": "Thanh Hoa",
        "mother_birth_country": "",
    }
    _cross_check_birth_country(out)
    assert out["father_birth_country"] == "Vietnam"
    assert out["mother_birth_country"] == "Vietnam"


def test_foreign_birth_not_touched():
    # Sinh ở nước ngoài (không nhận diện địa danh VN) → KHÔNG ép Vietnam.
    out = {"birth_city": "Fresno", "birth_state": "California", "birth_country": "USA"}
    _cross_check_birth_country(out)
    assert out["birth_country"] == "USA"


def test_already_vietnam_unchanged():
    out = {"birth_city": "Can Tho", "birth_country": "Vietnam"}
    _cross_check_birth_country(out)
    assert out["birth_country"] == "Vietnam"


def test_guard_runs_in_prepare_display_values():
    out = _prepare_display_values({"birth_city": "Can Tho", "birth_country": "Canada"})
    assert out["birth_country"] == "Vietnam"


def test_boilerplate_defaults_present_in_schema():
    mappings = flatten_ds260_mappings()
    # Câu hỏi cố định phải có default để không bị bỏ trống khi AI đọc sót.
    assert mappings["been_in_us"].default is None
    assert mappings["issued_us_visa"].default is None
    assert mappings["refused_us_visa"].default is None
    assert mappings["other_languages_used"].default is None
    assert mappings["traveled_countries_5yr_used"].default is None
    assert mappings["arrested_convicted"].default == "No"
    assert mappings["public_charge"].default == "No"
    assert mappings["applied_ssn_before"].default == "No"
    assert mappings["want_ssn_issued"].default == "Yes"
    assert mappings["authorize_ssn_disclosure"].default == "Yes"
    assert mappings["has_vaccination_docs"].default == "Yes"


def test_unanswered_questions_stay_empty_when_not_declared():
    """other_languages_used, traveled_countries_5yr_used, issued_us_visa, refused_us_visa, been_in_us:
    nếu khách để trống không khai thì hệ thống cũng để trống, không tự động khai No.
    """
    from app.services.ds260_mapping import (
        apply_ds260_default_values,
        reconcile_ds260_yesno_and_death_year,
    )

    sections = [
        {
            "id": "section_test",
            "fields": [
                {"key": "other_languages_used", "value": "", "source": {}},
                {"key": "traveled_countries_5yr_used", "value": "", "source": {}},
                {"key": "issued_us_visa", "value": "", "source": {}},
                {"key": "refused_us_visa", "value": "", "source": {}},
                {"key": "been_in_us", "value": "", "source": {}},
            ],
        }
    ]

    apply_ds260_default_values(sections)
    reconcile_ds260_yesno_and_death_year(sections)

    by_key = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert by_key["other_languages_used"] == ""
    assert by_key["traveled_countries_5yr_used"] == ""
    assert by_key["issued_us_visa"] == ""
    assert by_key["refused_us_visa"] == ""
    assert by_key["been_in_us"] == ""



def test_date_format_dd_mm_yyyy():
    from app.services.ds260_dates import format_ds260_display_date
    assert format_ds260_display_date("1983-03-14") == "14/03/1983"
    assert format_ds260_display_date("14/03/1983") == "14/03/1983"
    assert format_ds260_display_date("2017-08-01") == "01/08/2017"
    # partial → mm/yyyy / năm
    assert format_ds260_display_date("2023-09") == "09/2023"
    assert format_ds260_display_date("1993") == "1993"


def test_name_uppercase_ascii_vs_native_with_diacritics():
    out = _prepare_display_values(
        {"applicant_name": "Nguyễn Văn A", "applicant_name_native": "Nguyễn Văn A"}
    )
    # Name (Last/Middle/First): IN HOA, KHÔNG dấu
    assert out["applicant_name"] == "NGUYEN VAN A"
    # Full Name in Native Language: IN HOA, CÓ dấu
    assert out["applicant_name_native"] == "NGUYỄN VĂN A"


def test_all_security_questions_default_no():
    mappings = flatten_ds260_mappings()
    for key in ("communicable_disease", "money_laundering", "terrorist_activities",
                "genocide", "visa_fraud", "removed_deported", "polygamy", "frivolous_asylum"):
        assert mappings[key].default == "No", key


def test_has_vaccination_docs_always_defaults_to_yes():
    """Câu hỏi Have vaccination documentation per U.S law? luôn luôn chọn Yes dù khách có khai No."""
    from app.services.ds260_mapping import apply_ds260_default_values

    # Trường hợp 1: Khách khai No -> vẫn ép thành Yes (default_value)
    sec_declared_no = [
        {
            "id": "section_security",
            "fields": [
                {"key": "has_vaccination_docs", "value": "No", "source": {"document_type": "ds260_customer_form"}},
            ],
        }
    ]
    apply_ds260_default_values(sec_declared_no)
    assert sec_declared_no[0]["fields"][0]["value"] == "Yes"
    assert sec_declared_no[0]["fields"][0]["source"]["derived"] == "default_value"

    # Trường hợp 2: Để trống -> thành Yes
    sec_empty = [
        {
            "id": "section_security",
            "fields": [
                {"key": "has_vaccination_docs", "value": "", "source": {}},
            ],
        }
    ]
    apply_ds260_default_values(sec_empty)
    assert sec_empty[0]["fields"][0]["value"] == "Yes"

    # Trường hợp 3: Manual override của user -> giữ nguyên
    sec_manual = [
        {
            "id": "section_security",
            "fields": [
                {"key": "has_vaccination_docs", "value": "No", "source": {"derived": "manual_override"}},
            ],
        }
    ]
    apply_ds260_default_values(sec_manual)
    assert sec_manual[0]["fields"][0]["value"] == "No"

