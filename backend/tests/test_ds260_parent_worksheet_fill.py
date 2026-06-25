"""Cha/mẹ: GKS thiếu field → bổ sung từ DS-260 khách khai (01_6)."""

import json
from types import SimpleNamespace
from uuid import uuid4

from app.services.ds260_customer_keys import normalize_ds260_customer_raw
from app.services.ds260_mapping import enrich_empty_fields_from_all_doc_records


def _rec(doc_type: str, raw: dict, *, variant: str = "standard") -> SimpleNamespace:
    data = json.dumps(raw)
    return SimpleNamespace(
        id=uuid4(),
        doc_type=doc_type,
        variant=variant,
        source_document_id=uuid4(),
        form_data=data,
        raw_data=data,
        updated_at=None,
    )


def _father_section() -> dict:
    keys = [
        "father_surname",
        "father_given_names",
        "father_date_of_birth",
        "father_birth_city",
        "father_birth_state",
        "father_birth_country",
        "father_full_name",
        "father_is_living",
        "father_death_year",
        "father_address",
        "father_city",
        "father_state",
        "father_postal_code",
        "father_country",
    ]
    return {
        "id": "section_father",
        "fields": [{"key": k, "value": "", "source": {}} for k in keys],
    }


def test_family_prefix_keys_normalize_to_father_fields():
    raw = normalize_ds260_customer_raw(
        {
            "family.father_surname": "TRAN",
            "family.father_given_names": "VAN A",
            "family.father_date_of_birth": "1960-05-01",
            "family.father_birth_city": "HUE",
            "family.father_city": "DA NANG",
            "family.father_address_line1": "123 LE LOI",
            "family.father_death_year": "2020",
        }
    )
    assert raw["father_surname"] == "TRAN"
    assert raw["father_birth_city"] == "HUE"
    assert raw["father_city"] == "DA NANG"
    assert raw["father_address"] == "123 LE LOI"
    assert raw["father_death_year"] == "2020"


def test_gks_name_only_worksheet_fills_parent_details():
    bc = _rec("birth_certificate", {"father_name": "TRAN VAN A", "mother_name": "LE THI B"})
    ws_raw = normalize_ds260_customer_raw(
        {
            "father_surname": "TRAN",
            "father_given_names": "VAN A",
            "father_date_of_birth": "1960-01-01",
            "father_birth_city": "HUE",
            "father_is_living": "No",
            "father_death_year": "2018",
            "father_address": "456 TRAN PHU",
            "father_city": "DA NANG",
            "father_state": "DA NANG",
            "father_postal_code": "550000",
            "father_country": "VIETNAM",
            "mother_surname": "LE",
            "mother_given_names": "THI B",
            "mother_date_of_birth": "1962-03-15",
            "mother_birth_city": "QUANG NAM",
            "mother_is_living": "Yes",
            "mother_address": "789 HUNG VUONG",
            "mother_city": "HOI AN",
            "mother_postal_code": "560000",
            "mother_country": "VIETNAM",
        }
    )
    ws = _rec("ds260_customer_form", ws_raw, variant="exception")

    father_sec = _father_section()
    mother_sec = {
        "id": "section_mother",
        "fields": [
            {"key": k, "value": "", "source": {}}
            for k in [
                "mother_surname",
                "mother_given_names",
                "mother_date_of_birth",
                "mother_birth_city",
                "mother_is_living",
                "mother_address",
                "mother_city",
                "mother_postal_code",
                "mother_country",
            ]
        ],
    }

    enrich_empty_fields_from_all_doc_records([father_sec, mother_sec], [bc, ws], {})

    f = {x["key"]: x["value"] for x in father_sec["fields"]}
    m = {x["key"]: x["value"] for x in mother_sec["fields"]}

    assert f["father_full_name"] == "TRAN VAN A"
    assert f["father_surname"] == "TRAN"
    assert f["father_date_of_birth"] == "1960-01-01"
    assert f["father_birth_city"] == "HUE"
    assert f["father_city"] == "DA NANG"
    assert f["father_death_year"] == "2018"
    assert f["father_address"] == "456 TRAN PHU"
    assert f["father_postal_code"] == "550000"

    assert m["mother_surname"] == "LE"
    assert m["mother_birth_city"] == "QUANG NAM"
    assert m["mother_city"] == "HOI AN"
    assert m["mother_address"] == "789 HUNG VUONG"

    src = next(x["source"] for x in father_sec["fields"] if x["key"] == "father_death_year")
    assert src.get("derived") == "ds260_worksheet_fill"
    assert src.get("document_type") == "ds260_customer_form"


def test_birth_city_not_filled_from_current_city_alias():
    """father_city (địa chỉ hiện tại) không được điền vào father_birth_city."""
    ws = _rec(
        "ds260_customer_form",
        {"father_city": "DA NANG", "father_birth_city": ""},
        variant="exception",
    )
    father_sec = _father_section()
    enrich_empty_fields_from_all_doc_records([father_sec], [ws], {})
    f = {x["key"]: x["value"] for x in father_sec["fields"]}
    assert f["father_city"] == "DA NANG"
    assert f["father_birth_city"] == ""
