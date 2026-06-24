"""DS-260 parent (father/mother) fields from birth certificate."""

import json
from types import SimpleNamespace

from app.services.ds260_mapping import (
    apply_mother_absent_rule,
    apply_parent_absent_rule,
    has_father_info_on_birth_cert,
    has_mother_info_on_birth_cert,
    has_parent_info_on_birth_cert,
)


def _rec(form: dict | None = None, *, raw: dict | None = None, doc_type: str | None = "birth_certificate") -> SimpleNamespace:
    return SimpleNamespace(
        form_data=json.dumps(form or {}),
        raw_data=json.dumps(raw or {}),
        doc_type=doc_type,
    )


def test_no_mother_info():
    rec = _rec({"full_name": "CHILD", "father_surname": "TRAN"})
    assert has_mother_info_on_birth_cert(rec) is False


def test_na_mother_name_is_not_info():
    rec = _rec({"mother_name": "N/A"})
    assert has_mother_info_on_birth_cert(rec) is False


def test_has_mother_surname():
    rec = _rec({"mother_surname": "LE", "mother_given_names": "THI C"})
    assert has_mother_info_on_birth_cert(rec) is True


def test_mother_absent_rule():
    fields = [
        {"key": "mother_surname", "value": "OLD", "source": {}},
        {"key": "mother_given_names", "value": "OLD", "source": {}},
    ]
    apply_mother_absent_rule(fields)
    assert fields[0]["value"] == "N/A"
    assert fields[1]["value"] == ""


def test_parent_generic():
    rec = _rec({"mother_name": "LE THI D"})
    assert has_parent_info_on_birth_cert(rec, "mother") is True
    assert has_father_info_on_birth_cert(rec) is False


def test_resolve_mother_from_ocr_aliases():
    """Giấy khai sinh VN — OCR trả mother_city/address/country thay vì mother_birth_*."""
    from app.services.ds260_mapping import _resolve_ds260_field_value, flatten_ds260_mappings

    raw = {
        "mother_name": "ĐẶNG THỊ TIÊM",
        "mother_date_of_birth": "1954-01-01",
        "mother_city": "Đà Nẵng",
        "mother_address": "An Đồn, An Hải Bắc, thành phố Đà Nẵng",
        "mother_country": "Việt Nam",
    }
    rec = _rec(raw=raw)
    mappings = flatten_ds260_mappings()

    dob, _ = _resolve_ds260_field_value(mappings["mother_date_of_birth"], rec)
    city, _ = _resolve_ds260_field_value(mappings["mother_birth_city"], rec)
    state, _ = _resolve_ds260_field_value(mappings["mother_birth_state"], rec)
    country, _ = _resolve_ds260_field_value(mappings["mother_birth_country"], rec)

    assert dob == "1954-01-01"
    assert city == "Đà Nẵng"
    assert "Đà Nẵng" in state
    assert country == "Vietnam"
