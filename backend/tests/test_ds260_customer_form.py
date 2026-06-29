"""DS-260 customer worksheet (ds260.pdf) → doc record → form fill."""

import json
from types import SimpleNamespace
from uuid import uuid4

from app.services.document_registry import (
    RECORDABLE_DOC_TYPES,
    parse_document_filename,
)
from app.services.ds260_mapping import (
    enrich_empty_fields_from_all_doc_records,
    flatten_ds260_mappings,
    resolve_customer_form_field,
)


def test_parse_ds260_filename():
    assert parse_document_filename("ds260.pdf") == ("ds260_customer_form", True)
    assert parse_document_filename("DS260_new.pdf") == ("ds260_customer_form", True)
    assert parse_document_filename("my ds-260 form.pdf") == ("ds260_customer_form", True)
    assert "ds260_customer_form" in RECORDABLE_DOC_TYPES


def test_name_header_noise_stripped():
    """OCR chữ tay lẫn tiêu đề 'DS 260' / 'KHACH KHAI' vào tên → phải bỏ."""
    from app.services.ds260_customer_keys import normalize_ds260_customer_raw

    out = normalize_ds260_customer_raw(
        {"applicant_name": "DS LE CONG PHONG", "family_name": "DS", "full_name": "DS LE CONG PHONG"}
    )
    assert out["applicant_name"] == "LE CONG PHONG"
    assert out["full_name"] == "LE CONG PHONG"
    assert out["family_name"] == ""
    assert normalize_ds260_customer_raw({"applicant_name": "KHACH KHAI DS260 TRAN MAN VY"})[
        "applicant_name"
    ] == "TRAN MAN VY"
    # Tên sạch không bị đụng.
    assert normalize_ds260_customer_raw({"applicant_name": "LE CONG PHONG"})["applicant_name"] == "LE CONG PHONG"


def test_vietnamese_school_levels_map_to_middle_and_high():
    """Cấp 2 = Trung học cơ sở (THCS); Cấp 3 = Trung học phổ thông (THPT)."""
    from app.services.ds260_customer_keys import normalize_ds260_customer_raw

    out = normalize_ds260_customer_raw(
        {
            "trung_hoc_co_so_name": "THCS Nguyen Du",
            "trung_hoc_co_so_period": "09/1990 - 05/1994",
            "thpt_name": "THPT Le Hong Phong",
            "thpt_period": "09/1994 - 05/1997",
        }
    )
    assert out["edu_middle_school_name"] == "THCS Nguyen Du"
    assert out["edu_middle_school_period"] == "09/1990 - 05/1994"
    assert out["edu_high_school_name"] == "THPT Le Hong Phong"
    assert out["edu_high_school_period"] == "09/1994 - 05/1997"


def _rec(raw: dict, *, variant: str = "exception") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        doc_type="ds260_customer_form",
        variant=variant,
        source_document_id=uuid4(),
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
        updated_at=None,
    )


def test_resolve_address_contact_social_from_ds260_customer_form():
    ref = _rec(
        {
            "current_address": "123 LE LOI",
            "address_city": "DA NANG",
            "address_state": "DA NANG",
            "address_country": "VIETNAM",
            "postal_code": "550000",
            "address_from_date": "2020-01-01",
            "other_addresses_since_16": "No",
            "primary_phone_number": "+84901234567",
            "email_address": "test@example.com",
            "social_media_platform": "Facebook",
            "social_media_identifier": "facebook.com/user",
        }
    )
    mappings = flatten_ds260_mappings()
    addr, _, _, _ = resolve_customer_form_field([ref], "ds260_customer_form", mappings["current_address"])
    phone, _, _, _ = resolve_customer_form_field([ref], "ds260_customer_form", mappings["primary_phone"])
    email, _, _, _ = resolve_customer_form_field([ref], "ds260_customer_form", mappings["email"])
    social, _, _, _ = resolve_customer_form_field(
        [ref], "ds260_customer_form", mappings["social_media_platform"]
    )
    assert addr == "123 LE LOI"
    assert phone == "+84901234567"
    assert email == "test@example.com"
    assert social == "Facebook"


def test_enrich_from_ds260_customer_form_record():
    ref = _rec(
        {
            "current_address": "456 TRAN PHU",
            "address_city": "HUE",
            "primary_phone_number": "+84901112233",
        }
    )
    sections = [
        {
            "id": "section_address",
            "fields": [
                {"key": "current_address", "value": "", "source": {}},
                {"key": "current_city", "value": "", "source": {}},
            ],
        },
        {
            "id": "section_contact",
            "fields": [{"key": "primary_phone", "value": "", "source": {}}],
        },
    ]
    enrich_empty_fields_from_all_doc_records(sections, [ref], {})
    assert sections[0]["fields"][0]["value"] == "456 TRAN PHU"
    assert sections[0]["fields"][1]["value"] == "HUE"
    assert sections[1]["fields"][0]["value"] == "+84901112233"
