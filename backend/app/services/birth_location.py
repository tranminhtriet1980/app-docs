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


# Thành phố trực thuộc trung ương — DS-260: ghi vào ô City, ô State = N/A.
# Tỉnh — ghi vào ô State, ô City = N/A (theo quy ước điền tay của nghiệp vụ).
VN_MUNICIPALITIES = frozenset(
    {"Ho Chi Minh", "Ha Noi", "Da Nang", "Hai Phong", "Can Tho"}
)

PROVINCE_MAP_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "doc_schemas" / "province_to_postal_code.json"
)

# Cơ sở y tế / cơ quan / địa chỉ — KHÔNG phải tên thành phố/tỉnh nơi sinh.
_FACILITY_RE = re.compile(
    r"(?i)(benh vien|bệnh viện|hospital|tram y te|trạm y tế|nha ho sinh|nhà hộ sinh|"
    r"nha bao sanh|nhà bảo sanh|khoa san|khoa sản|clinic|ubnd|uy ban|ủy ban|"
    r"benh xa|bệnh xá|y te|trung tam)"
)
_ADDRESS_RE = re.compile(
    r"(?i)(\d+/\d+|^\s*\d+\s|\bto\s+\d+\b|\btổ\s+\d+\b|\bso\s+\d+\b|\bsố\s+\d+\b|"
    r"\bap\s|\bấp\s|\bhamlet\b|\bstreet\b|\bst\.|\bduong\b|\bđường\b|\bkhu pho\b|\bkhu phố\b)"
)
_CITY_MARKER_RE = re.compile(r"(?i)\b(thanh pho|thành phố|tp\.?|city)\b")


@lru_cache(maxsize=1)
def _locality_index() -> list[tuple[str, str, bool]]:
    """(alias_norm, canonical_province, is_municipality) — sorted dài→ngắn."""
    with PROVINCE_MAP_PATH.open(encoding="utf-8") as f:
        data = json.load(f)
    idx: list[tuple[str, str, bool]] = []
    seen: set[str] = set()
    for prov in data.get("provinces") or []:
        name = (prov.get("name") or "").strip()
        if not name:
            continue
        is_muni = name in VN_MUNICIPALITIES
        for alias in (name, *(prov.get("aliases") or [])):
            norm = normalize_location(alias)
            if len(norm) >= 3 and norm not in seen:
                seen.add(norm)
                idx.append((norm, name, is_muni))
    idx.sort(key=lambda x: -len(x[0]))
    return idx


def find_vn_locality(text: str, *, only_municipality: bool = False) -> str:
    """Tên tỉnh/TP trực thuộc TW chuẩn nếu nhận diện được trong chuỗi, else ''."""
    norm = normalize_location(text)
    if not norm:
        return ""
    for alias, name, is_muni in _locality_index():
        if only_municipality and not is_muni:
            continue
        if alias in norm:
            return name
    return ""


@lru_cache(maxsize=1)
def _municipality_alias_set() -> dict[str, str]:
    """alias_norm → tên TP trực thuộc TW (khớp CHÍNH XÁC cả chuỗi)."""
    out: dict[str, str] = {}
    for alias, name, is_muni in _locality_index():
        if is_muni:
            out[alias] = name
    return out


def canonical_vn_city(text: str) -> str:
    """
    Chuẩn hóa tên TP trực thuộc TW (vd. 'Hcm'/'HCMC'/'Go Vap' → 'Ho Chi Minh').
    CHỈ khớp chính xác alias municipality để KHÔNG biến 'Hue' thành tên tỉnh.
    """
    norm = normalize_location(text)
    if not norm:
        return ""
    return _municipality_alias_set().get(norm, "")


def looks_like_address_or_facility(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    return bool(_FACILITY_RE.search(raw) or _ADDRESS_RE.search(raw))


def split_birthplace_city_state(*blobs: str) -> tuple[str, str] | None:
    """
    Quy ước DS-260 (nơi sinh VN):
      - TP trực thuộc TW  → (City=TP, State='N/A')
      - Tỉnh              → (City='N/A', State=Tỉnh)
      - Bệnh viện/địa chỉ → ('N/A', 'N/A')
      - Không nhận diện được & rỗng → None (giữ nguyên)
    """
    text = " , ".join(b for b in blobs if (b or "").strip())
    if not text.strip():
        return None
    muni = find_vn_locality(text, only_municipality=True)
    if muni:
        return muni, "N/A"
    prov = find_vn_locality(text)
    if prov:
        return "N/A", prov
    if looks_like_address_or_facility(text):
        return "N/A", "N/A"
    return None


def extract_city_token(raw: str) -> str:
    """Lấy tên thành phố từ chuỗi nơi đăng ký/kết hôn (vd. 'UBND Phường X, Thành Phố Huế' → 'Hue')."""
    segments = [s.strip() for s in (raw or "").split(",") if s.strip()]
    for seg in segments:
        if _CITY_MARKER_RE.search(seg) and not _FACILITY_RE.search(seg):
            token = _CITY_MARKER_RE.sub(" ", seg)
            token = re.sub(r"(?i)\b(tinh|tỉnh|province)\b", " ", token)
            token = re.sub(r"\s+", " ", token).strip(" ,.-")
            if token:
                return format_place_name_title(token)
    muni = find_vn_locality(raw, only_municipality=True)
    if muni:
        return muni
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
