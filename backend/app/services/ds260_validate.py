"""Validate DS260 form trước approve / export — đọc từ doc records + mapping."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import ApplicantDocRecord, Document, DocumentStatus
from app.services.document_registry import REGISTRY_BY_CODE
from app.services.ds260_conflicts import count_open_ds260_conflicts
from app.services.ds260_mapping import (
    _child_excluded_section_ids,
    flatten_ds260_mappings,
    load_ds260_mapping,
    load_ds260_sections,
    pick_luong1_pair_for_person,
    resolve_ds260_form,
)

PASSPORT_REQUIRED_FIELD_KEYS = frozenset(
    {"passport_number", "passport_issue_date", "passport_expiration_date"}
)

# GKS chủ hồ sơ — không áp validation section cho hồ sơ con
_CHILD_SKIP_VALIDATION_SECTIONS = _child_excluded_section_ids() | frozenset(
    {"section_birth_certificate"}
)

# Giấy tờ có trong bộ upload nhưng không áp cho DS-260 con
_CHILD_SKIP_VALIDATION_DOC_TYPES = frozenset(
    {"birth_certificate", "birth_certificate_child", "marriage_certificate", "divorce"}
)


def load_validation_rules() -> dict[str, Any]:
    return load_ds260_mapping().get("validation") or {}


def flatten_ds260_values(form: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for sec in form.get("sections", []):
        for field in sec.get("fields", []):
            out[field["key"]] = (field.get("value") or "").strip()
    return out


from app.services.ds260_dates import (
    format_partial_ds260_date,
    is_partial_date_value,
    parse_date_lenient,
    parse_full_date,
    partial_date_warning_message,
)


def _date_note_warnings(
    form: dict[str, Any], field_labels: dict[str, str]
) -> list[dict[str, str]]:
    """Cảnh báo ngày do format_sections_date_display đánh dấu (nhập nhằng / không đọc được)."""
    out: list[dict[str, str]] = []
    for sec in form.get("sections", []):
        for field in sec.get("fields", []):
            note = field.get("date_note")
            if not isinstance(note, dict):
                continue
            key = field.get("key", "")
            label = field_labels.get(key, key)
            raw = note.get("raw", "")
            if note.get("code") == "ambiguous_date":
                msg = (
                    f"{label}: ngày \"{raw}\" đọc được theo cả dd/mm lẫn mm/dd — "
                    f"đang hiểu theo dd/mm (chuẩn VN), xuất \"{field.get('value', '')}\". "
                    f"Đối chiếu giấy gốc."
                )
            else:
                msg = (
                    f"{label}: không đọc được ngày \"{raw}\" — đã để TRỐNG để tránh "
                    f"sai định dạng trên form. Nhập tay sau khi đối chiếu giấy gốc."
                )
            out.append(
                _issue(code=str(note.get("code")), message=msg, field_key=key)
            )
    return out


def _judicial_criminal_record_warnings(form: dict[str, Any]) -> list[dict[str, str]]:
    """Cảnh báo khi arrested_convicted được tự động suy ra "Yes" từ Phiếu lý lịch tư pháp
    (enrich_arrested_convicted_from_judicial) — câu hỏi nhạy cảm, luôn cần người duyệt đối
    chiếu lại nguyên văn án tích trên giấy gốc trước khi xuất."""
    out: list[dict[str, str]] = []
    for sec in form.get("sections", []):
        for field in sec.get("fields", []):
            if field.get("key") != "arrested_convicted":
                continue
            derived = (field.get("source") or {}).get("derived")
            if derived != "arrested_convicted_yes_from_judicial":
                continue
            out.append(
                _issue(
                    code="arrested_convicted_needs_review",
                    message=(
                        "Câu \"Ever arrested or convicted?\" đã tự động điền \"Yes\" dựa trên "
                        "án tích ghi trên Phiếu lý lịch tư pháp — kiểm tra lại nguyên văn giấy "
                        "gốc trước khi xuất (câu hỏi nhạy cảm, ảnh hưởng trực tiếp hồ sơ visa)."
                    ),
                    field_key="arrested_convicted",
                    document_type="judicial_certificate",
                )
            )
    return out


def _issue(
    *,
    code: str,
    message: str,
    field_key: str | None = None,
    document_type: str | None = None,
) -> dict[str, str]:
    item: dict[str, str] = {"code": code, "message": message}
    if field_key:
        item["field_key"] = field_key
    if document_type:
        item["document_type"] = document_type
    return item


def missing_address_before_16(
    *,
    dob_val: str,
    address_from_val: str,
    other_addresses_used: str,
    other_addresses_history: str,
) -> bool:
    """True when the worksheet's current-address from-date starts strictly after the
    applicant's 16th birthday (month granularity) and no earlier address history was
    declared. Lenient-parses address_from_val so mm/yyyy values (the common case for
    this field) don't mis-fire just because they lack a day component."""
    dob_date = parse_full_date(dob_val) if dob_val else None
    if not dob_date:
        return False
    address_from_parsed = parse_date_lenient(address_from_val) if address_from_val else None
    try:
        age16_date = dob_date.replace(year=dob_date.year + 16)
    except ValueError:
        age16_date = dob_date.replace(month=2, day=28, year=dob_date.year + 16)
    covers_before_16 = other_addresses_used == "yes" and bool(other_addresses_history)
    if covers_before_16:
        return False
    if address_from_parsed is None:
        return True
    address_from_date, _granularity = address_from_parsed
    return (address_from_date.year, address_from_date.month) > (age16_date.year, age16_date.month)


