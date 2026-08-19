"""missing_address_before_16 — mm/yyyy address_from_date must not mis-fire the warning."""

from app.services.ds260_validate import missing_address_before_16


def _check(address_from_val, dob_val="15/01/1990", other_used="", other_history=""):
    return missing_address_before_16(
        dob_val=dob_val,
        address_from_val=address_from_val,
        other_addresses_used=other_used,
        other_addresses_history=other_history,
    )


def test_full_date_before_16_no_warning():
    # Turns 16 on 15/01/2006; address from earlier that year → covered.
    assert _check("01/01/2006") is False


def test_month_year_before_16_no_warning():
    # mm/yyyy from-date, same month as the 16th birthday — previously mis-fired because
    # parse_full_date() rejected mm/yyyy and treated it as "no address" (báo lỗi thực tế).
    assert _check("01/2006") is False


def test_month_year_same_month_as_16th_birthday_no_warning():
    assert _check("01/2006") is False


def test_month_year_after_16_still_warns():
    assert _check("06/2006") is True


def test_full_date_after_16_still_warns():
    # Next month after the 16th birthday — unambiguously after at month granularity.
    assert _check("01/02/2006") is True


def test_full_date_same_month_as_16th_birthday_no_warning():
    # Later day, same month as the 16th birthday — compared at month granularity, so a
    # few days' difference within the birth month must not mis-fire.
    assert _check("20/01/2006") is False


def test_year_only_after_16_still_warns():
    assert _check("2007") is True


def test_no_address_from_date_warns():
    assert _check("") is True


def test_covered_by_other_addresses_history_no_warning():
    assert _check("06/2006", other_used="yes", other_history="12 Le Loi, before 2006") is False


def test_no_dob_no_warning():
    # Can't compute the 16-year mark without a full DOB — don't warn.
    assert missing_address_before_16(
        dob_val="",
        address_from_val="06/2006",
        other_addresses_used="",
        other_addresses_history="",
    ) is False
