"""DS-260 date formatting and partial-date handling."""

from app.services.ds260_dates import (
    format_ds260_display_date,
    format_partial_ds260_date,
    is_partial_date_value,
    parse_full_date,
    sanitize_date_values,
)
from app.services.export_ds260 import _prepare_display_values


def test_format_full_date_d_month_yyyy():
    assert format_ds260_display_date("1990-01-15") == "15 January 1990"
    assert format_ds260_display_date("15/01/1990") == "15 January 1990"
    assert format_ds260_display_date("01 May 2026") == "01 May 2026"
    assert format_ds260_display_date("2026-05-01") == "01 May 2026"


def test_partial_dates_export_as_month_year_or_year():
    assert format_ds260_display_date("2023-05") == "May 2023"
    assert format_ds260_display_date("05/2023") == "May 2023"
    assert format_ds260_display_date("May 2023") == "May 2023"
    assert format_ds260_display_date("2023") == "2023"
    assert parse_full_date("2023-05") is None
    assert is_partial_date_value("2023-05")
    assert not is_partial_date_value("1990-01-15")


def test_prepare_display_keeps_partial_marriage_date():
    out = _prepare_display_values(
        {
            "spouse_marriage_date": "2023-05",
            "address_from_date": "05/2023",
            "date_of_birth": "1990-01-15",
            "current_address": "123 LE LOI",
        }
    )
    assert out["spouse_marriage_date"] == "May 2023"
    assert out["address_from_date"] == "May 2023"
    assert out["date_of_birth"] == "15 January 1990"


def test_sanitize_date_values():
    cleaned = sanitize_date_values(
        {
            "address_from_date": "2023-05",
            "passport_issue_date": "2020-03-01",
            "military_service_start": "2023",
        }
    )
    assert cleaned["address_from_date"] == "May 2023"
    assert cleaned["passport_issue_date"] == "01 March 2020"
    assert cleaned["military_service_start"] == "2023"
