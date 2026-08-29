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


def normalize_person_name(text: str) -> str:
    """Chuẩn hoá HỌ TÊN để so khớp (khác chuỗi = khác người) — chỉ bỏ dấu + hạ chữ thường +
    gọn khoảng trắng/dấu câu.

    KHÔNG dùng normalize_location() cho việc này: hàm đó lọc bỏ từ ĐỊA DANH hành chính
    (phường/quận/huyện/xã/tỉnh/tp...) vì được thiết kế cho địa chỉ, và vô tình cắt mất tên
    người trùng các từ này — vd. "Nguyễn Minh Phương" từng bị normalize_location cắt còn
    "nguyen minh" (mất "Phương" vì trùng "phường"), khiến so khớp tên trong toàn hệ thống
    (dedupe con, khớp vợ/chồng, khớp thành viên hồ sơ theo tên OCR...) sai lệch cho bất kỳ
    ai có tên trùng từ hành chính (Phương/Phường, Quân/Quan, Xa...). Sự cố thực tế 2026-08-04.
    """
    text = _strip_accents((text or "").strip().lower())
    text = re.sub(r"[^\w\s]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


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


# Thuật ngữ hành chính VN → Anh. Tiếng Anh đặt thuật ngữ SAU tên ("Xã Bình Hưng" → "Binh Hung Commune").
# Khớp theo prefix accent-stripped; xếp cụm dài trước cụm ngắn ("thi xa" trước "xa").
_ADDRESS_PREFIX_TERMS: list[tuple[str, str]] = [
    ("thanh pho", "City"),
    ("thi xa", "Town"),
    ("thi tran", "Town"),
    ("tx", "Town"),
    ("tt", "Town"),
    ("phuong", "Ward"),
    ("quan", "District"),
    ("huyen", "District"),
    ("xa", "Commune"),
    ("tinh", "Province"),
    ("khu pho", "Quarter"),
    ("ap", "Hamlet"),
    ("thon", "Hamlet"),
    ("duong", "Street"),
    ("kiet", "Alley"),
    ("hem", "Alley"),
    ("ngo", "Alley"),
]

# Viết tắt nguyên cụm → tên đầy đủ.
_ADDRESS_WHOLE_MAP: dict[str, str] = {
    "tphcm": "Ho Chi Minh",
    "tp hcm": "Ho Chi Minh",
    "tp.hcm": "Ho Chi Minh",
    "tp ho chi minh": "Ho Chi Minh",
}


_HOUSE_NUMBER_TERM_RE = re.compile(
    r"(?i)^(?P<num>[\d/]+)\s+(?P<term>duong|kiet|hem|ngo)\s+(?P<rest>.+)$"
)
_HOUSE_NUMBER_TERM_ENGLISH = {"duong": "Street", "kiet": "Alley", "hem": "Alley", "ngo": "Alley"}


def _format_address_segment(seg: str) -> str:
    ascii_seg = re.sub(r"\s+", " ", _strip_accents(seg.strip())).strip()
    if not ascii_seg:
        return ""
    low = ascii_seg.lower()
    if low in _ADDRESS_WHOLE_MAP:
        return _ADDRESS_WHOLE_MAP[low]
    m = re.match(r"(?i)^quoc\s*lo\s+(.+)$", ascii_seg)  # Quốc lộ 50 → Highway 50
    if m:
        return f"Highway {m.group(1).strip().title()}".strip()
    # Số nhà dính liền thuật ngữ trong cùng 1 đoạn (vd. "196 Kiet 7", "60/14 Duong Thich Buu
    # Dang") — vòng lặp suffix bên dưới chỉ khớp khi thuật ngữ đứng ĐẦU đoạn nên bỏ sót case này.
    m2 = _HOUSE_NUMBER_TERM_RE.match(ascii_seg)
    if m2:
        term = m2.group("term").lower()
        rest = m2.group("rest").strip()
        num = m2.group("num")
        english = _HOUSE_NUMBER_TERM_ENGLISH[term]
        if term == "duong":
            return f"{num} {rest.title()} {english}".strip()
        rest_fmt = rest if re.fullmatch(r"\d+", rest) else rest.title()
        return f"{num} {english} {rest_fmt}".strip()
    for prefix, suffix in _ADDRESS_PREFIX_TERMS:
        if low.startswith(prefix + " "):
            rest = ascii_seg[len(prefix) :].strip()
            if not rest:
                break
            # Đơn vị đánh số: "Quận 1" → "District 1"; có tên: "Xã Bình Hưng" → "Binh Hung Commune".
            if re.fullmatch(r"\d+", rest):
                return f"{suffix} {rest}"
            return f"{rest.title()} {suffix}".strip()
    return ascii_seg.title()


_VN_PRESENT_MARKER_RE = re.compile(
    r"(?<=[–—-])\s*(hiện\s*tại|hien\s*tai|đến\s*nay|den\s*nay|hiện\s*nay|hien\s*nay|nay)\s*(?=\)|,|;|$)",
    re.IGNORECASE,
)


def normalize_present_marker(text: str) -> str:
    """DS-260 chỉ dùng tiếng Anh — chuẩn hoá mốc thời gian mở "hiện tại/đến nay/nay" (mọi cách
    viết có/không dấu) ở cuối khoảng ngày thành "Present". Dùng chung cho cả OCR extraction
    (ocr_pipeline.py) và export (export_ds260.py) — 2 điểm dữ liệu có thể lẫn tiếng Việt vào
    field lẽ ra chỉ tiếng Anh (other_addresses_history…)."""
    if not text:
        return text
    return _VN_PRESENT_MARKER_RE.sub("Present", text)


def _format_address_line(raw: str) -> str:
    parts = [_format_address_segment(s) for s in re.split(r"\s*,\s*", raw)]
    return ", ".join(p for p in parts if p)


def format_address_english(text: str) -> str:
    """Địa chỉ VN → Anh: bỏ dấu, dịch thuật ngữ hành chính (Xã→Commune, Huyện/Quận→District,
    Quốc lộ→Highway, Phường→Ward, Ấp/Thôn→Hamlet…) và đặt thuật ngữ sau tên theo văn phong Anh.

    Giữ NGUYÊN ranh giới xuống dòng (vd. other_addresses_history — mỗi mốc ở/khai một dòng) — xử
    lý riêng từng dòng rồi ghép lại bằng '\\n', KHÔNG format cả khối làm một: nếu gộp chung, dòng
    trống giữa 2 dòng không có dấu phẩy sẽ bị `_format_address_segment` (dùng \\s+ nuốt luôn \\n)
    xoá mất, làm mọi mốc thời gian dính liền thành 1 dòng và bỏ sót việc dịch ở giữa khối (báo lỗi
    thực tế 2026-08-07: "196 Kiet 7" chỉ được dịch thành "Alley 7" ở dòng đầu, các dòng sau y
    nguyên vì lọt ra ngoài phạm vi so khớp)."""
    raw = (text or "").strip()
    if not raw:
        return ""
    if "\n" in raw:
        return "\n".join(_format_address_line(line.strip()) for line in raw.split("\n") if line.strip())
    return _format_address_line(raw)


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


# Địa chỉ/trường học đôi khi 1 giấy tờ ghi tiếng Việt, giấy khác ghi bản dịch tiếng Anh (vd. "Trung
# tâm giáo dục thường xuyên huyện Châu Đức" ↔ "Continuing Education Center of Chau Duc District")
# — dịch cụm/từ hành chính + giáo dục thường gặp sang tiếng Anh trước khi tokenize để so khớp
# xuyên ngôn ngữ (dùng cho Conflict, KHÔNG dùng để format giá trị hiển thị/export). Cụm dài xếp
# trước cụm ngắn để khớp đúng cụm trước khi rơi xuống từ đơn.
_PLACE_SCHOOL_VOCAB_VI_TO_EN: tuple[tuple[str, str], ...] = tuple(
    (term, english.lower()) for term, english in _ADDRESS_PREFIX_TERMS
) + (
    ("trung tam giao duc thuong xuyen", "continuing education center"),
    ("giao duc thuong xuyen", "continuing education"),
    ("trung hoc pho thong", "high school"),
    ("trung hoc co so", "secondary school"),
    ("tieu hoc", "elementary school"),
    ("cao dang", "college"),
    ("dai hoc", "university"),
    ("truong", "school"),
    ("trung tam", "center"),
    ("giao duc", "education"),
    ("thuong xuyen", "continuing"),
    ("cong lap", "public"),
    ("dan lap", "private"),
    ("tu thuc", "private"),
)


def _translate_place_school_vocab(accent_stripped_lower_text: str) -> str:
    text = accent_stripped_lower_text
    for vi, en in _PLACE_SCHOOL_VOCAB_VI_TO_EN:
        text = re.sub(rf"\b{re.escape(vi)}\b", en, text)
    return text


_PLACE_SCHOOL_STOPWORDS = frozenset({"the", "and", "of", "a", "an", "in", "at"})


def place_or_school_identity_tokens(text: str) -> set[str]:
    """Token hoá địa danh/tên trường để so khớp mờ, xuyên ngôn ngữ (dịch từ vựng VN→EN trước khi
    tách từ — xem _PLACE_SCHOOL_VOCAB_VI_TO_EN) — dùng cho Conflict, không dùng để hiển thị."""
    plain = _translate_place_school_vocab(_strip_accents((text or "").strip().lower()))
    cleaned = re.sub(r"[^a-z0-9\s]", " ", plain)
    return {t.upper() for t in cleaned.split() if len(t) >= 2 and t not in _PLACE_SCHOOL_STOPWORDS}


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
        if len(alias) >= 3 and (norm == alias or norm in alias or _words_contain(norm, alias)):
            return country
    return ""


def _words_contain(text: str, word: str) -> bool:
    """True when word appears as a complete word in text (word-boundary match)."""
    return bool(__import__("re").search(r"\b" + __import__("re").escape(word) + r"\b", text))


def _match_location(segment: str) -> str:
    _, location_to_country = _load_mapping()
    norm = normalize_location(segment)
    if not norm:
        return ""
    if norm in location_to_country:
        return location_to_country[norm]
    for loc, country in sorted(location_to_country.items(), key=lambda x: -len(x[0])):
        if len(loc) >= 3 and (norm == loc or loc in norm or _words_contain(norm, loc)):
            return country
    return ""


# Thành phố trực thuộc trung ương — DS-260: ghi vào ô City, ô State = N/A.
# Tỉnh — ghi vào ô State; ô City = tên TP/thị xã thuộc tỉnh nếu đọc được, ngược lại 'N/A'.
# "Thua Thien Hue" là tên entry cũ trong province map; Huế lên TP trực thuộc TW từ 01/2025.
VN_MUNICIPALITIES = frozenset(
    {"Ho Chi Minh", "Ha Noi", "Da Nang", "Hai Phong", "Can Tho", "Thua Thien Hue"}
)

# Tên hiển thị trên DS-260 khi khác tên entry trong province map.
_MUNICIPALITY_DISPLAY_NAME = {"Thua Thien Hue": "Hue"}


def municipality_display_name(name: str) -> str:
    """Tên TP trực thuộc TW dùng để in lên DS-260 ('Thua Thien Hue' → 'Hue')."""
    return _MUNICIPALITY_DISPLAY_NAME.get(name, name)

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
    name, _alias = find_vn_locality_match(text, only_municipality=only_municipality)
    return name


def find_vn_locality_match(
    text: str, *, only_municipality: bool = False
) -> tuple[str, str]:
    """Như find_vn_locality nhưng trả kèm ALIAS đã khớp.

    Cần alias để biết chuỗi khớp nhờ tên TỈNH ('Khanh Hoa') hay nhờ tên THÀNH PHỐ
    thuộc tỉnh ('Nha Trang') — trường hợp sau phải giữ tên TP cho ô City of Birth.
    """
    norm = normalize_location(text)
    if not norm:
        return "", ""
    for alias, name, is_muni in _locality_index():
        if only_municipality and not is_muni:
            continue
        if alias in norm:
            return name, alias
    return "", ""


def _alias_is_province_name(alias_norm: str, province: str) -> bool:
    """True khi alias chính là biến thể tên TỈNH (không phải tên TP thuộc tỉnh)."""
    return alias_norm == normalize_location(province)


def find_city_alias_in_province(text: str, province: str) -> str:
    """Tên TP/thị xã THUỘC `province` xuất hiện trong chuỗi, else ''.

    Quét toàn bộ alias của tỉnh thay vì lấy alias khớp đầu tiên: chuỗi
    'Nha Trang, Khanh Hoa' chứa cả tên TP lẫn tên tỉnh, phải lấy được 'Nha Trang'.
    """
    norm = normalize_location(text)
    if not norm or not province:
        return ""

    # Bỏ tên TỈNH khỏi chuỗi trước đã: 'ba ria vung tau' CHỨA cả 'ba ria' lẫn 'vung tau',
    # quét thẳng sẽ tưởng nhầm là có tên thành phố trong khi chỉ có tên tỉnh.
    province_aliases = sorted(
        (a for a, n, _ in _locality_index() if n == province and _alias_is_province_name(a, province)),
        key=len,
        reverse=True,
    )
    residual = norm
    for alias in province_aliases:
        residual = residual.replace(alias, " ")

    best = ""
    for alias, name, _is_muni in _locality_index():
        if name != province or _alias_is_province_name(alias, province):
            continue
        if alias in residual and len(alias) > len(best):
            best = alias
    return best


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
    name = _municipality_alias_set().get(norm, "")
    return municipality_display_name(name) if name else ""


def looks_like_address_or_facility(text: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False
    return bool(_FACILITY_RE.search(raw) or _ADDRESS_RE.search(raw))


def split_birthplace_city_state(*blobs: str) -> tuple[str, str] | None:
    """
    Quy ước DS-260 (nơi sinh VN):
      - TP trực thuộc TW      → (City=TP, State='N/A')
      - TP/thị xã thuộc tỉnh  → (City=TP, State=Tỉnh)   vd. ('Nha Trang', 'Khanh Hoa')
      - Chỉ có tên tỉnh       → (City='N/A', State=Tỉnh)
      - Bệnh viện/địa chỉ     → ('N/A', 'N/A')
      - Không nhận diện được & rỗng → None (giữ nguyên)

    Địa danh đã sáp nhập (2025) giữ TÊN CŨ đúng như trên giấy khai sinh/hộ chiếu nộp kèm,
    để form không lệch với giấy tờ gốc.
    """
    text = " , ".join(b for b in blobs if (b or "").strip())
    if not text.strip():
        return None
    muni, _ = find_vn_locality_match(text, only_municipality=True)
    if muni:
        return municipality_display_name(muni), "N/A"
    prov, _alias = find_vn_locality_match(text)
    if prov:
        # Có tên TP thuộc tỉnh trong chuỗi (vd. 'Nha Trang' của Khanh Hoa) → giữ tên TP,
        # đừng bỏ đi thành 'N/A' như quy ước cũ.
        city_alias = find_city_alias_in_province(text, prov)
        if city_alias:
            return format_place_name_title(city_alias), prov
        return "N/A", prov
    if looks_like_address_or_facility(text):
        return "N/A", "N/A"
    return None


def extract_city_token(raw: str | None) -> str:
    """Lấy tên thành phố từ chuỗi nơi đăng ký/kết hôn (vd. 'UBND Phường X, Thành Phố Huế' → 'Hue')."""
    segments = [s.strip() for s in (raw or "").split(",") if s.strip()]
    for seg in segments:
        if _CITY_MARKER_RE.search(seg) and not _FACILITY_RE.search(seg):
            token = _CITY_MARKER_RE.sub(" ", seg)
            token = re.sub(r"(?i)\b(tinh|tỉnh|province)\b", " ", token)
            token = re.sub(r"\s+", " ", token).strip(" ,.-")
            if token:
                return format_place_name_title(token)
    muni = find_vn_locality(raw or "", only_municipality=True)
    if muni:
        return muni
    return ""


def derive_birth_state_from_place(place_of_birth: str | None) -> str:
    """State/Province of Birth = copy PlaceOfBirth directly."""
    return (place_of_birth or "").strip()


def derive_city_from_place(place_of_birth: str | None) -> str:
    """City of Birth — thường là phần cuối trong chuỗi nơi sinh (ward, district, city)."""
    raw = (place_of_birth or "").strip()
    if not raw:
        return ""
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    if len(parts) > 1 and parts[-1].lower() in {"vietnam", "viet nam", "vn", "vietnamese", "usa", "us", "united states"}:
        candidate = parts[-2]
    else:
        candidate = parts[-1] if parts else raw
    candidate = re.sub(r"(?i)^thành phố\s+", "", candidate).strip()
    candidate = re.sub(r"(?i)^city\s+", "", candidate).strip()
    return candidate


def derive_country_from_place(place_of_birth: str | None) -> str:
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
