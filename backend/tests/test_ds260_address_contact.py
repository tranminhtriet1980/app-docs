"""DS-260 sections 3–5: address, contact, social from customer reference."""

import json
from types import SimpleNamespace
from uuid import uuid4

from app.services.ds260_mapping import (
    enrich_empty_fields_from_reference_records,
    flatten_ds260_mappings,
    resolve_customer_form_field,
)


def _rec(raw: dict, doc_type: str = "passport", *, variant: str = "exception") -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        doc_type=doc_type,
        variant=variant,
        source_document_id=uuid4(),
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
        updated_at=None,
    )


def test_contact_from_passport_new_cross_fill():
    passport_ref = _rec(
        {
            "current_address": "123 LE LOI",
            "address_city": "DA NANG",
            "address_state": "DA NANG",
            "address_country": "VIETNAM",
            "postal_code": "550000",
            "primary_phone_number": "+84901234567",
            "email_address": "test@example.com",
            "social_media_platform": "Facebook",
            "social_media_identifier": "facebook.com/user",
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
        },
        {
            "id": "section_contact",
            "fields": [
                {"key": "primary_phone", "value": "", "source": {}},
                {"key": "email", "value": "", "source": {}},
            ],
        },
        {
            "id": "section_social",
            "fields": [
                {"key": "social_media_platform", "value": "", "source": {}},
            ],
        },
    ]
    enrich_empty_fields_from_reference_records(sections, [passport_ref], {})
    addr = {f["key"]: f["value"] for f in sections[0]["fields"]}
    contact = {f["key"]: f["value"] for f in sections[1]["fields"]}
    social = {f["key"]: f["value"] for f in sections[2]["fields"]}
    assert addr["current_address"] == "123 LE LOI"
    assert addr["current_city"] == ""
    assert addr["postal_code"] == ""
    assert contact["primary_phone"] == ""
    assert contact["email"] == ""
    assert social["social_media_platform"] == ""


def test_loose_profile_key_contact_phone():
    from app.services.ds260_mapping import _resolve_loose_from_record

    ref = _rec(
        {"contact.phone_primary": "+84901112233"},
        "passport",
        variant="exception",
    )
    mapping = flatten_ds260_mappings()["primary_phone"]
    val, sf = _resolve_loose_from_record(ref, mapping)
    assert val == "+84901112233"
    assert sf == "contact.phone_primary"

    std = _rec({}, "address_document", variant="standard")
    ref = _rec({"current_address": "456 TRAN PHU", "address_city": "HUE"}, "address_document", variant="exception")
    mapping = flatten_ds260_mappings()["current_address"]
    val, _, rec, extra = resolve_customer_form_field([std, ref], "address_document", mapping)
    assert val == "456 TRAN PHU"
    assert rec is ref
    assert extra.get("derived") == "reference_fallback"
