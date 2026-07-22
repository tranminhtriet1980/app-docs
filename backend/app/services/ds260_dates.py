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

    m = re.match(r"^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$", val)
    if m:
        d, mo, y = m.groups()
        try:
            return date(int(y), int(mo), int(d))
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
