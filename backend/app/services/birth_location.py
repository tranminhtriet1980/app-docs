"""Derive DS-260 birth location fields from passport place_of_birth."""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path

LOCATION_MAP_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "doc_schemas" / "location_to_country.json"
)

_LOCATION_SUFFIXES = re.compile(
    r"(?i)\b(thanh pho|thành phố|tp\.?|tinh|tỉnh|city|province|state|region|district|quan|quận|huyen|huyện|xa|xã|phuong|phường)\b"
)


def _strip_accents(text: str) -> str:
    text = text.replace("\u0110", "D").replace("\u0111", "d")
    normalized = unicodedata.normalize("NFD", text)
    return "".join(ch for ch in normalized if unicodedata.category(ch) != "Mn")


def format_person_name_ascii(text: str) -> str:
    """Họ tên cho DS-260/CEAC: không dấu, IN HOA (vd. ĐẶNG VĂN HÙNG → DANG VAN HUNG)."""
    if not (text or "").strip():
        return ""
    cleaned = re.sub(r"\s+", " ", _strip_accents(text.strip()))
    return cleaned.upper()


def format_place_name_title(text: str) -> str:
    """Địa danh cho DS-260: không dấu, chữ cái đầu mỗi từ viết hoa (ĐÀ NẴNG → Da Nang)."""
    if not (text or "").strip():
        return ""
    cleaned = re.sub(r"\s+", " ", _strip_accents(text.strip()))
    return cleaned.title()


def format_birth_city_display(text: str) -> str:
    """Thành phố nơi sinh: Title Case, bỏ hậu tố ' City' (Da Nang City → Da Nang)."""
    val = format_place_name_title(text)
    return re.sub(r"\s+City$", "", val, flags=re.I).strip()


def format_nationality_country(text: str) -> str:
    """
    Quốc tịch / Country of Origin → tên quốc gia chuẩn (vd. VIỆT NAM / VIETNAMESE → Vietnam).
    Cùng format với Country of Birth.
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    for part in re.split(r"\s*/\s*", raw):
        country = _match_country_alias(part.strip())
        if country:
            return country
    country = _match_country_alias(raw)
    if country:
        return country
    return format_place_name_title(raw.split("/")[0].strip())


def normalize_location(text: str) -> str:
    text = _strip_accents((text or "").strip().lower())
    text = _LOCATION_SUFFIXES.sub(" ", text)
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


@lru_cache(maxsize=1)
def _load_mapping() -> tuple[dict[str, str], dict[str, str]]:
    """Returns (alias -> country, location -> country)."""
    with LOCATION_MAP_PATH.open(encoding="utf-8") as f:
        data = json.load(f)

    alias_to_country: dict[str, str] = {}
    for country, aliases in (data.get("country_aliases") or {}).items():
        alias_to_country[normalize_location(country)] = country
        for alias in aliases:
            alias_to_country[normalize_location(alias)] = country

    location_to_country: dict[str, str] = {}
    for country, locations in (data.get("location_to_country") or {}).items():
        for loc in locations:
            location_to_country[normalize_location(loc)] = country

    return alias_to_country, location_to_country


def _match_country_alias(segment: str) -> str:
    alias_to_country, _ = _load_mapping()
    norm = normalize_location(segment)
    if not norm:
        return ""
    if norm in alias_to_country:
        return alias_to_country[norm]
    for alias, country in sorted(alias_to_country.items(), key=lambda x: -len(x[0])):
        if len(alias) >= 3 and (norm == alias or alias in norm or norm in alias):
            return country
    return ""


def _match_location(segment: str) -> str:
    _, location_to_country = _load_mapping()
    norm = normalize_location(segment)
    if not norm:
        return ""
    if norm in location_to_country:
        return location_to_country[norm]
    for loc, country in sorted(location_to_country.items(), key=lambda x: -len(x[0])):
        if len(loc) >= 3 and (loc in norm or norm in loc):
            return country
    return ""


def derive_birth_state_from_place(place_of_birth: str) -> str:
    """State/Province of Birth = copy PlaceOfBirth directly."""
    return (place_of_birth or "").strip()


def derive_city_from_place(place_of_birth: str) -> str:
    """City of Birth — thường là phần cuối trong chuỗi nơi sinh (ward, district, city)."""
    raw = (place_of_birth or "").strip()
    if not raw:
        return ""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    candidate = parts[-1] if parts else raw
    candidate = re.sub(r"(?i)^thành phố\s+", "", candidate).strip()
    candidate = re.sub(r"(?i)^city\s+", "", candidate).strip()
    return candidate


def derive_country_from_place(place_of_birth: str) -> str:
    """
    Country of Birth from place_of_birth via location-to-country mapping.
    Never uses nationality.
    """
    raw = (place_of_birth or "").strip()
    if not raw:
        return ""

    segments = [s.strip() for s in raw.split(",") if s.strip()]
    for segment in reversed(segments):
        country = _match_country_alias(segment)
        if country:
            return country

    for segment in segments:
        country = _match_location(segment)
        if country:
            return country

    country = _match_country_alias(raw)
    if country:
        return country

    return _match_location(raw)
