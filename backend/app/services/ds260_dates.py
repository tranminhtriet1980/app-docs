"""Parse and format dates for DS-260 export / validation."""

from __future__ import annotations

import re
from datetime import date, datetime

_FULL_DATE_TEXT_FORMATS = (
    "%d %B %Y",
    "%d %b %Y",
    "%B %d %Y",
    "%b %d %Y",
    "%B %d, %Y",
    "%b %d, %Y",
    "%d-%b-%Y",
    "%d-%B-%Y",
)


# Ngày dạng số A/B/YYYY (hoặc '-', '.') — dùng chung cho parse và phát hiện nhập nhằng.
_NUMERIC_DMY_RE = re.compile(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$")


def is_date_field_key(key: str) -> bool:
    k = (key or "").lower()
    # 'service_start'/'service_end' là ngày quân sự nhưng tên không chứa 'date'.
    return "date" in k or k.endswith("_dob") or k.endswith("service_start") or k.endswith("service_end")


def is_date_range_field_key(key: str) -> bool:
    """Field chứa KHOẢNG thời gian 'A - B' (vd. thời gian học edu_*_period)."""
    return (key or "").lower().endswith("_period")


def parse_full_date(val: str) -> date | None:
    """Return date only when day + month + year are present; else None."""
    val = (val or "").strip()
    if not val:
        return None

    if re.match(r"^\d{4}-\d{2}$", val):
        return None
    if re.match(r"^\d{4}$", val):
        return None
    if re.match(r"^\d{1,2}[/.-]\d{4}$", val):
        return None
    if re.match(r"^[A-Za-z]+\s+\d{4}$", val):
        return None

    if re.match(r"^\d{4}-\d{2}-\d{2}$", val):
        try:
            return datetime.strptime(val, "%Y-%m-%d").date()
        except ValueError:
            return None

    m = _NUMERIC_DMY_RE.match(val)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        # Giấy tờ VN dùng dd/mm/yyyy, nhưng OCR đôi khi trả mm/dd/yyyy (kiểu Mỹ).
        # Cấu phần thứ hai > 12 thì nó CHỈ có thể là NGÀY → cụm đầu là THÁNG (mm/dd).
        # Suy luận này xác định, không đoán mò. Trường hợp cả hai ≤ 12 là NHẬP NHẰNG
        # thật sự → giữ quy ước VN dd/mm và báo cảnh báo qua is_ambiguous_numeric_date().
        if b > 12 and a <= 12:
            d, mo = b, a
        else:
            d, mo = a, b
        try:
            return date(y, mo, d)
        except ValueError:
            return None

    for fmt in _FULL_DATE_TEXT_FORMATS:
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


_MONTHS_ABBR = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _month_name(month: int) -> str:
    """Tháng viết tắt tiếng Anh (vd. Mar) — thống nhất định dạng ngày DS-260 'DD Mon YYYY' (14 Mar 1983)."""
    return _MONTHS_ABBR[month] if 1 <= month <= 12 else ""


def format_partial_ds260_date(val: str) -> str | None:
    """
    Month/year or year-only → display string.
    2023-05 / 05/2023 → May 2023; 2023 → 2023.
    """
    val = (val or "").strip()
    if not val:
        return None

    m = re.match(r"^(\d{4})-(\d{2})$", val)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return f"{_month_name(mo)} {y}"

    m = re.match(r"^(\d{1,2})[/.-](\d{4})$", val)
    if m:
        mo, y = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return f"{_month_name(mo)} {y}"

    m = re.match(r"^([A-Za-z]+)\s+(\d{4})$", val)
    if m:
        month_raw, year = m.group(1), m.group(2)
        try:
            mo = datetime.strptime(month_raw[:3], "%b").month
            return f"{_month_name(mo)} {year}"
        except ValueError:
            try:
                mo = datetime.strptime(month_raw, "%B").month
                return f"{_month_name(mo)} {year}"
            except ValueError:
                return f"{month_raw.title()} {year}"

    m = re.match(r"^(\d{4})$", val)
    if m:
        return m.group(1)

    return None


def is_ambiguous_numeric_date(val: str) -> bool:
    """True khi ngày dạng số có thể đọc theo CẢ dd/mm lẫn mm/dd → giá trị xuất có thể SAI ÂM THẦM.

    '05/06/1986' → 5 Jun hay 6 May? Hệ thống giữ quy ước VN (dd/mm) nhưng phải cảnh báo
    để người review đối chiếu giấy gốc. '26/01/1986' (26 > 12) KHÔNG nhập nhằng.
    """
    m = _NUMERIC_DMY_RE.match((val or "").strip())
    if not m:
        return False
    a, b = int(m.group(1)), int(m.group(2))
    if a == b:
        return False  # 05/05 đọc kiểu nào cũng ra một ngày
    return 1 <= a <= 12 and 1 <= b <= 12


def looks_like_date_but_unparsed(val: str) -> bool:
    """True khi giá trị CÓ dạng ngày nhưng không parse được (đủ lẫn từng phần).

    Vd. '32/45/1986', '00/00/0000'. Những giá trị này trước đây bị giữ nguyên chuỗi thô
    trên form → lệch định dạng với các ô ngày khác mà không ai biết.
    """
    v = (val or "").strip()
    if not v:
        return False
    if parse_full_date(v) or format_partial_ds260_date(v):
        return False
    # Có ít nhất 1 cụm 4 chữ số (năm) HOẶC dạng số phân tách bằng / - .
    return bool(re.match(r"^[\d/.\-\s]+$", v) and re.search(r"\d", v))


def is_partial_date_value(val: str) -> bool:
    """True when value is month/year or year-only (not a full calendar date)."""
    val = (val or "").strip()
    if not val:
        return False
    if parse_full_date(val):
        return False
    return format_partial_ds260_date(val) is not None


def format_ds260_display_date(val: str) -> str:
    """Full date → 01 May 2026; partial → May 2023 / 2023; else empty."""
    d = parse_full_date(val)
    if d:
        return f"{d.day:02d} {_month_name(d.month)} {d.year}"
    partial = format_partial_ds260_date(val)
    return partial or ""


# Dấu ngăn cách KHOẢNG thời gian: en/em-dash, 'to'/'đến', mũi tên — HOẶC dấu '-' CÓ khoảng trắng
# hai bên. Bắt buộc có space quanh '-' để KHÔNG cắt nhầm '01-01-2010' (dấu '-' trong ngày dd-mm-yyyy).
_RANGE_SEP_RE = re.compile(r"\s+(?:–|—|->|=>|to|đến|den)\s+|\s+-\s+", re.IGNORECASE)
_OPEN_ENDED = {"now", "present", "current", "nay", "hien tai", "hiện tại", "den nay", "đến nay"}


def _format_range_endpoint(token: str) -> str:
    t = (token or "").strip()
    if not t:
        return ""
    if t.lower() in _OPEN_ENDED:
        return "Present"
    return format_ds260_display_date(t) or t


def format_ds260_display_date_range(val: str) -> str:
    """Chuẩn hoá khoảng thời gian → 'DD Mon YYYY - DD Mon YYYY' (mỗi đầu theo chuẩn ngày DS-260).

    'Aug 15, 2004 - Jun 01, 2008' → '15 Aug 2004 - 01 Jun 2008'; giữ 'Present' cho đầu mở
    (Now/nay). Không tách được (không phải khoảng) → thử format như 1 ngày, không được thì giữ nguyên.
    """
    v = (val or "").strip()
    if not v:
        return ""
    v = re.sub(r"^\s*(?:from|từ|tu)\s+", "", v, flags=re.IGNORECASE)
    parts = _RANGE_SEP_RE.split(v, maxsplit=1)
    if len(parts) != 2:
        return format_ds260_display_date(v) or v
    return f"{_format_range_endpoint(parts[0])} - {_format_range_endpoint(parts[1])}"


def format_sections_date_display(sections_out: list) -> None:
    """Chuẩn hóa mọi trường ngày trên form DS-260 (Review + export) về 'DD Mon YYYY'.

    Gồm cả field KHOẢNG thời gian ('_period': thời gian học) → 'DD Mon YYYY - DD Mon YYYY'.
    """
    for sec in sections_out:
        for field in sec.get("fields", []):
            key = field.get("key", "")
            val = (field.get("value") or "").strip()
            if not val:
                continue
            if is_date_range_field_key(key):
                field["value"] = format_ds260_display_date_range(val)
            elif is_date_field_key(key):
                formatted = format_ds260_display_date(val)
                if formatted:
                    field["value"] = formatted
                    # Đọc được nhưng nguồn nhập nhằng dd/mm ↔ mm/dd → đánh dấu để
                    # validate cảnh báo; người review phải đối chiếu giấy gốc.
                    if is_ambiguous_numeric_date(val):
                        field["date_note"] = {"code": "ambiguous_date", "raw": val}
                elif looks_like_date_but_unparsed(val):
                    # Trước đây giữ nguyên chuỗi thô (vd. '01/26/1986') → lệch định dạng
                    # với mọi ô ngày khác mà KHÔNG ai biết. Nay để TRỐNG + cảnh báo.
                    field["value"] = ""
                    field["date_note"] = {"code": "unparsed_date", "raw": val}


def partial_date_warning_message(field_label: str, raw_val: str, display_val: str) -> str:
    return (
        f"{field_label}: ngày thiếu ngày cụ thể — xuất \"{display_val}\" "
        f"(nguồn: {raw_val})"
    )


def sanitize_date_values(values: dict[str, str]) -> dict[str, str]:
    """Format date keys — full and partial dates preserved for export."""
    out = dict(values)
    for key, val in list(out.items()):
        if not val or not is_date_field_key(key):
            continue
        out[key] = format_ds260_display_date(val)
    return out
