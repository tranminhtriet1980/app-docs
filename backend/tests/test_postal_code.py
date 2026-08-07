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


def test_parent_postal_code_never_derived_from_birthplace():
    """Postal code cha/mẹ phải theo ĐỊA CHỈ HIỆN TẠI, không phải nơi sinh — nơi sinh và nơi ở
    hiện tại là 2 khái niệm khác nhau, mỗi nơi có mã bưu điện riêng. Bug thật (2026-08-05):
    mother_postal_code bị suy từ mother_birth_state ('Nghe An' → 460000) trong khi DS-260 gốc của
    khách ghi rõ mẹ đang ở postal code khác (78607) — vì bleed-detection xóa nhầm dữ liệu hiện tại
    thật, rồi export lại tự đoán bù bằng nơi sinh (nguồn kém tin cậy hơn cho postal code)."""
    from app.services.export_ds260 import _prepare_display_values

    out = _prepare_display_values(
        {
            "mother_birth_state": "Nghe An",
            "mother_birth_city": "Vinh",
            "mother_birth_country": "Vietnam",
            # Không có mother_state/mother_city/mother_address (địa chỉ hiện tại) → phải để TRỐNG.
        }
    )
    assert out.get("mother_postal_code", "") == "", (
        f"Không được suy postal code cha/mẹ từ nơi sinh, ra: {out.get('mother_postal_code')!r}"
    )

    # Có địa chỉ HIỆN TẠI thật thì vẫn phải tính đúng, không bị fallback nơi sinh che mất.
    out2 = _prepare_display_values(
        {
            "mother_birth_state": "Nghe An",
            "mother_state": "Da Nang",
            "mother_city": "Da Nang",
            "mother_country": "Vietnam",
        }
    )
    assert out2.get("mother_postal_code") == "550000"
