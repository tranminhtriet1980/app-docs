"""DS-260 date formatting and partial-date handling."""

from datetime import date

from app.services.ds260_dates import (
    format_ds260_display_date,
    format_ds260_display_date_range,
    format_ds260_export_date,
    format_partial_ds260_date,
    format_sections_date_display,
    is_ambiguous_numeric_date,
    is_partial_date_value,
    looks_like_date_but_unparsed,
    parse_date_lenient,
    parse_full_date,
    sanitize_date_values,
)
from app.services.export_ds260 import _prepare_display_values


def test_format_full_date_dd_mm_yyyy():
    assert format_ds260_display_date("1990-01-15") == "15/01/1990"
    assert format_ds260_display_date("15/01/1990") == "15/01/1990"
    assert format_ds260_display_date("01 May 2026") == "01/05/2026"
    assert format_ds260_display_date("2026-05-01") == "01/05/2026"


def test_partial_dates_export_as_month_year_or_year():
    assert format_ds260_display_date("2023-05") == "05/2023"
    assert format_ds260_display_date("05/2023") == "05/2023"
    assert format_ds260_display_date("May 2023") == "05/2023"
    assert format_ds260_display_date("2023") == "2023"
    assert parse_full_date("2023-05") is None
    assert is_partial_date_value("2023-05")
    assert not is_partial_date_value("1990-01-15")


def test_prepare_display_keeps_partial_marriage_date():
    # Word export dùng mốc trọn kiểu Anh, tháng viết tắt ("15 Aug 1990") — dashboard vẫn
    # dd/mm/yyyy (format_sections_date_display, không đổi ở đây).
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


def test_parse_date_lenient_granularity():
    assert parse_date_lenient("1990-01-15") == (date(1990, 1, 15), "day")
    assert parse_date_lenient("05/2023") == (date(2023, 5, 1), "month")
    assert parse_date_lenient("2023-05") == (date(2023, 5, 1), "month")
    assert parse_date_lenient("2023") == (date(2023, 1, 1), "year")
    assert parse_date_lenient("not a date") is None
    assert parse_date_lenient("") is None


def test_format_ds260_export_date_english_month():
    assert format_ds260_export_date("15/01/1990") == "15 Jan 1990"
    assert format_ds260_export_date("1990-01-15") == "15 Jan 1990"
    assert format_ds260_export_date("15/08/1990") == "15 Aug 1990"
    assert format_ds260_export_date("05/2023") == "May 2023"
    assert format_ds260_export_date("2023-05") == "May 2023"
    assert format_ds260_export_date("2023-09") == "Sep 2023"
    assert format_ds260_export_date("2023") == "2023"
    assert format_ds260_export_date("N/A") == "N/A"
    assert format_ds260_export_date("") == ""


def test_date_range_standardized_to_dd_mm_yyyy():
    # Khoảng thời gian học → 'dd/mm/yyyy - dd/mm/yyyy', bất kể định dạng đầu vào.
    assert format_ds260_display_date_range("Aug 15, 2004 - Jun 01, 2008") == "15/08/2004 - 01/06/2008"
    assert format_ds260_display_date_range("15/08/2008 - 02/06/2011") == "15/08/2008 - 02/06/2011"
    assert format_ds260_display_date_range("2010-01-01 to 2012-01-01") == "01/01/2010 - 01/01/2012"
    # Dấu '-' TRONG ngày dd-mm-yyyy không bị cắt nhầm (chỉ tách khi '-' có space hai bên).
    assert format_ds260_display_date_range("01-01-2010 - 31-12-2012") == "01/01/2010 - 31/12/2012"


def test_date_range_open_ended_and_passthrough():
    assert format_ds260_display_date_range("Sep 2008 to Now") == "09/2008 - Present"
    assert format_ds260_display_date_range("từ 01/2010 đến nay") == "01/2010 - Present"
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
    assert got["edu_high_school_period"] == "15/08/2008 - 02/06/2011"
    assert got["military_service_start"] == "01/01/2010"
    assert got["military_service_end"] == "01/01/2012"


