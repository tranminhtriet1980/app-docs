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


def test_export_birth_city_state_display_equal():
    from app.services.export_ds260 import _prepare_display_values

    out = _prepare_display_values(
        {
            "birth_city": "Da Nang City",
            "birth_state": "An Don, An Hai Bac, Da Nang City, Vietnam",
        }
    )
    assert out["birth_city"] == "Da Nang"
    assert out["birth_state"] == "Da Nang"

    fields = [
        {"key": "birth_city", "value": "Da Nang", "source": {}},
        {"key": "birth_state", "value": "Da Nang City, Vietnam", "source": {}},
    ]
    enrich_applicant_birth_city_state_equal(fields, None)
    by_key = {f["key"]: f["value"] for f in fields}
    assert by_key["birth_city"] == "Da Nang"
    assert by_key["birth_state"] == "Da Nang"
