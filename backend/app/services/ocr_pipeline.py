import base64
import json
import re
from pathlib import Path

from openai import APIStatusError, RateLimitError
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.entities import Applicant, Document, DocumentStatus, ExtractedField
from app.services.document_registry import (
    RECORDABLE_DOC_TYPES,
    RECORDABLE_REGISTRY_BY_CODE,
    parse_document_filename,
)
from app.services.ds260_mapping import get_extract_keys_for_doc_type
from app.services.field_mapping import DOCUMENT_TYPES
from app.services.llm_client import get_ocr_client, get_openai_client, is_openai_configured
from app.services.llm_usage import UsageContext, chat_completion

QUOTA_WARNING = (
    "OpenAI hết quota/credits (lỗi 429). Đã dùng chế độ demo từ tên file — "
    "nạp tiền tại https://platform.openai.com/account/billing rồi upload lại."
)

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp", ".tif", ".tiff"}

CLASSIFICATION_PROMPT = """Bạn là hệ thống phân loại hồ sơ DS260 / định cư Mỹ.

Bước 1: Xác định loại tài liệu từ nội dung (ảnh/PDF). Các loại chuẩn:
- passport
- judicial_certificate
- divorce
- birth_certificate
- death_certificate
- marriage_certificate
- birth_certificate_child
- military_discharge

Các loại khác (nếu không thuộc 8 loại trên): visa, i20, i94, diploma_transcript, financial, employment_letter, address_document, ds260_customer_form, photo, other

ds260_customer_form = bản DS-260 khách tự khai (worksheet khách điền tay/đánh máy). Gồm cả:
(a) bản CŨ ImmiPath nhiều mục (cá nhân, hộ chiếu, ĐỊA CHỈ, LIÊN LẠC, MXH, cha/mẹ/phối ngẫu/con,
    công việc/học vấn…) — thường có nhãn tiếng Việt trong ngoặc và khối "From/To" cho địa chỉ;
(b) bản MỚI trùng mẫu DS-260 export.
Chọn loại này cho MỌI worksheet khách tự khai, kể cả khi có nhiều mục — KHÔNG hạ xuống "other" hay
"address_document". address_document chỉ dành cho hoá đơn/hợp đồng thuê/giấy xác nhận cư trú riêng lẻ.

Trả về ONLY valid JSON:
{"document_type": "<code>", "confidence": 0.0-1.0, "reason": "brief"}"""

EXTRACTION_PROMPT_TEMPLATE = """Bạn trích xuất dữ liệu có cấu trúc cho form DS260.

Loại tài liệu đã xác định: {doc_type}

CHỈ trích xuất các field thuộc loại tài liệu này — KHÔNG gộp field trùng tên từ loại khác.
Ví dụ passport có full_name; birth_certificate cũng có full_name — chỉ trích field của {doc_type}.

Trả về ONLY valid JSON:
{{
  "document_type": "{doc_type}",
  "fields": {{
    "<field_key>": {{"value": "<string or null>", "confidence": 0.0-1.0, "source_page": "page_1"}}
  }}
}}

Quy tắc:
- ISO dates YYYY-MM-DD khi có thể
- UPPERCASE cho tên như in trên giấy
- null chỉ khi thật sự không đọc được
- CHỈ dùng các key sau (không thêm key ngoài schema):
{expected_keys}"""


def _is_quota_error(exc: Exception) -> bool:
    if isinstance(exc, RateLimitError):
        return True
    if isinstance(exc, APIStatusError) and exc.status_code in (429, 402):
        return True
    msg = str(exc).lower()
    return "insufficient_quota" in msg or "exceeded your current quota" in msg


def _encode_image(path: Path) -> tuple[str, str]:
    suffix = path.suffix.lower()
    mime = "image/jpeg"
    if suffix == ".png":
        mime = "image/png"
    elif suffix == ".webp":
        mime = "image/webp"
    elif suffix == ".gif":
        mime = "image/gif"
    data = base64.standard_b64encode(path.read_bytes()).decode("utf-8")
    return mime, data


def _pdf_pages_to_images(path: Path, max_pages: int = 3, dpi: int = 180) -> list[Path]:
    """Render PDF pages to PNG for vision API. PyMuPDF first (no Poppler), then pdf2image."""
    images: list[Path] = []

    try:
        import fitz

        doc = fitz.open(str(path))
        for i in range(min(len(doc), max_pages)):
            # DPI trong tên cache → đổi DPI sẽ render lại, không dùng nhầm ảnh độ nét cũ.
            out = path.parent / f"{path.stem}_page{i + 1}_dpi{dpi}.png"
            if not out.exists() or out.stat().st_mtime < path.stat().st_mtime:
                pix = doc[i].get_pixmap(dpi=dpi)
                pix.save(str(out))
            images.append(out)
        doc.close()
        if images:
            return images
    except Exception:
        pass

    try:
        from pdf2image import convert_from_path

        rendered = convert_from_path(str(path), first_page=1, last_page=max_pages, dpi=dpi)
        for i, img in enumerate(rendered):
            out = path.parent / f"{path.stem}_page{i + 1}_dpi{dpi}.png"
            img.save(str(out), "PNG")
            images.append(out)
    except Exception:
        pass

    return images


