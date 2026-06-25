"""DS-260 English output normalization."""

from app.services.ds260_english_output import format_ds260_field_value, format_sections_english_output


def test_vietnamese_name_to_ascii_uppercase():
    assert format_ds260_field_value("applicant_name", "Hồ Công Bảo Long") == "HO CONG BAO LONG"


def test_vietnamese_city_title_case():
    assert format_ds260_field_value("birth_city", "Đà Nẵng") == "Da Nang"
    assert format_ds260_field_value("birth_country", "Việt Nam") == "Vietnam"


def test_yes_no_and_gender():
    assert format_ds260_field_value("father_is_living", "Có") == "Yes"
    assert format_ds260_field_value("children_used", "Không") == "No"
    assert format_ds260_field_value("gender", "Nữ") == "Female"


def test_sections_english_output_batch():
    sections = [
        {
            "id": "section_a_personal",
            "fields": [
                {"key": "applicant_name", "value": "Nguyễn Văn A"},
                {"key": "nationality", "value": "VIỆT NAM"},
            ],
        }
    ]
    format_sections_english_output(sections)
    assert sections[0]["fields"][0]["value"] == "NGUYEN VAN A"
    assert sections[0]["fields"][1]["value"] == "Vietnamese"
