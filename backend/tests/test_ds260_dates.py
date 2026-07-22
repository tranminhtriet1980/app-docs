"""DS-260 date formatting and partial-date handling."""

from app.services.ds260_dates import (
    format_ds260_display_date,
    format_ds260_display_date_range,
    format_partial_ds260_date,
    format_sections_date_display,
    is_partial_date_value,
    parse_full_date,
    sanitize_date_values,
)
from app.services.export_ds260 import _prepare_display_values


def test_format_full_date_d_month_yyyy():
    assert format_ds260_display_date("1990-01-15") == "15 Jan 1990"
    assert format_ds260_display_date("15/01/1990") == "15 Jan 1990"
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
    assert out["date_of_birth"] == "15 Jan 1990"


def test_date_range_standardized_to_dd_mon_yyyy():
    # Khoảng thời gian học → 'DD Mon YYYY - DD Mon YYYY', bất kể định dạng đầu vào.
    assert format_ds260_display_date_range("Aug 15, 2004 - Jun 01, 2008") == "15 Aug 2004 - 01 Jun 2008"
    assert format_ds260_display_date_range("15/08/2008 - 02/06/2011") == "15 Aug 2008 - 02 Jun 2011"
    assert format_ds260_display_date_range("2010-01-01 to 2012-01-01") == "01 Jan 2010 - 01 Jan 2012"
    # Dấu '-' TRONG ngày dd-mm-yyyy không bị cắt nhầm (chỉ tách khi '-' có space hai bên).
    assert format_ds260_display_date_range("01-01-2010 - 31-12-2012") == "01 Jan 2010 - 31 Dec 2012"


def test_date_range_open_ended_and_passthrough():
    assert format_ds260_display_date_range("Sep 2008 to Now") == "Sep 2008 - Present"
    assert format_ds260_display_date_range("từ 01/2010 đến nay") == "Jan 2010 - Present"
    assert format_ds260_display_date_range("2015") == "2015"   # 1 giá trị, không phải khoảng
    assert format_ds260_display_date_range("N/A") == "N/A"      # không phải ngày → giữ nguyên


def test_sections_standardize_period_and_service_dates():
    secs = [
        {
            "id": "x",
            "fields": [
                {"key": "edu_high_school_period", "value": "Aug 15, 2008 - Jun 02, 2011"},
                {"key": "military_service_start", "value": "2010-01-01"},
                {"key": "military_service_end", "value": "01/01/2012"},
            ],
        }
    ]
    format_sections_date_display(secs)
    got = {f["key"]: f["value"] for f in secs[0]["fields"]}
    assert got["edu_high_school_period"] == "15 Aug 2008 - 02 Jun 2011"
    assert got["military_service_start"] == "01 Jan 2010"
    assert got["military_service_end"] == "01 Jan 2012"


def test_sanitize_date_values():
    cleaned = sanitize_date_values(
        {
            "address_from_date": "2023-05",
            "passport_issue_date": "2020-03-01",
            "military_service_start": "2023",
        }
    )
    assert cleaned["address_from_date"] == "May 2023"
    assert cleaned["passport_issue_date"] == "01 Mar 2020"
    assert cleaned["military_service_start"] == "2023"
