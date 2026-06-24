"""Vietnam province → postal code for DS-260."""

from app.services.postal_code import derive_postal_code_from_location


def test_da_nang_from_city():
    assert derive_postal_code_from_location(city="Da Nang City", country="Vietnam") == "550000"


def test_da_nang_from_address():
    assert (
        derive_postal_code_from_location(
            address="An Don, An Hai Bac, Da Nang City",
            country="Vietnamese",
        )
        == "550000"
    )


def test_empty_without_location():
    assert derive_postal_code_from_location() == ""
    assert derive_postal_code_from_location(state="", city="") == ""


def test_non_vietnam_country():
    assert derive_postal_code_from_location(state="California", city="Los Angeles", country="USA") == ""


def test_hanoi():
    assert derive_postal_code_from_location(state="Ha Noi", country="Vietnam") == "100000"


def test_export_postal_only_with_current_address():
    from app.services.export_ds260 import _prepare_display_values

    without_addr = _prepare_display_values(
        {"birth_city": "Da Nang", "birth_state": "Da Nang", "birth_country": "Vietnam"}
    )
    assert without_addr.get("postal_code") == ""

    with_addr = _prepare_display_values(
        {
            "current_address": "35 An Hai 15, An Hai",
            "current_city": "Da Nang",
            "current_country": "Vietnam",
        }
    )
    assert with_addr.get("postal_code") == "550000"
