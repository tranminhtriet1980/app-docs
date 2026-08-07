"""
DS-260 — Luồng 1 vs nguồn đối chiếu + worksheet khách khai.

Luồng 1 (variant=standard): file mẫu chuẩn — Passport, Birth certificate,
JUDICIAL CERTIFICATE, Marriage certificate.

Nguồn đối chiếu (variant=exception, hậu tố _new): người khai upload để đối chiếu.
Worksheet DS-260 (ds260_customer_form): form khách điền đầy đủ.

Khi hai nguồn khác nhau → Conflict; người dùng chọn giá trị → DS-260 dùng giá trị đã chọn.
Mặc định (chưa xung đột / chưa chọn): ưu tiên Luồng 1 (standard).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ApplicantDocRecord, Conflict, ConflictStatus, ProfileField
from app.services.doc_record_sync import list_doc_records

# Luồng 1 — file mẫu chuẩn
LUONG1_DOC_TYPES: frozenset[str] = frozenset(
    {
        "passport",
        "birth_certificate",
        "judicial_certificate",
        "marriage_certificate",
        "application_form",
    }
)

DS260_CONFLICT_PREFIX = "ds260."
WORKSHEET_CONFLICT_SEGMENT = "document_vs_worksheet"
DS260_MANUAL_SEGMENT = "manual"
IDENTITY_OUTLIER_SEGMENT = "identity_outlier"
CHILD_IDENTITY_SEGMENT = "child_identity"
CHILD_PARENT_IDENTITY_SEGMENT = "child_parent_identity"

def _application_form_worksheet_keys() -> frozenset[str]:
    """Section D (công việc/học vấn) — mọi field nguồn application_form, trừ narrative tự do
    (work_prior_jobs_history: so khớp chuỗi tuyệt đối luôn khác nhau dù nội dung đúng)."""
    from app.services.ds260_mapping import flatten_ds260_mappings

    return frozenset(
        k
        for k, m in flatten_ds260_mappings().items()
        if m.document == "application_form" and k != "work_prior_jobs_history"
    )


# DS-260 mapping keys compared: official (Luồng 1 resolved) vs ds260_customer_form
WORKSHEET_COMPARE_KEYS: frozenset[str] = frozenset(
    {
        "applicant_name",
        "date_of_birth",
        "gender",
        "nationality",
        "place_of_birth",
        "passport_number",
        "passport_issue_date",
        "passport_expiration_date",
        "current_marital_status",
        "current_address",
        "current_city",
        "current_state",
        "postal_code",
        "current_country",
        "primary_phone",
        "email",
        # Thông tin cha/mẹ — trước đây KHÔNG nằm trong danh sách này nên birth_certificate và
        # worksheet DS-260 khách khai chưa bao giờ được đối chiếu (báo lỗi thực tế 2026-08-05).
        # Đương đơn: nguồn chính thức là birth_certificate của chính họ (mapping.document mặc
        # định — không cần override). Con cái: birth_certificate của con không tồn tại (con chỉ
        # có birth_certificate_child do cha/mẹ khai, chỉ có father_name/mother_name gộp, không
        # tách surname/given_names/ngày sinh/nơi sinh) — xem _WORKSHEET_OFFICIAL_DOC_FALLBACK.
        "father_full_name",
        "father_surname",
        "father_given_names",
        "father_date_of_birth",
        "father_birth_city",
        "father_birth_state",
        "father_birth_country",
        "mother_full_name",
        "mother_surname",
        "mother_given_names",
        "mother_date_of_birth",
        "mother_birth_city",
        "mother_birth_state",
        "mother_birth_country",
    }
) | _application_form_worksheet_keys()

# Giá trị "chính thức" so với worksheet — override mapping.document khi cần.
# Address/contact trên worksheet; nguồn đối chiếu là Application form (Job Application, mục 1.
# Applicant's Information) — giấy tờ khách nộp có mục địa chỉ cá nhân riêng (Current Address,
# City, State/Province, Country, Postal Code đầy đủ), dùng để đối chiếu chứ không tự điền
# thẳng giá trị worksheet (báo lỗi thực tế 2026-08-04: current_address trước đó "cứ điền rồi
# fill" không hề đối chiếu, vì override cũ trỏ vào "passport" — passport KHÔNG có
# current_address nên _official_value_for_worksheet_compare luôn trả rỗng và
# build_worksheet_conflict_rows luôn bỏ qua field này, im lặng không bao giờ tạo Conflict).
# Khách khai worksheet nhiều khi ghi sai/thiếu (vd. bỏ trống City, đảo City↔State, Postal Code
# ghi tên khu vực thay vì mã bưu điện — thấy trong hồ sơ thật TRIEU THI DUYEN 2026-08-04) nên
# City/State/Postal/Country cũng phải đối chiếu với application_form như current_address,
# không chỉ riêng mỗi địa chỉ đường phố.
#
# primary_phone/email trước đó trỏ vào "passport" — CÙNG LỚP LỖI với current_address (2026-08-04):
# passport không có số điện thoại/email nên _official_value_for_worksheet_compare luôn trả rỗng,
# build_worksheet_conflict_rows luôn bỏ qua field này, im lặng không bao giờ tạo Conflict dù
# worksheet với Job Application (mục Applicant's Information) ghi số/email khác nhau (2026-08-05).
WORKSHEET_OFFICIAL_DOC_OVERRIDES: dict[str, str] = {
    "current_address": "application_form",
    "current_city": "application_form",
    "current_state": "application_form",
    "postal_code": "application_form",
    "current_country": "application_form",
    "primary_phone": "application_form",
    "email": "application_form",
}

# Fallback KHI nguồn chính thức (mapping.document / override ở trên) không có record trong
# phạm vi thành viên đang xét — chỉ dùng cho con cái: con không có birth_certificate (giấy
# khai sinh CỦA CHÍNH HỌ dạng người lớn), chỉ có birth_certificate_child (do cha/mẹ khai hộ).
# birth_certificate_child chỉ có field "father_name"/"mother_name" GỘP (đúng tên field trùng
# với mapping.field của father_full_name/mother_full_name) — không có surname/given_names/
# ngày sinh/nơi sinh tách riêng, nên các field chi tiết đó KHÔNG so được cho con (official_val
# rỗng → build_worksheet_conflict_rows tự bỏ qua, không phải bug — do thiếu dữ liệu nguồn).
_WORKSHEET_OFFICIAL_DOC_FALLBACK: dict[str, str] = {
    "father_full_name": "birth_certificate_child",
    "mother_full_name": "birth_certificate_child",
}

_DATE_COMPARE_KEYS = frozenset(
    {
        "date_of_birth",
        "passport_issue_date",
        "passport_expiration_date",
    }
)


# Hồ sơ gia đình (nhiều thành viên): field_key được gắn hậu tố ".memberNN" để phân biệt
# conflict của từng người — nếu không, 2 người cùng có xung đột "current_address" sẽ dùng
# CHUNG một field_key, khiến conflict của người này ghi đè mất conflict của người kia (upsert
# theo field_key), và tệ hơn — nếu không nhóm theo người trước khi so sánh, giá trị của người A
# bị đem so với người B (báo lỗi thực tế 2026-08-05: TRIEU THI DUYEN so nhầm với NGUYEN MINH
# PHUONG). Hồ sơ đơn (1 thành viên) không có hậu tố — giữ nguyên field_key cũ, không phá dữ
# liệu Conflict đã có trong DB.
_MEMBER_SUFFIX_RE = re.compile(r"\.member(\d{2})$")


def _with_member_suffix(name: str, member_suffix: str | None) -> str:
    return f"{name}.member{member_suffix}" if member_suffix else name


def strip_member_suffix(name: str) -> tuple[str, str | None]:
    """Tách hậu tố .memberNN khỏi field_key suffix — trả (tên gốc, số thành viên hoặc None)."""
    m = _MEMBER_SUFFIX_RE.search(name)
    if not m:
        return name, None
    return name[: m.start()], m.group(1)


def ds260_conflict_field_key(doc_type: str, source_field: str, member_suffix: str | None = None) -> str:
    return f"{DS260_CONFLICT_PREFIX}{doc_type}.{_with_member_suffix(source_field, member_suffix)}"


def worksheet_conflict_field_key(mapping_key: str, member_suffix: str | None = None) -> str:
    return f"{DS260_CONFLICT_PREFIX}{WORKSHEET_CONFLICT_SEGMENT}.{_with_member_suffix(mapping_key, member_suffix)}"


def _slugify_child_name(name: str) -> str:
    from app.services.birth_location import format_person_name_ascii

    ascii_name = format_person_name_ascii(name or "").upper()
    slug = re.sub(r"[^A-Z0-9]+", "_", ascii_name).strip("_")
    return slug or "unknown"


def child_identity_conflict_field_key(child_name: str, field: str) -> str:
    """Khoá theo TÊN con (không theo vị trí slot child_1/child_2 — vị trí đổi mỗi lần dữ liệu
    thay đổi nên không ổn định để làm khoá Conflict)."""
    return f"{DS260_CONFLICT_PREFIX}{CHILD_IDENTITY_SEGMENT}.{_slugify_child_name(child_name)}.{field}"


def child_parent_identity_conflict_field_key(child_name: str, parent: str, field: str) -> str:
    """Khoá theo TÊN con + vai trò cha/mẹ — so ngày sinh/quốc gia sinh cha/mẹ khai trên
    worksheet của con với hồ sơ thật của cha/mẹ đó (khi cha/mẹ CŨNG là case member)."""
    slug = _slugify_child_name(child_name)
    return f"{DS260_CONFLICT_PREFIX}{CHILD_PARENT_IDENTITY_SEGMENT}.{slug}.{parent}.{field}"


def ds260_manual_field_key(mapping_key: str, member_id: str | None = None) -> str:
    if member_id:
        return f"{DS260_CONFLICT_PREFIX}{DS260_MANUAL_SEGMENT}.{member_id}.{mapping_key}"
    return f"{DS260_CONFLICT_PREFIX}{DS260_MANUAL_SEGMENT}.{mapping_key}"


def is_ds260_manual_field_key(field_key: str) -> bool:
    return field_key.startswith(f"{DS260_CONFLICT_PREFIX}{DS260_MANUAL_SEGMENT}.")


def is_ds260_conflict_field(field_key: str) -> bool:
    return field_key.startswith(DS260_CONFLICT_PREFIX) and not is_ds260_manual_field_key(field_key)


def conflict_type_from_field_key(field_key: str) -> str:
    if f".{WORKSHEET_CONFLICT_SEGMENT}." in field_key:
        return "document_vs_worksheet"
    if f".{IDENTITY_OUTLIER_SEGMENT}." in field_key:
        return "identity_outlier"
    if f".{CHILD_PARENT_IDENTITY_SEGMENT}." in field_key:
        return "child_parent_identity"
    if f".{CHILD_IDENTITY_SEGMENT}." in field_key:
        return "child_identity"
    return "document_vs_exception"


def parse_ds260_conflict_key(field_key: str) -> tuple[str, str] | None:
    if not is_ds260_conflict_field(field_key):
        return None
    rest = field_key[len(DS260_CONFLICT_PREFIX) :]
    if rest.startswith(f"{WORKSHEET_CONFLICT_SEGMENT}."):
        return WORKSHEET_CONFLICT_SEGMENT, rest[len(WORKSHEET_CONFLICT_SEGMENT) + 1 :]
    if rest.startswith(f"{IDENTITY_OUTLIER_SEGMENT}."):
        return IDENTITY_OUTLIER_SEGMENT, rest[len(IDENTITY_OUTLIER_SEGMENT) + 1 :]
    if rest.startswith(f"{CHILD_PARENT_IDENTITY_SEGMENT}."):
        return CHILD_PARENT_IDENTITY_SEGMENT, rest[len(CHILD_PARENT_IDENTITY_SEGMENT) + 1 :]
    if rest.startswith(f"{CHILD_IDENTITY_SEGMENT}."):
        return CHILD_IDENTITY_SEGMENT, rest[len(CHILD_IDENTITY_SEGMENT) + 1 :]
    doc_type, _, source_field = rest.partition(".")
    if doc_type and source_field:
        return doc_type, source_field
    return None


def _norm_value(val: str) -> str:
    return re.sub(r"\s+", " ", (val or "").strip().upper())


def _norm_gender(val: str) -> str:
    u = _norm_value(val)
    if u in {"M", "MALE", "NAM"}:
        return "MALE"
    if u in {"F", "FEMALE", "NU", "NỮ"}:
        return "FEMALE"
    return u


def norm_conflict_value(mapping_key: str, val: str) -> str:
    """Normalize for comparison — dates to ISO, gender canonical, else uppercase trim."""
    if not (val or "").strip():
        return ""
    if mapping_key in _DATE_COMPARE_KEYS:
        from app.services.ds260_dates import parse_full_date

        parsed = parse_full_date(val)
        if parsed:
            return parsed.isoformat()
    if mapping_key == "gender":
        return _norm_gender(val)
    return _norm_value(val)


def pick_latest_by_variant(
    records: list[ApplicantDocRecord],
    doc_type: str,
    variant: str,
) -> ApplicantDocRecord | None:
    typed = [r for r in records if r.doc_type == doc_type and r.variant == variant]
    if not typed:
        return None
    return max(typed, key=lambda r: (r.updated_at or r.id, str(r.id)))


async def load_ds260_manual_overrides(
    db: AsyncSession, applicant_id, *, member_id=None
) -> dict[str, str]:
    """DS-260 mapping key → giá trị chỉnh tay (Review trước export)."""
    prefix = f"{DS260_CONFLICT_PREFIX}{DS260_MANUAL_SEGMENT}."
    result = await db.execute(
        select(ProfileField).where(
            ProfileField.applicant_id == applicant_id,
            ProfileField.field_key.like(f"{prefix}%"),
            ProfileField.is_manual.is_(True),
        )
    )
    member_prefix = f"{prefix}{member_id}." if member_id else None
    legacy_prefix = prefix if member_id else None
    out: dict[str, str] = {}
    for pf in result.scalars():
        val = (pf.field_value or "").strip()
        if not val:
            continue
        key = pf.field_key
        if member_prefix and key.startswith(member_prefix):
            mapping_key = key[len(member_prefix) :]
            if mapping_key:
                out[mapping_key] = val
        elif legacy_prefix and member_id is None and key.startswith(legacy_prefix):
            mapping_key = key[len(legacy_prefix) :]
            if mapping_key and "." not in mapping_key:
                out[mapping_key] = val
        elif not member_id and key.startswith(prefix):
            mapping_key = key[len(prefix) :]
            if mapping_key and "." not in mapping_key:
                out[mapping_key] = val
    return out


def apply_ds260_manual_overrides(
    sections_out: list[dict[str, Any]],
    overrides: dict[str, str],
) -> None:
    if not overrides:
        return
    for sec in sections_out:
        for field in sec.get("fields", []):
            key = field.get("key", "")
            if key not in overrides:
                continue
            field["value"] = overrides[key]
            source = field.setdefault("source", {})
            source["derived"] = "manual_override"


def _mapping_keys_for_document_field(doc_type: str, source_field: str) -> list[str]:
    """OCR field trên giấy tờ → các field key DS-260 dùng nguồn đó."""
    from app.services.ds260_mapping import flatten_ds260_mappings

    keys: list[str] = []
    for mkey, mapping in flatten_ds260_mappings().items():
        if mapping.document != doc_type:
            continue
        if mapping.field == source_field or mkey == source_field:
            keys.append(mkey)
            continue
        if source_field in (mapping.aliases or ()):
            keys.append(mkey)
    return keys


def apply_ds260_resolved_conflicts(
    sections_out: list[dict[str, Any]],
    resolutions: dict[str, str],
    *,
    person_name: str = "",
    member_role: str | None = None,
    member_number: str | None = None,
) -> None:
    """
    Áp giá trị user đã chọn khi giải quyết xung đột — sau enrich, trước chỉnh tay.

    Ưu tiên cao hơn OCR/enrich mặc định; thấp hơn manual_override.
    Bộ hồ sơ gia đình: worksheet conflict chỉ áp chủ hồ sơ / khi tên khớp thành viên.

    `member_number` ('01', '02'…) — khi conflict được sinh ra từ hồ sơ nhiều thành viên,
    field_key mang hậu tố ".memberNN" (xem sync_ds260_doc_conflicts); chỉ áp giá trị đã chọn
    khi hậu tố khớp member_number của người đang render form. Conflict KHÔNG có hậu tố (hồ sơ
    1 người, hoặc dữ liệu cũ trước bản vá 2026-08-05) vẫn áp theo cơ chế cũ (name-heuristic) để
    không phá vỡ dữ liệu đã resolve trước đó.
    """
    if not resolutions:
        return

    from app.services.ds260_mapping import _names_same_person, flatten_ds260_mappings

    mappings = flatten_ds260_mappings()
    chosen_by_field: dict[str, tuple[str, str]] = {}

    for fk, chosen in resolutions.items():
        val = (chosen or "").strip()
        if not val:
            continue
        parsed = parse_ds260_conflict_key(fk)
        if not parsed:
            continue
        seg, suffix = parsed
        if seg not in LUONG1_DOC_TYPES:
            continue
        suffix, suffix_member = strip_member_suffix(suffix)
        if suffix_member and suffix_member != member_number:
            continue
        for mkey in _mapping_keys_for_document_field(seg, suffix):
            chosen_by_field[mkey] = (val, "conflict_resolution")

    identity_keys = frozenset({"applicant_name", "date_of_birth", "passport_number", "gender"})
    for fk, chosen in resolutions.items():
        val = (chosen or "").strip()
        if not val:
            continue
        parsed = parse_ds260_conflict_key(fk)
        if not parsed:
            continue
        seg, suffix = parsed
        if seg != WORKSHEET_CONFLICT_SEGMENT:
            continue
        suffix, suffix_member = strip_member_suffix(suffix)
        if suffix not in mappings:
            continue
        if suffix_member:
            # Conflict có hậu tố thành viên — chỉ khớp người đang render, không cần đoán qua tên.
            if suffix_member != member_number:
                continue
        else:
            # Hồ sơ 1 người / conflict cũ chưa có hậu tố — giữ cơ chế cũ.
            if member_role in ("child", "grandchild"):
                continue
            if (
                suffix in identity_keys
                and person_name
                and not _names_same_person(val, person_name)
            ):
                continue
        chosen_by_field[suffix] = (val, "worksheet_conflict_resolution")

    for sec in sections_out:
        for field in sec.get("fields", []):
            key = field.get("key", "")
            if key not in chosen_by_field:
                continue
            val, derived = chosen_by_field[key]
            field["value"] = val
            src = field.setdefault("source", {})
            src["derived"] = derived


async def load_ds260_field_resolutions(db: AsyncSession, applicant_id) -> dict[str, str]:
    """field_key ds260.* → resolved_value (chỉ conflict đã giải quyết)."""
    result = await db.execute(
        select(Conflict).where(
            Conflict.applicant_id == applicant_id,
            Conflict.field_key.like(f"{DS260_CONFLICT_PREFIX}%"),
            Conflict.status == ConflictStatus.resolved,
        )
    )
    out: dict[str, str] = {}
    for c in result.scalars():
        if c.resolved_value:
            out[c.field_key] = c.resolved_value.strip()
    return out


async def list_open_ds260_conflicts(db: AsyncSession, applicant_id) -> list[Conflict]:
    result = await db.execute(
        select(Conflict).where(
            Conflict.applicant_id == applicant_id,
            Conflict.field_key.like(f"{DS260_CONFLICT_PREFIX}%"),
            Conflict.status == ConflictStatus.open,
        )
    )
    return list(result.scalars())


async def count_open_ds260_conflicts(db: AsyncSession, applicant_id) -> int:
    conflicts = await list_open_ds260_conflicts(db, applicant_id)
    return len(conflicts)


def _form_dict(rec: ApplicantDocRecord) -> dict[str, str]:
    try:
        data = json.loads(rec.form_data or "{}")
    except json.JSONDecodeError:
        return {}
    return {k: str(v).strip() for k, v in data.items() if v is not None and str(v).strip()}


def _strict_field_value(
    rec: ApplicantDocRecord | None,
    mapping_key: str,
) -> tuple[str, str]:
    """Chỉ key/field/aliases — không loose match (tránh nhầm gender ↔ date_of_birth)."""
    from app.services.ds260_mapping import (
        _effective_aliases,
        _resolve_from_record,
        flatten_ds260_mappings,
    )

    mapping = flatten_ds260_mappings().get(mapping_key)
    if not mapping or not rec:
        return "", mapping_key

    aliases = _effective_aliases(mapping)
    if mapping.key != mapping.field:
        val = _resolve_from_record(rec, mapping.key, ())
        if val.strip():
            return val, mapping.key
    val = _resolve_from_record(rec, mapping.field, aliases)
    if val.strip():
        return val, mapping.field
    return "", mapping.field


_WORK_CURRENT_JOB_KEYS = frozenset(
    {
        "work_primary_occupation",
        "work_occupation_other_specify",
        "work_present_employer",
        "work_employer_address",
        "work_employer_city",
        "work_employer_state",
        "work_employer_postal_code",
        "work_employer_country",
        "work_job_title",
        "work_start_date",
    }
)


def _application_form_job_confirmed_as_prior(
    records: list[ApplicantDocRecord],
    app_rec: ApplicantDocRecord,
) -> bool:
    """True khi worksheet DS-260 tự xác nhận công việc trên Application form là công việc CŨ
    (tên công ty khớp trong work_other_occupation_detail/work_prior_jobs_history) — không phải
    chỉ vì worksheet khai nghề nghiệp hiện tại khác đi (điều đó vẫn có thể là xung đột thật)."""
    from app.services.ds260_mapping import _job_identity_tokens

    app_occ, _ = _strict_field_value(app_rec, "work_primary_occupation")
    app_emp, _ = _strict_field_value(app_rec, "work_present_employer")
    app_tokens = _job_identity_tokens(app_occ, app_emp)
    if not app_tokens:
        return False

    ws_rec = pick_latest_by_variant(records, "ds260_customer_form", "exception") or pick_latest_by_variant(
        records, "ds260_customer_form", "standard"
    )
    if not ws_rec:
        return False
    detail_val, _ = _strict_field_value(ws_rec, "work_other_occupation_detail")
    prior_val, _ = _strict_field_value(ws_rec, "work_prior_jobs_history")
    narrative_tokens = _job_identity_tokens("", f"{detail_val} {prior_val}")
    if not narrative_tokens:
        return False

    overlap = len(app_tokens & narrative_tokens) / len(app_tokens)
    return overlap >= 0.5


def _official_value_for_worksheet_compare(
    records: list[ApplicantDocRecord],
    mapping_key: str,
    resolutions: dict[str, str],
    member_suffix: str | None = None,
) -> tuple[str, ApplicantDocRecord | None]:
    """Giá trị từ giấy tờ chính thức (Luồng 1 resolved) — strict field match only.

    `records` phải đã được lọc theo TỪNG THÀNH VIÊN trước khi gọi (xem sync_ds260_doc_conflicts)
    — hàm này không tự lọc theo người, chỉ chọn bản mới nhất trong đúng danh sách được truyền vào.
    """
    from app.services.ds260_mapping import flatten_ds260_mappings, pick_latest_record

    mapping = flatten_ds260_mappings().get(mapping_key)
    if not mapping:
        return "", None

    doc_type = WORKSHEET_OFFICIAL_DOC_OVERRIDES.get(mapping_key, mapping.document)
    standard = pick_latest_by_variant(records, doc_type, "standard")
    reference = pick_latest_by_variant(records, doc_type, "exception")

    if not standard and not reference:
        # Con cái không có birth_certificate riêng (chỉ có birth_certificate_child) — thử
        # nguồn dự phòng trước khi bỏ cuộc, nếu không father_full_name/mother_full_name của
        # con sẽ luôn official_val rỗng → không bao giờ so được với worksheet (im lặng bỏ qua).
        fallback_doc_type = _WORKSHEET_OFFICIAL_DOC_FALLBACK.get(mapping_key)
        if fallback_doc_type:
            fb_standard = pick_latest_by_variant(records, fallback_doc_type, "standard")
            fb_reference = pick_latest_by_variant(records, fallback_doc_type, "exception")
            if fb_standard or fb_reference:
                doc_type, standard, reference = fallback_doc_type, fb_standard, fb_reference

    if doc_type == "application_form":
        # Cụm "công việc HIỆN TẠI" (present_employer/job_title/địa chỉ/ngày bắt đầu...): nếu
        # worksheet DS-260 đã tự xác nhận công ty trong Application form là công việc CŨ (mô tả
        # trong other_occupation_detail/prior_jobs_history — vd. khách nộp Job Application cũ
        # của công ty may Xuân Vũ, nhưng DS-260 tự khai nói rõ đó là việc đã nghỉ và hiện tại tự
        # làm), thì không có gì để "đối chiếu" giữa hai nguồn — coi như application_form không
        # cung cấp giá trị công việc HIỆN TẠI, tránh báo xung đột giả giữa việc cũ và việc hiện
        # tại thực sự. Chỉ bỏ qua khi có bằng chứng rõ ràng (tên công ty khớp trong narrative) —
        # nếu worksheet chỉ đơn thuần khai nghề khác mà KHÔNG nhắc gì tới công ty trong
        # Application form, đó vẫn là một xung đột thật cần người dùng xem xét (giữ hành vi cũ).
        if mapping_key in _WORK_CURRENT_JOB_KEYS:
            app_rec = standard or reference
            if app_rec and _application_form_job_confirmed_as_prior(records, app_rec):
                return "", None

    conflict_keys = (
        ds260_conflict_field_key(doc_type, mapping.field, member_suffix),
        ds260_conflict_field_key(doc_type, mapping.key, member_suffix),
    )
    for ck in conflict_keys:
        chosen = (resolutions.get(ck) or "").strip()
        if not chosen:
            continue
        for rec in (standard, reference):
            if not rec:
                continue
            val, _ = _strict_field_value(rec, mapping_key)
            if val.strip() and norm_conflict_value(mapping_key, val) == norm_conflict_value(mapping_key, chosen):
                return val, rec
        return chosen, standard or reference

    for rec in (standard, reference):
        if not rec:
            continue
        val, _ = _strict_field_value(rec, mapping_key)
        if val.strip():
            return val, rec

    rec = pick_latest_record(records, doc_type)
    if rec:
        val, _ = _strict_field_value(rec, mapping_key)
        return val, rec
    return "", None


def _worksheet_value(
    records: list[ApplicantDocRecord],
    mapping_key: str,
) -> tuple[str, ApplicantDocRecord | None]:
    from app.services.ds260_mapping import pick_latest_record

    ds260_rec = pick_latest_by_variant(records, "ds260_customer_form", "exception") or pick_latest_record(
        records, "ds260_customer_form"
    )
    if not ds260_rec:
        return "", None
    val, _ = _strict_field_value(ds260_rec, mapping_key)
    return val, ds260_rec


def build_worksheet_conflict_rows(
    records: list[ApplicantDocRecord],
    resolutions: dict[str, str],
    member_suffix: str | None = None,
) -> list[dict[str, Any]]:
    """Detect document_vs_worksheet conflicts (pure — for tests and sync).

    `records` phải đã được lọc theo TỪNG THÀNH VIÊN trước khi gọi (báo lỗi thực tế 2026-08-05:
    hồ sơ gia đình so nhầm application_form của người A với worksheet của người B) — xem
    sync_ds260_doc_conflicts(). `member_suffix` ('01', '02'…) gắn vào field_key khi hồ sơ có
    từ 2 thành viên trở lên, để conflict của mỗi người không ghi đè lẫn nhau.
    """
    ds260_present = any(r.doc_type == "ds260_customer_form" for r in records)
    if not ds260_present:
        return []

    rows: list[dict[str, Any]] = []
    for mapping_key in sorted(WORKSHEET_COMPARE_KEYS):
        fk = worksheet_conflict_field_key(mapping_key, member_suffix)
        if fk in resolutions:
            continue

        official_val, official_rec = _official_value_for_worksheet_compare(
            records, mapping_key, resolutions, member_suffix
        )
        worksheet_val, worksheet_rec = _worksheet_value(records, mapping_key)
        if not official_val.strip() or not worksheet_val.strip():
            continue
        if norm_conflict_value(mapping_key, official_val) == norm_conflict_value(mapping_key, worksheet_val):
            continue

        rows.append(
            {
                "field_key": fk,
                "value_a": official_val,
                "document_a_id": official_rec.source_document_id if official_rec else None,
                "value_b": worksheet_val,
                "document_b_id": worksheet_rec.source_document_id if worksheet_rec else None,
            }
        )
    return rows


def _sync_document_exception_conflicts(
    records: list[ApplicantDocRecord],
    resolutions: dict[str, str],
    member_suffix: str | None = None,
) -> list[dict]:
    """`records` phải đã lọc theo TỪNG THÀNH VIÊN trước khi gọi — xem sync_ds260_doc_conflicts()."""
    rows: list[dict] = []
    for doc_type in LUONG1_DOC_TYPES:
        standard = pick_latest_by_variant(records, doc_type, "standard")
        reference = pick_latest_by_variant(records, doc_type, "exception")
        if not standard or not reference:
            continue

        std_form = _form_dict(standard)
        ref_form = _form_dict(reference)
        for key in set(std_form) | set(ref_form):
            val_a = std_form.get(key, "")
            val_b = ref_form.get(key, "")
            if not val_a or not val_b:
                continue
            if _norm_value(val_a) == _norm_value(val_b):
                continue

            fk = ds260_conflict_field_key(doc_type, key, member_suffix)
            if fk in resolutions:
                continue

            rows.append(
                {
                    "field_key": fk,
                    "value_a": val_a,
                    "document_a_id": standard.source_document_id,
                    "value_b": val_b,
                    "document_b_id": reference.source_document_id,
                }
            )
    return rows


async def sync_ds260_doc_conflicts(db: AsyncSession, applicant_id) -> int:
    """
    So sánh:
    1) Luồng 1 (standard) vs đối chiếu (exception) — document_vs_exception
    2) Giá trị Luồng 1 đã resolve vs ds260_customer_form — document_vs_worksheet
    3) Đa số tài liệu vs tài liệu lệch (tên/ngày sinh/giới tính/tên cha-mẹ) — identity_outlier
    4) Ngày sinh/nơi sinh của TỪNG CON (tên khớp) giữa giấy khai sinh con và worksheet —
       child_identity (xem build_child_identity_conflict_rows trong ds260_mapping.py)
    5) Ngày sinh/quốc gia sinh cha-mẹ khai trên worksheet CỦA CHÍNH NGƯỜI CON vs hồ sơ thật của
       cha/mẹ đó (khi cha/mẹ CŨNG là case member) — child_parent_identity (xem
       build_child_parent_identity_conflict_rows trong ds260_mapping.py)

    Upsert theo field_key (KHÔNG xoá-hết-rồi-tạo-lại): sync chạy lại sau MỖI lần OCR xong
    một file, kể cả khi nội dung không đổi — xoá/tạo lại toàn bộ sẽ cấp UUID mới cho conflict
    id mỗi lần, khiến id đang hiển thị trên UI thành "mồ côi" giữa lúc người dùng bấm resolve
    → 404 dù conflict thực chất vẫn còn đó. Giữ conflict cũ nguyên id, chỉ cập nhật giá trị.

    Hồ sơ gia đình (nhiều thành viên): (1) và (2) PHẢI so sánh trong phạm vi tài liệu của TỪNG
    NGƯỜI — nhóm theo case member (tên file + tên OCR trích xuất, cùng cơ chế identity_outlier
    đã dùng từ 2026-08-04) trước khi so sánh, nếu không dữ liệu người A bị đem so với người B
    (báo lỗi thực tế 2026-08-05: TRIEU THI DUYEN so nhầm địa chỉ với NGUYEN MINH PHUONG). Hồ sơ
    1 người luôn gom về đúng 1 nhóm nên field_key giữ nguyên định dạng cũ (không hậu tố).
    """
    records = await list_doc_records(db, applicant_id)
    resolutions = await load_ds260_field_resolutions(db, applicant_id)

    from app.services.ds260_mapping import (
        build_child_identity_conflict_rows,
        build_child_parent_identity_conflict_rows,
    )
    from app.services.family_case import group_doc_records_by_member
    from app.services.identity_conflicts import build_identity_outlier_conflict_rows

    member_groups = await group_doc_records_by_member(db, applicant_id, records)
    multi_member = len(member_groups) > 1

    desired: dict[str, dict] = {}
    for member_number, group_records in member_groups.items():
        suffix = member_number if multi_member else None
        for row in _sync_document_exception_conflicts(group_records, resolutions, suffix):
            desired[row["field_key"]] = row
        for row in build_worksheet_conflict_rows(group_records, resolutions, suffix):
            desired[row["field_key"]] = row
        for row in build_child_identity_conflict_rows(group_records, resolutions):
            desired[row["field_key"]] = row
    for row in await build_identity_outlier_conflict_rows(db, applicant_id, resolutions):
        desired[row["field_key"]] = row
    for row in await build_child_parent_identity_conflict_rows(db, applicant_id, resolutions):
        desired[row["field_key"]] = row

    open_result = await db.execute(
        select(Conflict).where(
            Conflict.applicant_id == applicant_id,
            Conflict.field_key.like(f"{DS260_CONFLICT_PREFIX}%"),
            Conflict.status == ConflictStatus.open,
        )
    )
    existing_by_key: dict[str, Conflict] = {c.field_key: c for c in open_result.scalars()}

    for field_key, existing in existing_by_key.items():
        if field_key not in desired:
            await db.delete(existing)

    for field_key, row in desired.items():
        existing = existing_by_key.get(field_key)
        if existing:
            existing.value_a = row["value_a"]
            existing.document_a_id = row["document_a_id"]
            existing.value_b = row["value_b"]
            existing.document_b_id = row["document_b_id"]
            existing.majority_count = row.get("majority_count")
            existing.total_count = row.get("total_count")
        else:
            db.add(
                Conflict(
                    applicant_id=applicant_id,
                    field_key=field_key,
                    value_a=row["value_a"],
                    document_a_id=row["document_a_id"],
                    value_b=row["value_b"],
                    document_b_id=row["document_b_id"],
                    status=ConflictStatus.open,
                    majority_count=row.get("majority_count"),
                    total_count=row.get("total_count"),
                )
            )

    await db.flush()
    return len(desired)


@lru_cache(maxsize=1)
def _field_key_to_section_title() -> dict[str, str]:
    """mapping_key → tiêu đề MỤC DS-260 chứa nó (vd. "DS-260 3 — ADDRESS / ĐỊA CHỈ") — để
    nhãn conflict ghi rõ field đang xung đột thuộc mục nào trên form, thay vì nói chung chung
    "DS-260 worksheet" (yêu cầu thực tế 2026-08-04: "ở mục gì trong DS260 luôn á")."""
    from app.services.ds260_mapping import load_ds260_sections

    out: dict[str, str] = {}
    for sec in load_ds260_sections():
        for f in sec.fields:
            out[f.key] = sec.title
    return out


# identity_outlier dùng namespace canonical riêng ("identity.*"/"family.*", field_mapping.py)
# khác với namespace mapping_key của ds260_mapping.json ("applicant_name", "father_surname"...)
# — quy đổi thủ công cho đúng 5 key trong IDENTITY_VOTE_KEYS (identity_conflicts.py) để tra
# được MỤC DS-260 chứa nó, thay vì hiển thị nhãn trần không rõ thuộc mục nào (yêu cầu thực tế
# 2026-08-04: "nó đang không phân mục DS260 nào chứa").
_IDENTITY_CANONICAL_TO_MAPPING_KEY: dict[str, str] = {
    "identity.full_name": "applicant_name",
    "identity.date_of_birth": "date_of_birth",
    "identity.gender": "gender",
    "family.father_name": "father_surname",
    "family.mother_name": "mother_surname",
}


def conflict_label_vi(field_key: str, *, person_hint: str | None = None) -> str:
    """`person_hint` — tên người (case member) mà conflict identity_outlier này thuộc về.

    Hồ sơ gia đình nhiều người có thể phát sinh NHIỀU thẻ conflict cùng nhãn ("Họ và tên đầy
    đủ — khác biệt với đa số tài liệu") — một thẻ cho mẹ, một thẻ cho con — nếu không ghi rõ
    thuộc về ai ngay trên tiêu đề thì người dùng phải tự đọc tên file nhỏ bên dưới mới đoán
    được, dễ chọn nhầm giữa 2 người (báo lỗi thực tế 2026-08-04).
    """
    parsed = parse_ds260_conflict_key(field_key)
    if not parsed:
        return field_key
    kind, name = parsed
    if kind != IDENTITY_OUTLIER_SEGMENT:
        # Hồ sơ gia đình: name (WORKSHEET_CONFLICT_SEGMENT hoặc doc_type.source_field) có thể
        # mang hậu tố ".memberNN" — bóc ra trước khi tra label/mapping, nếu không lookup thất
        # bại và trả về nguyên field_key thô (hiện "current_address.member03" vỡ chữ trên UI).
        # identity_outlier có quy ước hậu tố riêng (.{document_id}, xử lý bằng rpartition bên
        # dưới) nên không strip ở đây.
        name, _member_no = strip_member_suffix(name)
    if kind == IDENTITY_OUTLIER_SEGMENT:
        from app.services.field_mapping import FIELD_LABELS_VI

        canonical_key, _, _document_id = name.rpartition(".")
        label = FIELD_LABELS_VI.get(canonical_key, canonical_key or name)
        who = f" ({person_hint})" if person_hint else ""
        mapping_key = _IDENTITY_CANONICAL_TO_MAPPING_KEY.get(canonical_key)
        section_title = _field_key_to_section_title().get(mapping_key or "", "")
        section_prefix = f"{section_title} · " if section_title else ""
        return f"⚠️ {section_prefix}{label}{who} — khác biệt với đa số tài liệu"
    if kind == CHILD_IDENTITY_SEGMENT:
        slug, _, field = name.rpartition(".")
        child_field_labels = {
            "date_of_birth": "Ngày sinh",
            "birth_city": "Nơi sinh (Thành phố)",
            "birth_state": "Nơi sinh (Tỉnh/Bang)",
            "birth_country": "Nơi sinh (Quốc gia)",
        }
        field_label = child_field_labels.get(field, field or name)
        display_name = slug.replace("_", " ").strip() or "Con"
        return f"⚠️ Con {display_name} · {field_label} — khác nhau giữa giấy khai sinh và worksheet"
    if kind == CHILD_PARENT_IDENTITY_SEGMENT:
        parts = name.split(".")
        slug, parent, field = (parts + ["", "", ""])[:3]
        parent_vi = "Cha" if parent == "father" else "Mẹ" if parent == "mother" else parent
        field_labels = {"date_of_birth": "Ngày sinh", "birth_country": "Quốc gia sinh"}
        field_label = field_labels.get(field, field or name)
        display_name = slug.replace("_", " ").strip() or "Con"
        return (
            f"⚠️ Con {display_name} · {parent_vi} — {field_label} khai trên worksheet khác với "
            f"hồ sơ thật của {parent_vi.lower()} trong bộ hồ sơ"
        )
    if kind == WORKSHEET_CONFLICT_SEGMENT:
        labels = {
            "applicant_name": "Họ và tên",
            "date_of_birth": "Ngày sinh",
            "gender": "Giới tính",
            "nationality": "Quốc tịch",
            "place_of_birth": "Nơi sinh",
            "passport_number": "Số hộ chiếu",
            "passport_issue_date": "Ngày cấp hộ chiếu",
            "passport_expiration_date": "Ngày hết hạn hộ chiếu",
            "current_marital_status": "Tình trạng hôn nhân",
            "current_address": "Địa chỉ hiện tại",
            "primary_phone": "Số điện thoại",
            "email": "Email",
            "work_primary_occupation": "Nghề nghiệp chính",
            "work_occupation_other_specify": "Nghề khác (ghi rõ)",
            "work_present_employer": "Công ty/nơi làm việc hiện tại",
            "work_employer_address": "Địa chỉ công ty",
            "work_employer_city": "Thành phố công ty",
            "work_employer_state": "Tỉnh/Bang công ty",
            "work_employer_postal_code": "Mã bưu điện công ty",
            "work_employer_country": "Quốc gia công ty",
            "work_job_title": "Chức danh",
            "work_start_date": "Ngày bắt đầu làm việc",
            "edu_middle_school_name": "Tên trường THCS",
            "edu_middle_school_address": "Địa chỉ trường THCS",
            "edu_middle_school_period": "Thời gian học THCS",
            "edu_high_school_name": "Tên trường THPT",
            "edu_high_school_address": "Địa chỉ trường THPT",
            "edu_high_school_period": "Thời gian học THPT",
            "edu_college_name": "Tên trường ĐH/CĐ",
            "edu_college_address": "Địa chỉ trường ĐH/CĐ",
            "edu_college_major": "Chuyên ngành",
            "edu_college_period": "Thời gian học ĐH/CĐ",
        }
        field_label = labels.get(name)
        if not field_label:
            from app.services.ds260_mapping import flatten_ds260_mappings

            mapping = flatten_ds260_mappings().get(name)
            field_label = mapping.label if mapping else name
        section_title = _field_key_to_section_title().get(name, "DS-260 worksheet")
        return f"{section_title} · {field_label}"
    doc_type, source_field = kind, name
    doc_labels = {
        "passport": "Passport",
        "birth_certificate": "Birth certificate",
        "judicial_certificate": "JUDICIAL CERTIFICATE",
        "marriage_certificate": "Marriage certificate",
    }
    return f"{doc_labels.get(doc_type, doc_type)} · {source_field}"
