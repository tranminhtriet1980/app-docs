"""Derive Vietnam postal codes from province/city/state text for DS-260 export."""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from app.services.birth_location import derive_country_from_place, normalize_location

POSTAL_MAP_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "doc_schemas" / "province_to_postal_code.json"
)

_VN_MARKERS = frozenset(
    {
        "vietnam",
        "viet nam",
        "việt nam",
        "vn",
        "vnm",
        "socialist republic of vietnam",
    }
)


@lru_cache(maxsize=1)
def _load_postal_index() -> list[tuple[str, str]]:
    """Sorted (alias_norm, postal_code) longest aliases first."""
    with POSTAL_MAP_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    rows: list[tuple[str, str]] = []
    for prov in data.get("provinces") or []:
        code = str(prov.get("postal_code") or "").strip()
        if not code:
            continue
        names = [prov.get("name", "")] + list(prov.get("aliases") or [])
        for name in names:
            norm = normalize_location(str(name))
            if norm:
                rows.append((norm, code))
    rows.sort(key=lambda x: -len(x[0]))
    return rows


def _is_vietnam_country(country: str) -> bool:
    norm = normalize_location(country)
    return norm in _VN_MARKERS or "viet" in norm


def _match_province_postal(text: str) -> str:
    norm = normalize_location(text)
    if not norm:
        return ""
    index = _load_postal_index()
    for alias, code in index:
        if alias == norm:
            return code
    for alias, code in index:
        if len(alias) >= 3 and (alias in norm or norm in alias):
            return code
    return ""


def derive_postal_code_from_location(
    *,
    state: str = "",
    city: str = "",
    country: str = "",
    address: str = "",
) -> str:
    """
    Map tỉnh/thành VN → mã bưu điện 6 số.
    Chỉ trả mã khi có state/city/address và (country trống hoặc là Việt Nam).
    """
    state = (state or "").strip()
    city = (city or "").strip()
    country = (country or "").strip()
    address = (address or "").strip()

    if not state and not city and not address:
        return ""

    if country and not _is_vietnam_country(country):
        inferred = derive_country_from_place(", ".join(x for x in (state, city, address) if x))
        if inferred != "Vietnam":
            return ""

    for text in (state, city):
        code = _match_province_postal(text)
        if code:
            return code

    if address:
        segments = [s.strip() for s in re.split(r"[,;]", address) if s.strip()]
        for segment in reversed(segments):
            code = _match_province_postal(segment)
            if code:
                return code
        code = _match_province_postal(address)
        if code:
            return code

    return ""
