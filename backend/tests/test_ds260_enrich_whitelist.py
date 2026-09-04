"""FIELD_ALLOWED_DOCS — enrich must not cross-fill from unrelated doc types."""

import json
from types import SimpleNamespace
from uuid import uuid4

from app.services.ds260_mapping import (
    FIELD_ALLOWED_DOCS,
    enrich_empty_fields_from_all_doc_records,
)


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


def test_passport_number_whitelist_excludes_judicial_and_divorce():
    assert set(FIELD_ALLOWED_DOCS["passport_number"]) == {"passport"}
    assert "judicial_certificate" not in FIELD_ALLOWED_DOCS["passport_number"]
    assert "divorce" not in FIELD_ALLOWED_DOCS["passport_number"]


def test_passport_number_does_not_fill_from_worksheet():
    """Thông tin Passport / Personal strictly lấy từ passport, không tự lấy từ worksheet."""
    worksheet = _rec({"passport_number": "B1234567"}, "ds260_customer_form")
    sections = [
        {
            "id": "section_a_passport",
            "fields": [{"key": "passport_number", "value": "", "source": {}}],
        }
    ]
    enrich_empty_fields_from_all_doc_records(sections, [worksheet], {})
    assert sections[0]["fields"][0]["value"] == ""


def test_passport_number_worksheet_fallback_ignores_unrelated_document_number():
    """Worksheet chứa document_number của MỤC LY HÔN (không phải hộ chiếu) — không được lọt
    vào passport_number."""
    worksheet = _rec(
        {"document_number": "DIV-555", "divorce_date": "2020-01-01"},
        "ds260_customer_form",
    )
    sections = [
        {
            "id": "section_a_passport",
            "fields": [{"key": "passport_number", "value": "", "source": {}}],
        }
    ]
    enrich_empty_fields_from_all_doc_records(sections, [worksheet], {})
    assert sections[0]["fields"][0]["value"] == ""


def test_nationality_allows_passport_only():
    assert set(FIELD_ALLOWED_DOCS["nationality"]) == {"passport"}


def test_phone_and_email_allow_worksheet_and_application_form():
    """primary_phone/email cho phép worksheet + application_form (Job Application, mục
    Applicant's Information có phone/email riêng của người khai) — mở rộng 2026-08-05, trước đó
    chỉ worksheet nên field bị bỏ trống nếu worksheet thiếu dù application_form OCR đã đọc được."""
    assert set(FIELD_ALLOWED_DOCS["primary_phone"]) == {"ds260_customer_form", "application_form"}
    assert set(FIELD_ALLOWED_DOCS["email"]) == {"ds260_customer_form", "application_form"}


def test_address_fields_are_worksheet_only_not_application_form():
    """ADDRESS (current_address/city/state/postal/country) CHỈ lấy từ worksheet DS-260 khách
    khai — Application form không được cross-fill khi worksheet trống nữa (khách yêu cầu: trống
    thì để trống, Job App chỉ dùng để đối chiếu conflict khi cả 2 bên đều có giá trị — xem
    build_worksheet_conflict_rows/WORKSHEET_OFFICIAL_DOC_OVERRIDES)."""
    assert set(FIELD_ALLOWED_DOCS["current_address"]) == {
        "ds260_customer_form",
        "passport",
        "address_document",
    }
    assert set(FIELD_ALLOWED_DOCS["current_city"]) == {"ds260_customer_form"}
    assert set(FIELD_ALLOWED_DOCS["current_state"]) == {"ds260_customer_form"}
    assert set(FIELD_ALLOWED_DOCS["postal_code"]) == {"ds260_customer_form"}
    assert set(FIELD_ALLOWED_DOCS["current_country"]) == {"ds260_customer_form"}


def test_current_address_still_allows_passport_not_city_from_passport():
    """Passport_new vẫn được phép điền street address khi worksheet trống, nhưng KHÔNG được
    điền city/postal (không có field đáng tin cậy cho 2 mục này trên passport)."""
    passport_ref = _rec(
        {
            "current_address": "123 LE LOI",
            "address_city": "DA NANG",
            "postal_code": "550000",
        },
        "passport",
        variant="exception",
    )
    sections = [
        {
            "id": "section_address",
            "fields": [
                {"key": "current_address", "value": "", "source": {}},
                {"key": "current_city", "value": "", "source": {}},
                {"key": "postal_code", "value": "", "source": {}},
            ],
        }
    ]
    enrich_empty_fields_from_all_doc_records(sections, [passport_ref], {})
    by_key = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert by_key["current_address"] == "123 LE LOI"
    assert by_key["current_city"] == ""
    assert by_key["postal_code"] == ""


