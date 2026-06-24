"""Tests for birth location derivation."""

from app.services.birth_location import (
    derive_birth_state_from_place,
    derive_country_from_place,
)


def test_birth_state_copies_place_of_birth():
    pob = "An Don, An Hai Bac, Da Nang City"
    assert derive_birth_state_from_place(pob) == pob


def test_birth_country_from_vn_location():
    assert derive_country_from_place("An Don, An Hai Bac, Da Nang City") == "Vietnam"
    assert derive_country_from_place("HA NOI") == "Vietnam"
    assert derive_country_from_place("Ho Chi Minh City") == "Vietnam"


def test_birth_country_from_explicit_country():
    assert derive_country_from_place("Los Angeles, California, United States") == "United States"
    assert derive_country_from_place("Paris, France") == "France"


def test_birth_country_not_from_nationality():
    # Nationality alone must not be used — empty place => empty country
    assert derive_country_from_place("") == ""
    assert derive_country_from_place("VIETNAM") == "Vietnam"  # explicit country in place string