def _pdf_text_excerpt(path: Path, max_chars: int = 12000) -> str:
    """Extract plain text from PDF pages (fallback when vision conversion unavailable)."""
    chunks: list[str] = []

    try:
        import fitz

        doc = fitz.open(str(path))
        for i in range(min(len(doc), 8)):
            text = (doc[i].get_text() or "").strip()
            if text:
                chunks.append(text)
            if sum(len(c) for c in chunks) >= max_chars:
                break
        doc.close()
    except Exception:
        pass

    if not chunks:
        try:
            from pypdf import PdfReader

            reader = PdfReader(str(path))
            for page in reader.pages[:8]:
                text = (page.extract_text() or "").strip()
                if text:
                    chunks.append(text)
                if sum(len(c) for c in chunks) >= max_chars:
                    break
        except Exception:
            pass

    merged = "\n\n".join(chunks).strip()
    if len(merged) > max_chars:
        merged = merged[:max_chars]
    return merged


# DS-260 worksheet (.docx) is long (full form ~60k chars) — cap generously so later sections
# (cha/mẹ, công việc/học vấn, du lịch, quân sự) không bị cắt khỏi prompt trích xuất.
_DOCX_MAX_CHARS = 80000


def _docx_text_excerpt(path: Path, max_chars: int = _DOCX_MAX_CHARS) -> str:
    """Extract text from a Word worksheet — paragraphs + table cells (DS-260 form is a label/value table)."""
    try:
        from docx import Document as _DocxDocument
    except ImportError:
        return ""
    try:
        doc = _DocxDocument(str(path))
    except Exception:
        return ""
    parts: list[str] = []
    for para in doc.paragraphs:
        t = (para.text or "").strip()
        if t:
            parts.append(t)
    for table in doc.tables:
        for row in table.rows:
            cells = [(c.text or "").strip() for c in row.cells]
            line = " | ".join(c for c in cells if c)
            if line:
                parts.append(line)
    merged = "\n".join(parts).strip()
    return merged[:max_chars]


def _resolve_document_images(file_path: Path, max_pages: int = 3, dpi: int = 180) -> tuple[list[Path], str]:
    """
    Return image paths suitable for vision API and a hint about source.
    hint: direct_image | pdf_pages | pdf_text_only | filename_only
    """
    suffix = file_path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        return [file_path], "direct_image"
    if suffix == ".pdf":
        pages = _pdf_pages_to_images(file_path, max_pages=max_pages, dpi=dpi)
        if pages:
            return pages, "pdf_pages"
        text = _pdf_text_excerpt(file_path)
        if text:
            return [], "pdf_text_only"
        return [], "filename_only"
    if suffix == ".txt":
        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore").strip()
            if text:
                return [], "plain_text"
        except OSError:
            pass
        return [], "filename_only"
    if suffix in {".xlsx", ".xls"}:
        try:
            from openpyxl import load_workbook

            wb = load_workbook(file_path, read_only=True, data_only=True)
            cells: list[str] = []
            for sheet in wb.worksheets[:3]:
                for row in sheet.iter_rows(max_row=80, values_only=True):
                    cells.extend(str(c) for c in row if c is not None)
            wb.close()
            text = " ".join(cells).strip()
            if text:
                return [], "plain_text"
        except Exception:
            pass
        return [], "filename_only"
    if suffix == ".docx":
        if _docx_text_excerpt(file_path):
            return [], "plain_text"
        return [], "filename_only"
    return [], "filename_only"


def _mock_classification(filename: str) -> dict:
    registry_type, _is_exc = parse_document_filename(filename)
    if registry_type:
        defn = registry_type
        return {"document_type": defn, "confidence": 0.85, "reason": "filename registry (standard template)"}

    name = filename.lower()
    rules = [
        ("passport", "passport"),
        ("visa", "visa"),
        ("i-20", "i20"),
        ("i20", "i20"),
        ("i-94", "i94"),
        ("i94", "i94"),
        ("birth", "birth_certificate"),
        ("marriage", "marriage_certificate"),
        ("divorce", "divorce"),
        ("judicial", "judicial_certificate"),
        ("death", "death_certificate"),
        ("military", "military_discharge"),
        ("transcript", "diploma_transcript"),
        ("diploma", "diploma_transcript"),
        ("employment", "employment_letter"),
        ("financial", "financial"),
        ("address", "address_document"),
        ("utility", "address_document"),
        ("lease", "address_document"),
        ("residence", "address_document"),
        ("ds260", "ds260_customer_form"),
        ("ds-260", "ds260_customer_form"),
        ("photo", "photo"),
    ]
    for token, doc_type in rules:
        if token in name:
            return {"document_type": doc_type, "confidence": 0.75, "reason": "filename heuristic (demo)"}
    return {"document_type": "other", "confidence": 0.5, "reason": "unknown (demo)"}


