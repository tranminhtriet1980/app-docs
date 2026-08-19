import pytest

from app.services.ds260_normalize import normalize_gender, normalize_phone


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Male", "Male"),
        ("MALE", "Male"),
        ("M", "Male"),
        ("Nam", "Male"),
        ("nam", "Male"),
        ("Man", "Male"),
        ("Female", "Female"),
        ("F", "Female"),
        ("Nữ", "Female"),
        ("nu", "Female"),
        ("Woman", "Female"),
        ("Other", "Other"),
        ("Khác", "Other"),
        ("khac", "Other"),
        ("NAM / M", "Male"),
        ("Nữ/F", "Female"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_gender_known_tokens(raw, expected):
    assert normalize_gender(raw) == expected


def test_normalize_gender_unrecognized_returns_raw_value():
    # No fallback to "Other" — unrecognized OCR text must survive unchanged so it can
    # be reviewed rather than silently mislabeled on the legal DS-260 form.
    assert normalize_gender("mo ta khong ro") == "mo ta khong ro"
    assert normalize_gender("???") == "???"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("0398333484", "398333484"),
        ("+84 398333484", "398333484"),
        ("84398333484", "398333484"),
        ("0084398333484", "398333484"),
        ("84 0398333484", "398333484"),
        ("", ""),
        (None, ""),
    ],
)
def test_normalize_phone_various_shapes(raw, expected):
    assert normalize_phone(raw) == expected


def test_normalize_phone_local_and_international_match():
    assert normalize_phone("0398333484") == normalize_phone("+84 398333484")
    assert normalize_phone("0398333484") == normalize_phone("84398333484")
    assert normalize_phone("0398333484") == normalize_phone("0084398333484")
    assert normalize_phone("0398333484") == normalize_phone("84 0398333484")


def test_normalize_phone_rejects_different_number():
    assert normalize_phone("0398333484") != normalize_phone("0912345678")
