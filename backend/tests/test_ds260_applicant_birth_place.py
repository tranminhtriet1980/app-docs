"""Applicant birth city/state in personal information section."""

import json
from types import SimpleNamespace

from app.services.ds260_mapping import enrich_applicant_birth_city_state_equal


def _rec(raw: dict, doc_type: str = "passport") -> SimpleNamespace:
    return SimpleNamespace(
        doc_type=doc_type,
        form_data=json.dumps(raw),
        raw_data=json.dumps(raw),
    )


def test_birth_city_and_state_equal_from_passport():
    passport = _rec(
        {
            "full_name": "DANG VAN HUNG",
            "place_of_birth": "An Don, An Hai Bac, Da Nang City, Vietnam",
            "birth_city": "",
        }
    )
    fields = [
        {"key": "place_of_birth", "value": "An Don, An Hai Bac, Da Nang City, Vietnam", "source": {}},
        {"key": "birth_city", "value": "", "source": {}},
        {"key": "birth_state", "value": "An Don, An Hai Bac, Da Nang City, Vietnam", "source": {}},
    ]
    enrich_applicant_birth_city_state_equal(fields, passport)
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["birth_city"] == by_key["birth_state"]
    assert by_key["birth_city"] == "Da Nang City"


def test_export_birth_city_state_not_forced_equal():
    """Export không còn ép birth_state = birth_city (đã chuẩn hóa ở resolve)."""
    from app.services.export_ds260 import _prepare_display_values

    out = _prepare_display_values({"birth_city": "N/A", "birth_state": "Thua Thien Hue"})
    assert out["birth_city"] == "N/A"
    assert out["birth_state"] == "Thua Thien Hue"


def test_normalize_municipality_birthplace():
    """TP trực thuộc TW → City = TP, State = N/A."""
    from app.services.ds260_mapping import normalize_ds260_place_fields

    sections = [
        {
            "id": "section_a_personal",
            "fields": [
                {"key": "place_of_birth", "value": "An Don, An Hai Bac, Da Nang City, Vietnam", "source": {}},
                {"key": "birth_city", "value": "Khoa San Khu Vuc 2", "source": {}},
                {"key": "birth_state", "value": "An Don, An Hai Bac, Da Nang City", "source": {}},
                {"key": "birth_country", "value": "Vietnam", "source": {}},
            ],
        }
    ]
    normalize_ds260_place_fields(sections)
    by_key = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert by_key["birth_city"] == "Da Nang"
    assert by_key["birth_state"] == "N/A"


def test_normalize_province_birthplace():
    """Tỉnh → State = tỉnh, City = N/A; bỏ tên bệnh viện."""
    from app.services.ds260_mapping import normalize_ds260_place_fields

    sections = [
        {
            "id": "section_father",
            "fields": [
                {"key": "father_birth_city", "value": "Nha Ho Sinh Khu Vuc II, Hue", "source": {}},
                {"key": "father_birth_state", "value": "To 1, Trung Giang, Huong Luu, Hue", "source": {}},
                {"key": "father_birth_country", "value": "Vietnam", "source": {}},
            ],
        }
    ]
    normalize_ds260_place_fields(sections)
    by_key = {f["key"]: f["value"] for f in sections[0]["fields"]}
    assert by_key["father_birth_city"] == "N/A"
    assert by_key["father_birth_state"] == "Thua Thien Hue"
