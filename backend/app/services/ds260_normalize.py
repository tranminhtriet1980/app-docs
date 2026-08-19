"""Shared value normalizers used across DS-260 mapping, conflicts, and export.

Centralizes gender and phone normalization so every call site (schema mapping,
conflict comparison, document registry, English-output formatting) agrees on the
same token set instead of drifting independently.
"""

from __future__ import annotations

import re

from app.services.birth_location import _strip_accents

_GENDER_MAP: dict[str, str] = {
    "m": "Male",
    "male": "Male",
    "nam": "Male",
    "man": "Male",
    "f": "Female",
    "female": "Female",
    "nu": "Female",
    "woman": "Female",
    "other": "Other",
    "khac": "Other",
}


def _normalize_token(value: str) -> str:
    text = _strip_accents((value or "").strip().lower())
    return re.sub(r"\s+", " ", text).strip()


def normalize_gender(value: str) -> str:
    """Male/Female/Other from any Vietnamese/English spelling (incl. compound strings
    like "NAM / M"). Unrecognized input is returned unchanged rather than forced to
    "Other" (khách yêu cầu: OCR gibberish must not silently become "Other" on the
    legal DS-260 form)."""
    v = (value or "").strip()
    if not v:
        return v
    token = _normalize_token(v)
    if token in _GENDER_MAP:
        return _GENDER_MAP[token]
    for part in re.split(r"[\s/,;]+", token):
        if part in _GENDER_MAP:
            return _GENDER_MAP[part]
    return v


def normalize_phone(value: str) -> str:
    """Digits-only VN phone number for comparison: strip international dialing prefix
    ('00'), then country code ('84'), then domestic trunk prefix ('0') — in that order,
    so '0084...', '84 0...', and '0...' all collapse to the same subscriber number."""
    digits = re.sub(r"\D", "", value or "")
    if not digits:
        return ""
    if digits.startswith("00"):
        digits = digits[2:]
    if digits.startswith("84") and len(digits) - 2 >= 9:
        digits = digits[2:]
    if digits.startswith("0"):
        digits = digits[1:]
    return digits


def format_vn_phone_display(value: str) -> str:
    """Chỉ chuẩn hoá số điện thoại VIỆT NAM (10 số, đầu 09/08/03/05) về +84.
    Các số khác (không phải VN mobile) → giữ nguyên."""
    if not value:
        return value
    digits = re.sub(r"\D", "", value)

    # Xác định mobile prefix VN
    def _to_international(d: str) -> str:
        # d = chuỗi 10 số, đầu 09/08/03/05 → format +84 XXX XXX XXX
        return f"+84 {d[1:4]} {d[4:7]} {d[7:]}"

    # +84 9XXXXXXXX → đúng 10 số sau mã nước
    if value.startswith("+84"):
        num = digits[2:]
        if len(num) == 10 and num[0] in ("9", "8", "3", "5"):
            return _to_international(num)
        return value  # không phải VN mobile → giữ nguyên

    # 00849XXXXXXXX → đúng 12 số
    if digits.startswith("0084"):
        num = digits[4:]
        if len(num) == 10 and num[0] in ("9", "8", "3", "5"):
            return _to_international(num)
        return value

    # 009XXXXXXXX → đúng 11 số (ít gặp)
    if digits.startswith("009"):
        num = digits[3:]
        if len(num) == 10 and num[0] in ("9", "8", "3", "5"):
            return _to_international(num)
        return value

    # 0XXXXXXXXXX → đúng 10 số
    if len(digits) == 10 and digits[0] in ("9", "8", "3", "5"):
        return _to_international(digits)

    # 84XXXXXXXX → đúng 11 số (ít gặp)
    if digits.startswith("84") and len(digits) == 11 and digits[2] in ("9", "8", "3", "5"):
        num = "0" + digits[2:]
        return _to_international(num)

    # Không phải VN mobile → giữ nguyên
    return value
