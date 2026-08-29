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
    """Chỉ chuẩn hoá số điện thoại VIỆT NAM (đầu 09/08/07/05/03) về +84 XXX XXX XXX.
    Các số khác (không phải VN mobile) → giữ nguyên."""
    if not value:
        return value
    raw = value.strip()
    digits = re.sub(r"\D", "", raw)

    def _to_international(d10: str) -> str:
        # d10 = chuỗi 10 số dạng 09XXXXXXXX -> format +84 XXX XXX XXX
        return f"+84 {d10[1:4]} {d10[4:7]} {d10[7:]}"

    vn_prefixes = ("9", "8", "7", "5", "3")

    # 1. 0084 + 9 số (13 số)
    if digits.startswith("0084") and len(digits) == 13 and digits[4] in vn_prefixes:
        return _to_international("0" + digits[4:])

    # 2. 84 + 9 số (11 số) hoặc +84
    if digits.startswith("84") and len(digits) == 11 and digits[2] in vn_prefixes:
        return _to_international("0" + digits[2:])

    # 3. 0 + 9 số (10 số) dạng 09xxxxxxxx
    if len(digits) == 10 and digits.startswith("0") and digits[1] in vn_prefixes:
        return _to_international(digits)

    # 4. Đúng 9 số dạng 9xxxxxxxx (thiếu số 0 hoặc +84)
    if len(digits) == 9 and digits[0] in vn_prefixes:
        return _to_international("0" + digits)

    return raw


def normalize_email(value: str) -> str:
    """Chuẩn hoá email về chữ thường (lowercase) toàn bộ."""
    v = (value or "").strip()
    if not v:
        return ""
    if v.upper() == "N/A":
        return "N/A"
    return v.lower()