def test_current_address_and_city_do_not_fill_from_application_form():
    """Application form (Job Application) có current_address/address_city/postal_code riêng của
    người khai, nhưng KHÔNG còn được dùng để cross-fill ADDRESS khi worksheet trống — worksheet
    trống thì các field này phải giữ trống, Job App chỉ dùng để đối chiếu conflict. primary_phone/
    email KHÔNG thuộc phạm vi thay đổi này — vẫn fill từ application_form như trước."""
    app_form_ref = _rec(
        {
            "current_address": "123 LE LOI",
            "address_city": "DA NANG",
            "postal_code": "550000",
            "primary_phone_number": "0901112233",
            "email_address": "duyen@example.com",
        },
        "application_form",
        variant="standard",
    )
    sections = [
        {
            "id": "section_address",
            "fields": [
                {"key": "current_address", "value": "", "source": {}},
                {"key": "current_city", "value": "", "source": {}},
                {"key": "postal_code", "value": "", "source": {}},
            ],
        },
        {
            "id": "section_contact",
            "fields": [
                {"key": "primary_phone", "value": "", "source": {}},
                {"key": "email", "value": "", "source": {}},
            ],
        },
    ]
    enrich_empty_fields_from_all_doc_records(sections, [app_form_ref], {})
    by_key = {f["key"]: f["value"] for sec in sections for f in sec["fields"]}
    assert by_key["current_address"] == ""
    assert by_key["current_city"] == ""
    assert by_key["postal_code"] == ""
    assert by_key["primary_phone"] == "0901112233"
    assert by_key["email"] == "duyen@example.com"


def test_judicial_certificate_number_whitelist_is_strict():
    allowed = set(FIELD_ALLOWED_DOCS["judicial_certificate_number"])
    assert allowed == {"judicial_certificate", "ds260_customer_form"}


def test_judicial_document_number_does_not_fill_passport_number():
    judicial = _rec(
        {"document_number": "JUD-999", "certificate_number": "JUD-999"},
        "judicial_certificate",
    )
    divorce = _rec({"document_number": "DIV-888"}, "divorce")
    sections = [
        {
            "id": "section_a_passport",
            "fields": [{"key": "passport_number", "value": "", "source": {}}],
        }
    ]
    enrich_empty_fields_from_all_doc_records(sections, [judicial, divorce], {})
    assert sections[0]["fields"][0]["value"] == ""


def test_divorce_document_number_does_not_fill_unrelated_fields():
    divorce = _rec({"document_number": "DIV-777"}, "divorce")
    sections = [
        {
            "id": "section_a_passport",
            "fields": [
                {"key": "passport_number", "value": "", "source": {}},
                {"key": "passport_issue_date", "value": "", "source": {}},
            ],
        }
    ]
    enrich_empty_fields_from_all_doc_records(sections, [divorce], {})
    for field in sections[0]["fields"]:
        assert field["value"] == ""


def test_passport_new_still_fills_father_cross_fill():
    passport_ref = _rec(
        {"father_surname": "TRAN", "father_given_names": "VAN B"},
        "passport",
        variant="exception",
    )
    sections = [
        {
            "id": "section_father",
            "fields": [
                {"key": "father_surname", "value": "", "source": {}},
                {"key": "father_given_names", "value": "", "source": {}},
            ],
        }
    ]
    enrich_empty_fields_from_all_doc_records(sections, [passport_ref], {})
    by_key = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert by_key["father_surname"] == "TRAN"
    assert by_key["father_given_names"] == "VAN B"


def test_judicial_loose_match_does_not_fill_applicant_name():
    judicial = _rec(
        {"full_name": "FROM JUDICIAL", "document_number": "J-123"},
        "judicial_certificate",
    )
    sections = [
        {
            "id": "section_a_personal",
            "fields": [{"key": "applicant_name", "value": "", "source": {}}],
        }
    ]
    enrich_empty_fields_from_all_doc_records(sections, [judicial], {})
    assert sections[0]["fields"][0]["value"] == ""
