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


def is_birth_date_field_key(key: str) -> bool:
    """Field ngày SINH của bất kỳ ai (chủ hồ sơ/cha/mẹ/vợ chồng/con/lý lịch tư pháp...) — luôn
    kết thúc bằng 'date_of_birth' hoặc '_dob' trong toàn bộ ds260_mapping.json. Khách yêu cầu
    2026-08-12: ngày sinh CHỈ nhận giá trị đầy đủ ngày/tháng/năm, không dùng ngày thiếu."""
    k = (key or "").lower()
    return k.endswith("date_of_birth") or k.endswith("_dob")


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

    m_vn = re.search(r"(?i)(?:ngày\s*)?(\d{1,2})\s*tháng\s*(\d{1,2})\s*năm\s*(\d{4})", val)
    if m_vn:
        try:
            return date(int(m_vn.group(3)), int(m_vn.group(2)), int(m_vn.group(1)))
        except ValueError:
            pass

    for fmt in _FULL_DATE_TEXT_FORMATS:
        try:
            return datetime.strptime(val, fmt).date()
        except ValueError:
            continue
    return None


def format_partial_ds260_date(val: str) -> str | None:
    """
    Month/year or year-only → display string.
    2023-05 / 05/2023 → May 2023; 2023 → 2023.
    """
    val = (val or "").strip()
    if not val:
        return None

    m_vn_mo = re.search(r"(?i)(?:tháng\s*)?(\d{1,2})\s*năm\s*(\d{4})", val)
    if m_vn_mo:
        mo, y = int(m_vn_mo.group(1)), int(m_vn_mo.group(2))
        if 1 <= mo <= 12:
            return f"{mo:02d}/{y}"

    m = re.match(r"^(\d{4})-(\d{2})$", val)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return f"{mo:02d}/{y}"

    m = re.match(r"^(\d{1,2})[/.-](\d{4})$", val)
    if m:
        mo, y = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12:
            return f"{mo:02d}/{y}"

    m = re.match(r"^([A-Za-z]+)\s+(\d{4})$", val)
    if m:
        month_raw, year = m.group(1), m.group(2)
        try:
            mo = datetime.strptime(month_raw[:3], "%b").month
            return f"{mo:02d}/{year}"
        except ValueError:
            try:
                mo = datetime.strptime(month_raw, "%B").month
                return f"{mo:02d}/{year}"
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


def parse_date_lenient(val: str) -> tuple[date, str] | None:
    """Parse a date at whatever granularity is actually present, so callers can compare
    partial dates (mm/yyyy, yyyy) without treating them as unparseable. Returns
    (date, granularity) with granularity one of "day"/"month"/"year"; partial values
    resolve to the 1st of the month/year so comparisons stay orderable. None if the
    value can't be parsed at all."""
    val = (val or "").strip()
    if not val:
        return None
    full = parse_full_date(val)
    if full:
        return full, "day"
    partial = format_partial_ds260_date(val)
    if partial is None:
        return None
    m = re.match(r"^(\d{2})/(\d{4})$", partial)
    if m:
        mo, y = int(m.group(1)), int(m.group(2))
        return date(y, mo, 1), "month"
    m = re.match(r"^(\d{4})$", partial)
    if m:
        return date(int(m.group(1)), 1, 1), "year"
    return None


def format_ds260_export_date(val: str) -> str:
    """Ngày xuất Word theo mốc trọn, tháng viết tắt tiếng Anh (vd. '15 Aug 1990'); ngày chỉ có
    tháng/năm → 'Aug 1990'; chỉ có năm → '1990'. Parse được cả input đã qua display format
    (dd/mm/yyyy, mm/yyyy). Không parse được → giữ nguyên chuỗi gốc."""
    parsed = parse_date_lenient(val)
    if not parsed:
        return val or ""
    d, granularity = parsed
    if granularity == "day":
        return f"{d.day:02d} {d.strftime('%b')} {d.year}"
    if granularity == "month":
        return f"{d.strftime('%b')} {d.year}"
    return f"{d.year}"


def format_ds260_display_date(val: str) -> str:
    """Ngày đầy đủ (có ngày+tháng+năm, vd. ngày sinh) → dd/mm/yyyy; ngày chỉ có tháng/năm
    (vd. ngày nhập cư, mốc địa chỉ) → mm/yyyy; chỉ có năm → yyyy; else empty."""
    d = parse_full_date(val)
    if d:
        return f"{d.day:02d}/{d.month:02d}/{d.year}"
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