def test_sanitize_date_values():
    cleaned = sanitize_date_values(
        {
            "address_from_date": "2023-05",
            "passport_issue_date": "2020-03-01",
            "military_service_start": "2023",
        }
    )
    assert cleaned["address_from_date"] == "05/2023"
    assert cleaned["passport_issue_date"] == "01/03/2020"
    assert cleaned["military_service_start"] == "2023"


# --- Nhập nhằng dd/mm ↔ mm/dd (lỗi Case C: spouse DOB xuất thô '01/26/1986') ---


def test_mm_dd_resolved_when_second_part_exceeds_12():
    """Cụm thứ hai > 12 chỉ có thể là NGÀY → cụm đầu là THÁNG. Suy luận xác định."""
    assert parse_full_date("01/26/1986").isoformat() == "1986-01-26"
    assert format_ds260_display_date("01/26/1986") == "26/01/1986"
    assert not is_ambiguous_numeric_date("01/26/1986")


def test_dd_mm_still_default_for_vietnamese_documents():
    assert format_ds260_display_date("26/01/1986") == "26/01/1986"
    assert format_ds260_display_date("12/09/2019") == "12/09/2019"


def test_ambiguous_date_flagged_but_kept_as_dd_mm():
    assert is_ambiguous_numeric_date("05/06/1986")
    assert format_ds260_display_date("05/06/1986") == "05/06/1986"
    # Cùng ngày & tháng → đọc kiểu nào cũng như nhau, không cần cảnh báo.
    assert not is_ambiguous_numeric_date("05/05/1986")


def test_unparseable_date_is_blanked_with_note_not_kept_raw():
    """Trước đây chuỗi hỏng bị giữ nguyên trên form; nay để trống + đánh dấu."""
    assert looks_like_date_but_unparsed("32/45/1986")
    secs = [
        {
            "fields": [
                {"key": "spouse_date_of_birth", "value": "01/26/1986"},
                {"key": "father_date_of_birth", "value": "05/06/1986"},
                {"key": "mother_date_of_birth", "value": "32/45/1986"},
            ]
        }
    ]
    format_sections_date_display(secs)
    got = {f["key"]: f for f in secs[0]["fields"]}

    assert got["spouse_date_of_birth"]["value"] == "26/01/1986"
    assert "date_note" not in got["spouse_date_of_birth"]

    assert got["father_date_of_birth"]["value"] == "05/06/1986"
    assert got["father_date_of_birth"]["date_note"]["code"] == "ambiguous_date"

    assert got["mother_date_of_birth"]["value"] == ""
    assert got["mother_date_of_birth"]["date_note"]["code"] == "unparsed_date"
    assert got["mother_date_of_birth"]["date_note"]["raw"] == "32/45/1986"


def test_birth_date_rejects_partial_value():
    """Ngày sinh (mọi vai trò) chỉ nhận giá trị đầy đủ ngày/tháng/năm — thiếu ngày (chỉ có
    tháng/năm hoặc chỉ năm) bị coi là chưa đủ, để trống + cảnh báo thay vì hiển thị ngày thiếu."""
    secs = [
        {
            "fields": [
                {"key": "date_of_birth", "value": "1990-01-15"},
                {"key": "father_date_of_birth", "value": "05/2023"},
                {"key": "mother_date_of_birth", "value": "1986"},
                {"key": "work_start_date", "value": "05/2023"},
            ]
        }
    ]
    format_sections_date_display(secs)
    got = {f["key"]: f for f in secs[0]["fields"]}

    assert got["date_of_birth"]["value"] == "15/01/1990"
    assert "date_note" not in got["date_of_birth"]

    assert got["father_date_of_birth"]["value"] == ""
    assert got["father_date_of_birth"]["date_note"]["code"] == "partial_birth_date_rejected"

    assert got["mother_date_of_birth"]["value"] == ""
    assert got["mother_date_of_birth"]["date_note"]["code"] == "partial_birth_date_rejected"

    # Field ngày KHÔNG phải ngày sinh (vd. ngày bắt đầu công việc) vẫn được phép chỉ có tháng/năm.
    assert got["work_start_date"]["value"] == "05/2023"
    assert "date_note" not in got["work_start_date"]


def test_valid_dates_never_flagged_as_unparsed():
    for good in ("2020-03-01", "01 Mar 2020", "May 2023", "1963", "03/2023"):
        assert not looks_like_date_but_unparsed(good)