def _mock_extraction(doc_type: str, filename: str) -> dict:
    keys = get_extract_keys_for_doc_type(doc_type)
    if not keys:
        keys = ["notes"]
    person = _person_name_from_filename(filename)
    fields = {}
    for key in keys:
        if key in {"family_name", "surname", "last_name"}:
            val = person["family_name"] or "NGUYEN"
        elif key in {"given_names", "given_name", "first_name"}:
            val = person["given_names"] or "VAN A"
        elif key in {"birth_city", "city_of_birth"}:
            val = "HANOI"
        elif key in {"birth_state", "state_of_birth"}:
            val = ""
        elif key in {"birth_country", "country_of_birth"}:
            val = "VIETNAM"
        elif key in {"full_name", "name", "child_full_name"}:
            val = person["full_name"] or "NGUYEN VAN A"
        elif key in {"date_of_birth", "child_date_of_birth"}:
            val = "1990-01-15"
        elif key == "passport_number":
            val = "B1234567"
        elif key == "nationality":
            val = "VIETNAM"
        elif key in {"gender", "sex", "child_gender"}:
            val = "MALE"
        elif key in {"service_from_date", "service_to_date"}:
            val = "2010-01-01" if "from" in key else "2012-01-01"
        else:
            val = f"[demo — {doc_type}]"
        fields[key] = {"value": val, "confidence": 0.5, "source_page": "demo"}
    return {"document_type": doc_type, "fields": fields}


_BIRTH_CERT_KEY_REMAP: dict[str, str] = {
    "mother_full_name": "mother_name",
    "mother_residence": "mother_address",
    "mother_nationality": "mother_country",
    "mother_year_of_birth": "mother_date_of_birth",
    "mother_birth_date": "mother_date_of_birth",
    "mother_dob": "mother_date_of_birth",
    "mother_birth_place": "mother_place_of_birth",
    "mother_city_of_birth": "mother_birth_city",
    "father_full_name": "father_name",
    "father_residence": "father_address",
    "father_nationality": "father_country",
    "father_year_of_birth": "father_date_of_birth",
    "father_birth_date": "father_date_of_birth",
    "father_dob": "father_date_of_birth",
    "father_birth_place": "father_place_of_birth",
    "father_city_of_birth": "father_birth_city",
}


def _field_meta_value(meta: object) -> str:
    if isinstance(meta, dict):
        val = meta.get("value")
        return "" if val is None else str(val).strip()
    return "" if meta is None else str(meta).strip()


def _coerce_birth_certificate_extraction(extraction: dict) -> dict:
    """Remap common LLM keys on English/VN birth certs before schema filter."""
    fields = extraction.get("fields")
    if not isinstance(fields, dict):
        return extraction

    remapped: dict[str, dict] = {}
    for key, meta in fields.items():
        if not isinstance(meta, dict):
            continue
        target = _BIRTH_CERT_KEY_REMAP.get(key, key)
        existing = remapped.get(target)
        if existing and _field_meta_value(existing) and not _field_meta_value(meta):
            continue
        if existing and _field_meta_value(existing) and _field_meta_value(meta):
            if len(_field_meta_value(meta)) <= len(_field_meta_value(existing)):
                continue
        remapped[target] = meta

    extraction["fields"] = remapped
    return extraction


def _filter_extraction_to_schema(doc_type: str, extraction: dict) -> dict:
    """Chỉ giữ field thuộc schema loại tài liệu — tránh merge field trùng tên."""
    allowed = set(get_extract_keys_for_doc_type(doc_type))
    if not allowed:
        return extraction
    fields = extraction.get("fields")
    if not isinstance(fields, dict):
        return extraction
    extraction["fields"] = {k: v for k, v in fields.items() if k in allowed}
    extraction["document_type"] = doc_type
    return extraction


def _resolve_document_type(ai_doc_type: str, filename: str) -> tuple[str, bool]:
    """
    AI phân loại trước; tên file chỉ fallback khi AI không nhận ra loại chuẩn.
    _new → variant exception, cùng doc_type (alias normalization).
    """
    registry_type, is_exception = parse_document_filename(filename or "")
    ai = (ai_doc_type or "other").strip().lower()

    if ai in RECORDABLE_DOC_TYPES:
        return ai, is_exception
    if registry_type:
        return registry_type, is_exception
    if ai in DOCUMENT_TYPES:
        return ai, is_exception
    return "other", is_exception