def _format_range_endpoint_export(token: str) -> str:
    """Format một đầu mốc của khoảng thời gian cho Word export — định dạng 'dd Mon yyyy'."""
    t = (token or "").strip()
    if not t:
        return ""
    if t.lower() in _OPEN_ENDED:
        return "Present"
    # Parse và format thành "dd Mon yyyy"
    d = parse_full_date(t)
    if d:
        return f"{d.day:02d} {d.strftime('%b')} {d.year}"
    return t  # giữ nguyên nếu không parse được


def format_ds260_display_date_range(val: str) -> str:
    """Chuẩn hoá khoảng thời gian → 'dd/mm/yyyy - dd/mm/yyyy' (mỗi đầu theo format_ds260_display_date).

    'Aug 15, 2004 - Jun 01, 2008' → '15/08/2004 - 01/06/2008'; giữ 'Present' cho đầu mở
    (Now/nay). Không tách được (không phải khoảng) → thử format như 1 ngày, không được thì giữ nguyên.
    Hỗ trợ chuỗi nhiều dòng (nhiều khoảng thời gian cách nhau bởi newline).
    """
    v = (val or "").strip()
    if not v:
        return ""
    if "\n" in v:
        lines = [format_ds260_display_date_range(line) for line in v.split("\n") if line.strip()]
        return "\n".join(lines)
    v = re.sub(r"^\s*(?:from|từ|tu)\s+", "", v, flags=re.IGNORECASE)
    parts = _RANGE_SEP_RE.split(v, maxsplit=1)
    if len(parts) != 2:
        return format_ds260_display_date(v) or v
    return f"{_format_range_endpoint(parts[0])} - {_format_range_endpoint(parts[1])}"


def format_ds260_export_date_range(val: str) -> str:
    """Format khoảng thời gian cho Word export — 'dd Mon yyyy - dd Mon yyyy'.

    '05/09/2007 - 30/05/2011' → '05 Sep 2007 - 30 May 2011'; giữ 'Present' cho đầu mở.
    Hỗ trợ chuỗi nhiều dòng (nhiều khoảng thời gian cách nhau bởi newline).
    """
    v = (val or "").strip()
    if not v:
        return ""
    if "\n" in v:
        lines = [format_ds260_export_date_range(line) for line in v.split("\n") if line.strip()]
        return "\n".join(lines)
    v = re.sub(r"^\s*(?:from|từ|tu)\s+", "", v, flags=re.IGNORECASE)
    parts = _RANGE_SEP_RE.split(v, maxsplit=1)
    if len(parts) != 2:
        # Không tách được → thử format như 1 ngày đầy đủ
        d = parse_full_date(v)
        if d:
            return f"{d.day} {d.strftime('%b')} {d.year}"
        return v
    return f"{_format_range_endpoint_export(parts[0])} - {_format_range_endpoint_export(parts[1])}"


def format_sections_date_display(sections_out: list) -> None:
    """Chuẩn hóa mọi trường ngày trên form DS-260 (Review + export): ngày đầy đủ → dd/mm/yyyy,
    ngày chỉ có tháng/năm (nhập cư, mốc địa chỉ...) → mm/yyyy.

    Gồm cả field KHOẢNG thời gian ('_period': thời gian học) → 'dd/mm/yyyy - dd/mm/yyyy'.
    Riêng field NGÀY SINH (is_birth_date_field_key): CHỈ nhận giá trị có đầy đủ ngày/tháng/năm —
    ngày sinh thiếu (chỉ tháng/năm hoặc chỉ năm) bị coi là chưa đủ, để trống + cảnh báo thay vì
    hiển thị ngày thiếu (khách yêu cầu 2026-08-12).
    """
    for sec in sections_out:
        for field in sec.get("fields", []):
            key = field.get("key", "")
            val = (field.get("value") or "").strip()
            if not val:
                continue
            if is_date_range_field_key(key):
                field["value"] = format_ds260_display_date_range(val)
            elif is_birth_date_field_key(key):
                d = parse_full_date(val)
                if d:
                    field["value"] = f"{d.day:02d}/{d.month:02d}/{d.year}"
                    if is_ambiguous_numeric_date(val):
                        field["date_note"] = {"code": "ambiguous_date", "raw": val}
                else:
                    field["value"] = ""
                    if format_partial_ds260_date(val) is not None:
                        field["date_note"] = {"code": "partial_birth_date_rejected", "raw": val}
                    else:
                        field["date_note"] = {"code": "unparsed_date", "raw": val}
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