async def validate_ds260(
    db: AsyncSession,
    applicant_id,
    *,
    filename_map: dict[str, str] | None = None,
    member_id=None,
) -> dict[str, Any]:
    rules = load_validation_rules()
    form = await resolve_ds260_form(db, applicant_id, filename_map=filename_map, member_id=member_id)
    flat = flatten_ds260_values(form)
    field_labels = {f.key: f.label for f in flatten_ds260_mappings().values()}
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    member_info = form.get("member") or {}
    member_role = member_info.get("role")
    person_name = (member_info.get("display_name") or "").strip()

    from app.services.doc_record_sync import list_doc_records

    records = await list_doc_records(db, applicant_id)

    member_has_passport_doc = "passport" in form.get("documents", {})
    if member_id and person_name:
        passport_rec, _ = pick_luong1_pair_for_person(records, "passport", person_name)
        member_has_passport_doc = passport_rec is not None

    present_docs = set(form.get("documents", {}).keys())

    for doc_rule in rules.get("required_documents", []):
        doc_type = doc_rule.get("doc_type", "")
        if doc_type not in present_docs:
            label = doc_rule.get("label") or REGISTRY_BY_CODE.get(doc_type, doc_type)
            errors.append(
                _issue(
                    code="missing_document",
                    message=f"Thiếu tài liệu bắt buộc: {label}",
                    document_type=doc_type,
                )
            )

    doc_result = await db.execute(
        select(Document).where(
            Document.applicant_id == applicant_id,
            Document.registry_doc_type.in_(list(REGISTRY_BY_CODE.keys())),
        )
    )
    for doc in doc_result.scalars().all():
        if doc.status == DocumentStatus.failed:
            dtype = doc.registry_doc_type or doc.document_type or "unknown"
            warnings.append(
                _issue(
                    code="ocr_failed",
                    message=f"OCR thất bại: {doc.original_filename or dtype}",
                    document_type=dtype,
                )
            )
        elif doc.status in {DocumentStatus.uploaded, DocumentStatus.processing}:
            dtype = doc.registry_doc_type or doc.document_type or "unknown"
            errors.append(
                _issue(
                    code="ocr_pending",
                    message=f"Đang chờ OCR: {doc.original_filename or dtype}",
                    document_type=dtype,
                )
            )

    for field_key in rules.get("required_fields", []):
        if (
            field_key in PASSPORT_REQUIRED_FIELD_KEYS
            and member_id
            and not member_has_passport_doc
        ):
            continue
        if not flat.get(field_key, "").strip():
            label = field_labels.get(field_key, field_key)
            mapping = flatten_ds260_mappings().get(field_key)
            errors.append(
                _issue(
                    code="missing_required_field",
                    message=f"Thiếu trường bắt buộc: {label}",
                    field_key=field_key,
                    document_type=mapping.document if mapping else None,
                )
            )

    section_by_id = {s.id: s for s in load_ds260_sections()}
    for doc_type, section_ids in (rules.get("section_required_when_document_present") or {}).items():
        if doc_type not in present_docs:
            continue
        if member_role in ("child", "grandchild") and doc_type in _CHILD_SKIP_VALIDATION_DOC_TYPES:
            continue
        if doc_type == "passport" and member_id and not member_has_passport_doc:
            continue
        for sec_id in section_ids:
            if member_role in ("child", "grandchild") and sec_id in _CHILD_SKIP_VALIDATION_SECTIONS:
                continue
            sec = section_by_id.get(sec_id)
            if not sec:
                continue
            for mapping in sec.fields:
                if not flat.get(mapping.key, "").strip():
                    warnings.append(
                        _issue(
                            code="incomplete_section",
                            message=f"Thiếu {mapping.label} (đã có {doc_type})",
                            field_key=mapping.key,
                            document_type=doc_type,
                        )
                    )

    for field_key in rules.get("date_fields", []):
        val = flat.get(field_key, "").strip()
        if not val:
            continue
        if parse_full_date(val) is None and not is_partial_date_value(val):
            continue

    for field_key, val in flat.items():
        if not val or not field_key:
            continue
        if not (
            field_key in (rules.get("date_fields") or [])
            or "date" in field_key.lower()
            or field_key.endswith("_dob")
        ):
            continue
        if not is_partial_date_value(val):
            continue
        display = format_partial_ds260_date(val) or val
        label = field_labels.get(field_key, field_key)
        mapping = flatten_ds260_mappings().get(field_key)
        warnings.append(
            _issue(
                code="partial_date",
                message=partial_date_warning_message(label, val, display),
                field_key=field_key,
                document_type=mapping.document if mapping else None,
            )
        )

    warnings.extend(_date_note_warnings(form, field_labels))
    warnings.extend(_judicial_criminal_record_warnings(form))

    exp_val = flat.get("passport_expiration_date", "").strip()
    if exp_val:
        exp_date = parse_full_date(exp_val)
        if exp_date:
            if exp_date < date.today():
                errors.append(
                    _issue(
                        code="passport_expired",
                        message=f"Hộ chiếu đã hết hạn ({exp_val})",
                        field_key="passport_expiration_date",
                        document_type="passport",
                    )
                )
            elif (exp_date - date.today()).days <= 180:
                warnings.append(
                    _issue(
                        code="passport_expiring_soon",
                        message=f"Hộ chiếu sắp hết hạn ({exp_val})",
                        field_key="passport_expiration_date",
                        document_type="passport",
                    )
                )

    rec_result = await db.execute(
        select(ApplicantDocRecord).where(ApplicantDocRecord.applicant_id == applicant_id)
    )
    if not list(rec_result.scalars().all()):
        errors.append(
            _issue(
                code="no_doc_records",
                message="Chưa có dữ liệu OCR trong bảng tài liệu — upload và chờ xử lý",
            )
        )

    open_conflicts = await count_open_ds260_conflicts(db, applicant_id)
    if open_conflicts:
        errors.append(
            _issue(
                code="ds260_conflict_open",
                message=f"Còn {open_conflicts} xung đột Luồng 1 / đối chiếu — chọn giá trị trước khi xuất",
            )
        )

    children_count_raw = flat.get("children_count", "").strip()
    if children_count_raw.isdigit() and int(children_count_raw) > 3:
        warnings.append(
            _issue(
                code="children_count_exceeds_template",
                message=(
                    f"Worksheet khai {children_count_raw} con nhưng mẫu DS-260 chỉ có 3 slot "
                    "— chỉ xuất child_1..child_3"
                ),
                field_key="children_count",
                document_type="birth_certificate_child",
            )
        )

    # Cảnh báo khi worksheet có địa chỉ nhưng chưa có application_form đối chiếu
    has_ds260_worksheet = "ds260_customer_form" in present_docs
    has_application_form = "application_form" in present_docs
    worksheet_address_keys = {"current_address", "current_city", "current_state", "postal_code", "current_country"}
    has_worksheet_address = any(
        str(flat.get(k, "")).strip() for k in worksheet_address_keys
    )

    if has_ds260_worksheet and has_worksheet_address and not has_application_form:
        warnings.append(
            _issue(
                code="missing_application_form_for_address_check",
                message=(
                    "Worksheet khách khai có địa chỉ nhưng chưa upload Application form để đối chiếu "
                    "— vui lòng upload Job Application / Application form để kiểm tra địa chỉ khách khai"
                ),
                document_type="application_form",
            )
        )

    # Cảnh báo khi không có địa chỉ trước 16 tuổi — DS-260 yêu cầu khai đủ nơi ở kể từ năm 16
    # tuổi (other_addresses_since_16). Nếu địa chỉ hiện tại chỉ có từ sau mốc 16 tuổi và khách
    # không khai "có ở nơi khác từ năm 16 tuổi" (other_addresses_used != Yes), khả năng cao đang
    # thiếu địa chỉ giai đoạn trước đó.
    if has_ds260_worksheet and missing_address_before_16(
        dob_val=flat.get("date_of_birth", "").strip(),
        address_from_val=flat.get("address_from_date", "").strip(),
        other_addresses_used=flat.get("other_addresses_used", "").strip().lower(),
        other_addresses_history=flat.get("other_addresses_history", "").strip(),
    ):
        warnings.append(
            _issue(
                code="missing_address_before_16",
                message=(
                    "Không có địa chỉ nào trước năm 16 tuổi — kiểm tra lại worksheet "
                    "(current_address chỉ có từ sau mốc 16 tuổi và other_addresses_used "
                    "chưa khai Yes/lịch sử nơi ở trước đó)"
                ),
                field_key="other_addresses_history",
                document_type="ds260_customer_form",
            )
        )

    # Mốc thời gian việc làm (khách yêu cầu 2026-08-13) — cảnh báo suy đoán từ text tự do, không
    # phải lỗi cứng chặn export. Cần cả DS-260 worksheet (nguồn duy nhất điền field) lẫn dữ liệu
    # đủ để so — bỏ qua khi chưa có worksheet.
    if has_ds260_worksheet:
        from app.services.ds260_conflicts import load_ds260_field_resolutions
        from app.services.ds260_mapping import detect_work_period_issues

        resolutions = await load_ds260_field_resolutions(db, applicant_id)
        work_issues = detect_work_period_issues(records, resolutions, person_name=person_name or None)

        if "start_after_signed" in work_issues:
            info = work_issues["start_after_signed"]
            warnings.append(
                _issue(
                    code="work_start_after_date_signed",
                    message=(
                        f"Ngày bắt đầu công việc hiện tại ({info['start']}) SAU ngày ký "
                        f"Application form ({info['date_signed']}) — kiểm tra lại, có thể khách "
                        "ghi sai ngày."
                    ),
                    field_key="work_start_date",
                    document_type="ds260_customer_form",
                )
            )

        if "overlapping_periods" in work_issues:
            warnings.append(
                _issue(
                    code="work_periods_overlap",
                    message=(
                        "Phát hiện 2 công việc (hiện tại/lịch sử làm việc) trùng thời điểm — "
                        "kiểm tra lại mốc thời gian trong DS-260 khách khai."
                    ),
                    field_key="work_prior_jobs_history",
                    document_type="ds260_customer_form",
                )
            )

        if "current_matches_closed_prior" in work_issues:
            warnings.append(
                _issue(
                    code="work_current_looks_like_past",
                    message=(
                        "Công việc HIỆN TẠI có vẻ trùng công ty/nghề nghiệp với 1 mục ĐÃ CÓ ngày "
                        "kết thúc trong lịch sử làm việc — có thể khách ghi nhầm, công việc này "
                        "thực ra đã nghỉ. Kiểm tra lại giấy tờ gốc."
                    ),
                    field_key="work_present_employer",
                    document_type="ds260_customer_form",
                )
            )

    return {
        "valid": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "filled_count": form.get("filled_count", 0),
        "total_count": form.get("total_count", 0),
    }