def _person_name_from_filename(filename: str) -> dict[str, str]:
    """Extract uppercase person name hints from filename."""
    stem = Path(filename).stem
    text = re.sub(r"[_\-]+", " ", stem)
    text = re.sub(r"[()]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()

    # If filename has "A & B", take the first person as primary subject.
    if "&" in text:
        text = text.split("&", 1)[0].strip()

    stop_words = {
        "PASSPORT", "PHOTO", "BIRTH", "CERTIFICATE", "JUDICIAL", "DIVORCE",
        "DECREE", "MARRIAGE", "VISA", "I", "I20", "I94", "COPY", "SCAN", "ORIGINAL",
        "DEATH", "MILITARY", "DISCHARGE", "CHILD", "NEW",
    }
    parts = []
    for p in text.upper().split(" "):
        if not p or p in stop_words:
            continue
        if p.isdigit():
            continue
        parts.append(p)

    if not parts:
        return {"full_name": "", "family_name": "", "given_names": ""}
    full_name = " ".join(parts)
    family_name = parts[0]
    given_names = " ".join(parts[1:]) if len(parts) > 1 else ""
    return {
        "full_name": full_name,
        "family_name": family_name,
        "given_names": given_names,
    }


def _is_empty_value(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _fallback_enrich_extraction(doc_type: str, filename: str, extraction: dict) -> dict:
    """If OCR returns many nulls, enrich from filename."""
    fields = extraction.get("fields")
    if not isinstance(fields, dict):
        return extraction

    person = _person_name_from_filename(filename)

    def set_if_empty(key: str, value: str, conf: float = 0.35) -> None:
        if not value:
            return
        if key not in fields:
            fields[key] = {"value": value, "confidence": conf, "source_page": "filename"}
            return
        meta = fields.get(key) or {}
        if not isinstance(meta, dict):
            return
        if _is_empty_value(meta.get("value")):
            meta["value"] = value
            meta["confidence"] = max(float(meta.get("confidence") or 0), conf)
            meta["source_page"] = meta.get("source_page") or "filename"
            fields[key] = meta

    set_if_empty("full_name", person["full_name"])
    set_if_empty("name", person["full_name"])
    set_if_empty("surname", person["family_name"])
    set_if_empty("family_name", person["family_name"])
    set_if_empty("given_name", person["given_names"].split(" ")[0] if person["given_names"] else "")
    set_if_empty("given_names", person["given_names"])

    extraction["fields"] = fields
    return extraction


def _parse_json_response(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    return json.loads(text)


def _build_llm_user_content(
    *,
    filename: str,
    image_paths: list[Path],
    hint: str,
    file_path: Path,
    task: str,
) -> list[dict] | str:
    """Build OpenAI user message content (multimodal or text-only)."""
    if image_paths:
        parts: list[dict] = []
        intro = f"{task} Filename: {filename}."
        if hint == "pdf_pages":
            intro += f" Document has {len(image_paths)} page image(s) — read all pages."
        parts.append({"type": "text", "text": intro})
        for i, img_path in enumerate(image_paths):
            mime, data = _encode_image(img_path)
            parts.append({"type": "text", "text": f"--- Page {i + 1} ---"})
            parts.append(
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{data}", "detail": "high"}}
            )
        return parts

    if hint == "pdf_text_only":
        pdf_text = _pdf_text_excerpt(file_path)
        return (
            f"{task} Filename: {filename}. PDF scanned without image renderer — use OCR text below:\n\n"
            f"{pdf_text}"
        )

    if hint == "plain_text":
        cap = 12000
        try:
            if file_path.suffix.lower() in {".xlsx", ".xls"}:
                from openpyxl import load_workbook

                wb = load_workbook(file_path, read_only=True, data_only=True)
                cells: list[str] = []
                for sheet in wb.worksheets[:3]:
                    for row in sheet.iter_rows(max_row=80, values_only=True):
                        cells.extend(str(c) for c in row if c is not None)
                wb.close()
                text = "\n".join(cells)
            elif file_path.suffix.lower() == ".docx":
                text = _docx_text_excerpt(file_path)
                cap = _DOCX_MAX_CHARS
            else:
                text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            text = ""
        return f"{task} Filename: {filename}. Document text:\n\n{text[:cap]}"

    return f"{task} Filename: {filename}. No image available — infer document type from filename only."


async def _openai_classify(
    file_path: Path, filename: str, db: AsyncSession, ctx: UsageContext
) -> dict:
    image_paths, hint = _resolve_document_images(file_path)
    content = _build_llm_user_content(
        filename=filename,
        image_paths=image_paths,
        hint=hint,
        file_path=file_path,
        task="Classify this document.",
    )
    messages: list[dict] = [
        {"role": "system", "content": CLASSIFICATION_PROMPT},
        {"role": "user", "content": content},
    ]

    response = await chat_completion(
        db,
        operation="document.classify",
        context=ctx,
        messages=messages,
        client=get_ocr_client(),
        model=settings.ocr_model,
        response_format={"type": "json_object"},
        temperature=0,
    )
    return _parse_json_response(response.choices[0].message.content or "{}")


ADDRESS_EXTRACT_HINT = """
For ADDRESS / CONTACT documents (utility bill, lease, DS-160 address or contact section), extract:

Address: current_address, city, state/province, postal_code, country, address_from_date,
other_addresses_since_16 (YES/NO), other_addresses_history (prior residences with date ranges).

Phone: primary_phone_number, secondary_phone_number, work_phone_number,
other_phones_used (YES/NO), other_phones_history (numbers used in last 5 years if YES).

Email: email_address, other_emails_used (YES/NO), other_emails_history (other emails in last 5 years if YES).

Social media: social_media_platform (e.g. Facebook – Display Name), social_media_identifier (profile URL or handle),
other_social_media_used (YES/NO), other_social_history (other platforms in last 5 years if YES, e.g. Zalo – Name).
"""

SOCIAL_EXTRACT_HINT = """
For DS-160 SOCIAL MEDIA section, extract:
social_media_platform, social_media_identifier (URL or short link),
other_social_media_used (YES/NO), other_social_history (platform + identifier if YES).
"""

DS260_REFERENCE_EXTRACT_HINT = """
This is a CUSTOMER-REFERENCE upload (_new) — often a filled DS-260 worksheet scan.
Extract ALL DS-260 sections visible on the document, including:

ADDRESS (section 3): current_address, address_city, address_state, postal_code, address_country,
address_from_date, other_addresses_since_16 (Yes/No), other_addresses_history (prior addresses with dates).
The legacy/old-version worksheet prints A.3 as repeated labeled blocks (Vietnamese + English), e.g.:
  (Street)(Đường) ... (City)(Thành phố) ... (State/Province)(Tỉnh/Bang) ...
  (Country)(Quốc gia) ... (Postal code)(Mã bưu điện) ...
  From (Từ tháng/năm)(MM/YYYY) ... To (Đến tháng/năm)(MM/YYYY) ...
Read EVERY block. The block whose To date is the most recent / blank / "present" is the CURRENT
address → current_address (Street), address_city (City), address_state (State/Province),
address_country (Country), postal_code, address_from_date (that block's From). Put each earlier
block on its own line in other_addresses_history as "Street, City, State, Country (MM/YYYY–MM/YYYY)"
and set other_addresses_since_16 = Yes. Disregard impossible To dates (To before From — OCR/typo)
when choosing the current block.

CONTACT (section 4): primary_phone_number, secondary_phone_number, work_phone_number,
other_phones_used (Yes/No), other_phones_history,
email_address, other_emails_used (Yes/No), other_emails_history.

SOCIAL MEDIA (section 5): social_media_platform, social_media_identifier,
other_social_media_used (Yes/No), other_social_history.

RESIDENCE-HISTORY rules (the form's "Lưu ý") — these add ADDRESS entries to
other_addresses_history, they are NOT child/birth data:
  - time spent studying or working in another locality → the real address there;
  - (male) military service → the address(es) while serving;
  - (female) gave birth in another locality → that locality's address.
Capture each such period as its own line in other_addresses_history
("Street, City, State, Country (MM/YYYY–MM/YYYY)") and set other_addresses_since_16 = Yes.

Use Yes/No for yes-no questions. Dates as YYYY-MM-DD or dd/mm/yyyy as printed.
"""

PASSPORT_EXTRACT_HINT = """
For PASSPORT documents (especially Vietnamese passport), extract ALL visible fields:

Personal: full_name, family_name, given_names, date_of_birth (YYYY-MM-DD),
place_of_birth (full text as printed — used for State/Province and Country of Birth on DS-260),
birth_city if shown separately, gender/sex (M/F or MALE/FEMALE), nationality,
id_card_number (Số CMND/CCCD / ID card N°).

Do NOT copy nationality into birth_country — country of birth is derived from place_of_birth separately.
Do NOT extract birth_state or birth_country as separate fields unless explicitly printed on the passport.

Passport document: passport_type or type (e.g. P), country_code (e.g. VNM),
passport_number, issue_date, expiration_date/expiry_date,
place_of_issue / issuing_authority (e.g. Cục Quản lý xuất nhập cảnh),
issuing_country if shown separately from place of issue.

Use ISO dates YYYY-MM-DD when possible. Names as printed on passport (uppercase OK).
"""

JUDICIAL_EXTRACT_HINT = """
For JUDICIAL CERTIFICATE (lý lịch tư pháp), extract:
full_name, date_of_birth, nationality, father_name, mother_name,
document_number, issue_date, document_type.
"""

BIRTH_CERT_EXTRACT_HINT = """
For BIRTH CERTIFICATE (giấy khai sinh chủ hồ sơ — applicant's own birth cert), extract ALL visible fields.

Applicant: full_name, date_of_birth (YYYY-MM-DD), place_of_birth, gender, registration_number.

English translated Vietnamese birth certificates (header "BIRTH CERTIFICATE", "Socialist Republic of Vietnam")
use labeled blocks — map them exactly:
  Mother block:
    "Mother's full name" → mother_name (also split mother_surname + mother_given_names if possible)
    "Year of birth" (often full date like 01 January 1954) → mother_date_of_birth as YYYY-MM-DD
    "Nationality" under mother → mother_country (e.g. Vietnamese)
    "Residence" under mother → mother_address AND mother_place_of_birth (full address)
    City in residence (e.g. Da Nang City) → mother_city
  Father block (same pattern):
    father_name, father_date_of_birth, father_country, father_address/father_place_of_birth, father_city

Vietnamese originals: mother_surname/mother_given_names, mother_date_of_birth, mother_birth_city,
mother_place_of_birth, mother_country.

If the document has NO father or mother information, leave all corresponding parent fields empty.
Use ISO dates YYYY-MM-DD. Do not use applicant nationality for parent country fields.
Do NOT skip parent date/address/nationality when they are printed on the certificate.
"""

DIVORCE_EXTRACT_HINT = """
For DIVORCE DECREE, extract BOTH parties:
husband_full_name, wife_full_name, husband_date_of_birth, wife_date_of_birth,
marriage_date, divorce_date, document_number, document_type.
If date of birth is printed for either party, use ISO YYYY-MM-DD.
Names UPPERCASE as printed (strip titles like MR./MRS. only in values, not keys).
"""

MARRIAGE_CERT_EXTRACT_HINT = """
For MARRIAGE CERTIFICATE (giấy kết hôn / giấy chứng nhận kết hôn), extract BOTH parties:

Husband (chồng): husband_full_name, husband_surname, husband_given_names,
husband_date_of_birth, husband_birth_city, husband_place_of_birth, husband_birth_country,
husband_address, husband_occupation.

Wife (vợ): wife_full_name, wife_surname, wife_given_names,
wife_date_of_birth, wife_birth_city, wife_place_of_birth, wife_birth_country,
wife_address, wife_occupation.

Marriage: marriage_date (YYYY-MM-DD), marriage_place (full), marriage_city, marriage_state, marriage_country.
document_number / registration_number if shown.
Use ISO dates. Names UPPERCASE as printed.
"""

DEATH_EXTRACT_HINT = """
For DEATH CERTIFICATE, extract:
deceased_full_name, date_of_death, place_of_death, relationship_to_applicant, document_number.
"""

CHILD_BIRTH_EXTRACT_HINT = """
For BIRTH CERTIFICATE CHILD (giấy khai sinh con), extract:
child_full_name, child_date_of_birth, child_place_of_birth,
child_birth_city, child_birth_state, child_birth_country, child_gender,
father_name, mother_name, registration_number.
Use ISO dates YYYY-MM-DD. Names UPPERCASE as printed.
If place of birth is one line, also split into city/state/country when possible.
"""

MILITARY_EXTRACT_HINT = """
For MILITARY DISCHARGE, extract:
full_name, military_country, military_branch, military_rank, military_specialty,
service_from_date, service_to_date, document_number.
"""

DS260_CUSTOMER_FORM_EXTRACT_HINT = """
This is a FULL CUSTOMER DS-260 WORKSHEET (ImmiPath form — all sections). Extract EVERY filled field.

This is often a SCANNED, HANDWRITTEN form — read each page carefully, including later pages
(security questions, Social Security). Read the customer's answer written after each label.
Name handling — read EXACTLY as written, do not guess or merge:
  - "Surnames (Họ)" = family name ONLY (e.g. LE, HUYNH, LAM); "Given Names (Tên)" = the rest
    (e.g. VAN TOT, THI KIM PHUC, THI MUOI). Keep father/mother/spouse surname vs given separate.
  - NEVER put the form header/title into a name field: ignore "DS-260", "DS 260", "DS260",
    "KHACH KHAI", "BANG CAU HOI" — these are NOT the applicant's name.
Free-text answers (10-year job history, military service, prior addresses, travel) — transcribe the
WHOLE text verbatim, do not shorten to "Yes". If a long answer is hard to read, capture what is legible.

PERSONAL (section 1): applicant_name, applicant_name_native, other_name_used, other_names,
gender/sex, current_marital_status, date_of_birth, birth_city, birth_state, birth_country,
nationality, id_card_number.

PASSPORT (section 2): passport_number, passport_type, country_code, passport_issue_date,
passport_expiration_date, passport_place_of_issue, passport_issuing_country,
other_nationality_used, other_nationality_history.

ADDRESS (section 3): current_address, address_city/current_city, address_state/current_state,
postal_code, address_country/current_country, address_from_date,
other_addresses_since_16 (Yes/No), other_addresses_history.
The legacy/old-version worksheet prints A.3 as repeated labeled blocks (Vietnamese + English), e.g.:
  (Street)(Đường) ... (City)(Thành phố) ... (State/Province)(Tỉnh/Bang) ...
  (Country)(Quốc gia) ... (Postal code)(Mã bưu điện) ...
  From (Từ tháng/năm)(MM/YYYY) ... To (Đến tháng/năm)(MM/YYYY) ...
Read EVERY block. The block whose To date is the most recent / blank / "present" is the CURRENT
address → current_address (Street), address_city (City), address_state (State/Province),
address_country (Country), postal_code, address_from_date (that block's From). Put each earlier
block on its own line in other_addresses_history as "Street, City, State, Country (MM/YYYY–MM/YYYY)"
and set other_addresses_since_16 = Yes. Disregard impossible To dates (To before From — OCR/typo)
when choosing the current block.
RESIDENCE-HISTORY rules (the form's "Lưu ý") add ADDRESS entries to other_addresses_history — they
are NOT child/birth data: time studying/working in another locality → that real address; (male)
military service → the address while serving; (female) gave birth in another locality → that
locality's address. List each as its own line and set other_addresses_since_16 = Yes.

CONTACT (section 4): primary_phone_number, secondary_phone_number, work_phone_number,
other_phones_used (Yes/No), other_phones_history,
email_address, other_emails_used (Yes/No), other_emails_history.

SOCIAL (section 5): social_media_platform, social_media_identifier,
other_social_media_used (Yes/No), other_social_history.

FATHER: father_surname, father_given_names, father_date_of_birth, father_birth_city,
father_birth_state, father_birth_country, father_is_living, father_death_year,
father_address/current_address (in father section), father_city, father_state, father_country.

MOTHER: mother_surname, mother_given_names, mother_date_of_birth, mother_birth_city,
mother_birth_state, mother_birth_country, mother_is_living, mother_death_year,
mother_address, mother_city, mother_state, mother_country.

SPOUSE: spouse_surname, spouse_given_names, spouse_full_name, spouse_date_of_birth,
spouse_birth_city, spouse_birth_state, spouse_birth_country, spouse_address,
spouse_occupation, spouse_marriage_date, spouse_marriage_city, spouse_marriage_state,
spouse_marriage_country, marriage_husband_name, marriage_wife_name.

PREVIOUS SPOUSE / DIVORCE: previous_spouses_used, previous_spouse_full_name,
previous_spouse_date_of_birth, previous_divorce_date, previous_marriage_date.

CHILDREN: children_used (Yes/No), children_count,
child_1_full_name, child_1_date_of_birth, child_1_birth_city, child_1_birth_state, child_1_birth_country,
child_2_full_name, child_2_date_of_birth, child_3_full_name, child_3_date_of_birth.

WORK / EDUCATION (section D) — Vietnamese header "CÔNG VIỆC / HỌC VẤN", "Work /Education /Training":
primary_occupation (NGHỀ NGHIỆP CHÍNH, e.g. Owner/Manager/Student),
occupation_other_specify (NGÀNH NGHỀ ghi rõ, e.g. Tailor),
present_employer (CÔNG TY hiện tại / trường học hiện tại, e.g. Self-employed),
employer_address, employer_city, employer_state, employer_postal_code, employer_country,
job_title, employment_start_date,
other_occupation_used (Yes/No), other_occupation_detail,
prior_jobs_10_years_used (Yes/No),
prior_jobs_history = FULL narrative of past 10 years employment exactly as written, keep every line
  (e.g. "From 01 January 2009 to 31 December 2023 / Occupation: Manager / Company name: ... /
   Company address: ... / Supervisor name: ... / Supervisor phone number: ...").
EDUCATION (cấp 2/cấp 3/đại học) — for each level capture name, address and period "from ... to ...":
middle_school_name (Cấp 2 = Trung học cơ sở / THCS / Secondary), middle_school_address, middle_school_period,
high_school_name (Cấp 3 = Trung học phổ thông / THPT / Highschool), high_school_address, high_school_period,
college_name (Cao đẳng/Đại học), college_address, college_major, college_period.
Map by level: "Trung học cơ sở"/"THCS" → middle_school_*, "Trung học phổ thông"/"THPT" → high_school_*.

MILITARY: military_country, military_branch, military_rank, military_specialty,
military_service_start, military_service_end.

Use mapping keys above (English snake_case). Yes/No for yes-no questions.
Dates as printed (dd/mm/yyyy or month/year). Vietnamese section headers: THÔNG TIN CÁ NHÂN, HỘ CHIẾU, ĐỊA CHỈ, CÔNG VIỆC/HỌC VẤN, THÔNG TIN LIÊN LẠC, MẠNG XÃ HỘI, THÔNG TIN CỦA CHA/MẸ/PHỐI NGẪU/CON.
"""

APPLICATION_FORM_EXTRACT_HINT = """
IMMIGRATION APPLICATION FORM — DS-260 Part D (Work / Education / Training).

WORK: primary_occupation, occupation_other_specify, present_employer, employer_name,
employer_address, employer_city, employer_state, employer_postal_code, employer_country,
job_title, employment_start_date, prior_jobs_history.

EDUCATION: middle_school_name (Cấp 2 / Trung học cơ sở / THCS),
middle_school_address, middle_school_period,
high_school_name (Cấp 3 / Trung học phổ thông / THPT), high_school_address, high_school_period,
college_name, college_address, college_major, college_period.

Yes/No for yes-no questions. Dates as printed.
"""

DOC_TYPE_EXTRACT_HINTS: dict[str, str] = {
    "passport": PASSPORT_EXTRACT_HINT,
    "birth_certificate": BIRTH_CERT_EXTRACT_HINT,
    "judicial_certificate": JUDICIAL_EXTRACT_HINT,
    "divorce": DIVORCE_EXTRACT_HINT,
    "marriage_certificate": MARRIAGE_CERT_EXTRACT_HINT,
    "death_certificate": DEATH_EXTRACT_HINT,
    "birth_certificate_child": CHILD_BIRTH_EXTRACT_HINT,
    "military_discharge": MILITARY_EXTRACT_HINT,
    "ds260_customer_form": DS260_CUSTOMER_FORM_EXTRACT_HINT,
    "application_form": APPLICATION_FORM_EXTRACT_HINT,
}


async def _openai_extract(
    file_path: Path, doc_type: str, filename: str, db: AsyncSession, ctx: UsageContext
) -> dict:
    from app.services.document_registry import parse_document_filename
    from app.services.ds260_conflicts import LUONG1_DOC_TYPES
    from app.services.field_mapping import CONTACT_AND_SOCIAL_MAP

    expected_keys = get_extract_keys_for_doc_type(doc_type)
    if not expected_keys:
        from app.services.field_mapping import FIELD_MAP

        expected_keys = list(FIELD_MAP.get(doc_type, {}).keys())
    extra = DOC_TYPE_EXTRACT_HINTS.get(doc_type, "")
    if doc_type == "ds260_customer_form":
        extra = DS260_CUSTOMER_FORM_EXTRACT_HINT + (extra or "")
    elif doc_type not in RECORDABLE_REGISTRY_BY_CODE and doc_type in {
        "address_document",
        "financial",
        "employment_letter",
        "application_form",
    }:
        extra = ADDRESS_EXTRACT_HINT + SOCIAL_EXTRACT_HINT

    _, is_exception = parse_document_filename(filename)
    if is_exception and doc_type in LUONG1_DOC_TYPES:
        extra = (extra or "") + DS260_REFERENCE_EXTRACT_HINT
        expected_keys = list(
            dict.fromkeys([*expected_keys, *CONTACT_AND_SOCIAL_MAP.keys()])
        )
    prompt = EXTRACTION_PROMPT_TEMPLATE.format(
        doc_type=doc_type,
        expected_keys=", ".join(expected_keys) or "any relevant fields for this document type",
    ) + extra
    # DS-260 worksheet khách khai thường là bản SCAN/VIẾT TAY nhiều trang (≈18 trang) →
    # đọc hết trang + render DPI cao hơn cho rõ nét chữ tay.
    is_ds260_ws = doc_type == "ds260_customer_form"
    image_paths, hint = _resolve_document_images(
        file_path,
        max_pages=3
        if doc_type == "passport"
        else (
            4
            if doc_type in {"birth_certificate", "marriage_certificate"}
            else (20 if is_ds260_ws else 2)
        ),
        dpi=300 if is_ds260_ws else 180,
    )
    content = _build_llm_user_content(
        filename=filename,
        image_paths=image_paths,
        hint=hint,
        file_path=file_path,
        task="Extract all fields from this document.",
    )
    messages: list[dict] = [
        {"role": "system", "content": prompt},
        {"role": "user", "content": content},
    ]

    response = await chat_completion(
        db,
        operation="document.extract",
        context=UsageContext(
            user_id=ctx.user_id,
            applicant_id=ctx.applicant_id,
            document_id=ctx.document_id,
            filename=filename,
            doc_type=doc_type,
        ),
        messages=messages,
        client=get_ocr_client(),
        model=settings.ocr_model,
        response_format={"type": "json_object"},
        temperature=0,
    )
    return _parse_json_response(response.choices[0].message.content or "{}")


async def classify_document(
    file_path: Path, filename: str, db: AsyncSession, ctx: UsageContext
) -> tuple[dict, str | None]:
    if not is_openai_configured():
        return _mock_classification(filename), None
    try:
        return await _openai_classify(file_path, filename, db, ctx), None
    except Exception as exc:
        if _is_quota_error(exc):
            return _mock_classification(filename), QUOTA_WARNING
        raise


async def extract_document(
    file_path: Path, doc_type: str, filename: str, db: AsyncSession, ctx: UsageContext
) -> tuple[dict, str | None]:
    if not is_openai_configured():
        raw = _fallback_enrich_extraction(doc_type, filename, _mock_extraction(doc_type, filename))
        return _filter_extraction_to_schema(doc_type, raw), None
    try:
        extracted = await _openai_extract(file_path, doc_type, filename, db, ctx)
        enriched = _fallback_enrich_extraction(doc_type, filename, extracted)
        if doc_type == "birth_certificate":
            enriched = _coerce_birth_certificate_extraction(enriched)
        if doc_type == "ds260_customer_form":
            from app.services.ds260_customer_keys import coerce_ds260_customer_extraction

            enriched = coerce_ds260_customer_extraction(enriched)
        return _filter_extraction_to_schema(doc_type, enriched), None
    except Exception as exc:
        if _is_quota_error(exc):
            raw = _fallback_enrich_extraction(doc_type, filename, _mock_extraction(doc_type, filename))
            return _filter_extraction_to_schema(doc_type, raw), QUOTA_WARNING
        raise


async def save_extracted_fields(db: AsyncSession, document_id, extraction: dict) -> list[ExtractedField]:
    await db.execute(delete(ExtractedField).where(ExtractedField.document_id == document_id))
    fields_data = extraction.get("fields", {})
    saved: list[ExtractedField] = []
    for key, meta in fields_data.items():
        if not isinstance(meta, dict):
            continue
        ef = ExtractedField(
            document_id=document_id,
            field_key=key,
            field_value=meta.get("value"),
            confidence=meta.get("confidence"),
            source_page=meta.get("source_page"),
        )
        db.add(ef)
        saved.append(ef)
    await db.flush()
    return saved


async def process_document(db: AsyncSession, document: Document) -> Document:
    file_path = Path(document.file_path)
    document.status = DocumentStatus.processing
    await db.flush()

    applicant = await db.get(Applicant, document.applicant_id)
    usage_ctx = UsageContext(
        user_id=applicant.user_id if applicant else None,
        applicant_id=document.applicant_id,
        document_id=document.id,
        filename=document.original_filename,
    )

    warnings: list[str] = []

    try:
        classification, w1 = await classify_document(file_path, document.original_filename, db, usage_ctx)
        if w1:
            warnings.append(w1)

        ai_type = classification.get("document_type", "other")
        doc_type, is_exception = _resolve_document_type(ai_type, document.original_filename or "")
        document.document_type = doc_type
        document.registry_doc_type = doc_type if doc_type in RECORDABLE_DOC_TYPES else None
        document.is_exception = is_exception
        document.classification_confidence = float(classification.get("confidence", 0))

        extraction, w2 = await extract_document(file_path, doc_type, document.original_filename, db, usage_ctx)
        if w2 and w2 not in warnings:
            warnings.append(w2)

        await save_extracted_fields(db, document.id, extraction)

        document.status = DocumentStatus.extracted
        from datetime import datetime, timezone

        document.processed_at = datetime.now(timezone.utc)
        document.error_message = warnings[0] if warnings else None
    except Exception as exc:
        if _is_quota_error(exc):
            classification = _mock_classification(document.original_filename)
            ai_type = classification.get("document_type", "other")
            doc_type, is_exception = _resolve_document_type(ai_type, document.original_filename or "")
            document.document_type = doc_type
            document.registry_doc_type = doc_type if doc_type in RECORDABLE_DOC_TYPES else None
            document.is_exception = is_exception
            document.classification_confidence = float(classification.get("confidence", 0))
            extraction = _filter_extraction_to_schema(
                doc_type,
                _fallback_enrich_extraction(
                    doc_type, document.original_filename, _mock_extraction(doc_type, document.original_filename)
                ),
            )
            await save_extracted_fields(db, document.id, extraction)
            document.status = DocumentStatus.extracted
            from datetime import datetime, timezone

            document.processed_at = datetime.now(timezone.utc)
            document.error_message = QUOTA_WARNING
        else:
            document.status = DocumentStatus.failed
            document.error_message = str(exc)[:2000]

    await db.flush()
    return document
