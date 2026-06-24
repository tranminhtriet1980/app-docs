"""Lưu dữ liệu OpenAI/OCR theo từng file → từng bảng (doc_type). Không merge vào profile."""

from __future__ import annotations

import json
import uuid

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Applicant, ApplicantDocRecord, ApplicantStatus, Document, DocumentStatus, ExtractedField
from app.services.document_registry import (
    DOCUMENT_REGISTRY,
    RECORDABLE_DOC_TYPES,
    RECORDABLE_REGISTRY_BY_CODE,
    SUPPLEMENTAL_DOCUMENT_REGISTRY,
    build_form_data,
    parse_document_filename,
)


async def _extracted_to_raw(db: AsyncSession, document_id: uuid.UUID) -> dict[str, str]:
    result = await db.execute(select(ExtractedField).where(ExtractedField.document_id == document_id))
    raw: dict[str, str] = {}
    for ef in result.scalars().all():
        if ef.field_value:
            raw[ef.field_key] = ef.field_value.strip()
    return raw


async def sync_doc_record_from_document(db: AsyncSession, document: Document) -> ApplicantDocRecord | None:
    """
    Một file → một dòng trong bảng doc_type tương ứng.
    Chỉ lưu raw_data (OCR gốc) và form_data (chuẩn hóa theo mẫu form) — không map sang profile.
    """
    registry_type, is_exception = parse_document_filename(document.original_filename or "")
    doc_type = registry_type or document.document_type
    if not doc_type or doc_type not in RECORDABLE_DOC_TYPES:
        return None

    variant = "exception" if is_exception else "standard"
    raw = await _extracted_to_raw(db, document.id)
    form_data = build_form_data(doc_type, raw)

    result = await db.execute(
        select(ApplicantDocRecord).where(ApplicantDocRecord.source_document_id == document.id)
    )
    record = result.scalar_one_or_none()
    if record:
        record.doc_type = doc_type
        record.variant = variant
        record.raw_data = json.dumps(raw, ensure_ascii=False)
        record.form_data = json.dumps(form_data, ensure_ascii=False)
        record.profile_data = "{}"
    else:
        record = ApplicantDocRecord(
            applicant_id=document.applicant_id,
            doc_type=doc_type,
            variant=variant,
            source_document_id=document.id,
            raw_data=json.dumps(raw, ensure_ascii=False),
            form_data=json.dumps(form_data, ensure_ascii=False),
            profile_data="{}",
        )
        db.add(record)

    document.registry_doc_type = doc_type
    document.is_exception = is_exception
    await db.flush()
    return record


async def finalize_applicant_after_ocr(db: AsyncSession, applicant_id: uuid.UUID) -> None:
    """Đặt trạng thái hồ sơ sau OCR — không gọi merge profile."""
    applicant = await db.get(Applicant, applicant_id)
    if not applicant:
        return
    pending = await db.scalar(
        select(func.count())
        .select_from(Document)
        .where(
            Document.applicant_id == applicant_id,
            Document.status.in_([DocumentStatus.uploaded, DocumentStatus.processing]),
        )
    )
    if pending and pending > 0:
        applicant.status = ApplicantStatus.processing
    else:
        applicant.status = ApplicantStatus.review
    from app.services.ds260_conflicts import sync_ds260_doc_conflicts

    await sync_ds260_doc_conflicts(db, applicant_id)


async def list_doc_records(
    db: AsyncSession,
    applicant_id: uuid.UUID,
    *,
    doc_type: str | None = None,
    document_id: uuid.UUID | None = None,
    variant: str | None = None,
) -> list[ApplicantDocRecord]:
    q = select(ApplicantDocRecord).where(ApplicantDocRecord.applicant_id == applicant_id)
    if doc_type:
        q = q.where(ApplicantDocRecord.doc_type == doc_type)
    if document_id:
        q = q.where(ApplicantDocRecord.source_document_id == document_id)
    if variant:
        q = q.where(ApplicantDocRecord.variant == variant)
    q = q.order_by(ApplicantDocRecord.doc_type, ApplicantDocRecord.variant, ApplicantDocRecord.updated_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())


async def get_doc_record_for_document(
    db: AsyncSession, applicant_id: uuid.UUID, document_id: uuid.UUID
) -> ApplicantDocRecord | None:
    result = await db.execute(
        select(ApplicantDocRecord).where(
            ApplicantDocRecord.applicant_id == applicant_id,
            ApplicantDocRecord.source_document_id == document_id,
        )
    )
    return result.scalar_one_or_none()


async def delete_doc_records_for_document(db: AsyncSession, document_id: uuid.UUID) -> None:
    await db.execute(
        delete(ApplicantDocRecord).where(ApplicantDocRecord.source_document_id == document_id)
    )


def record_to_dict(record: ApplicantDocRecord) -> dict:
    defn = RECORDABLE_REGISTRY_BY_CODE.get(record.doc_type)
    return {
        "id": str(record.id),
        "doc_type": record.doc_type,
        "display_name": defn.display_name if defn else record.doc_type,
        "form_section": defn.form_section if defn else "",
        "variant": record.variant,
        "source_document_id": str(record.source_document_id) if record.source_document_id else None,
        "raw_data": json.loads(record.raw_data or "{}"),
        "form_data": json.loads(record.form_data or "{}"),
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
    }


def update_doc_record_field(record: ApplicantDocRecord, field_key: str, value: str) -> None:
    """Chỉnh tay field OCR trên bản ghi giấy tờ — cập nhật cả form_data và raw_data."""
    form = json.loads(record.form_data or "{}")
    raw = json.loads(record.raw_data or "{}")
    trimmed = (value or "").strip()
    if trimmed:
        form[field_key] = trimmed
        raw[field_key] = trimmed
    else:
        form.pop(field_key, None)
        raw.pop(field_key, None)
    record.form_data = json.dumps(form, ensure_ascii=False)
    record.raw_data = json.dumps(raw, ensure_ascii=False)


async def list_table_summaries(db: AsyncSession, applicant_id: uuid.UUID) -> list[dict]:
    """Danh sách bảng + số dòng standard / reference (đối chiếu)."""
    from app.services.ds260_conflicts import LUONG1_DOC_TYPES

    result = await db.execute(
        select(ApplicantDocRecord.doc_type, ApplicantDocRecord.variant, func.count())
        .where(ApplicantDocRecord.applicant_id == applicant_id)
        .group_by(ApplicantDocRecord.doc_type, ApplicantDocRecord.variant)
    )
    counts: dict[str, dict[str, int]] = {}
    for doc_type, variant, cnt in result.all():
        counts.setdefault(doc_type, {"standard": 0, "exception": 0})
        counts[doc_type][variant] = cnt

    summaries: list[dict] = []
    for defn in DOCUMENT_REGISTRY:
        code = defn.code
        by_variant = counts.get(code, {"standard": 0, "exception": 0})
        std = by_variant.get("standard", 0)
        ref = by_variant.get("exception", 0)
        summaries.append(
            {
                "doc_type": code,
                "display_name": defn.display_name,
                "form_section": defn.form_section,
                "record_count": std + ref,
                "standard_count": std,
                "reference_count": ref,
                "supports_reference": code in LUONG1_DOC_TYPES,
            }
        )
    for defn in SUPPLEMENTAL_DOCUMENT_REGISTRY:
        code = defn.code
        by_variant = counts.get(code, {"standard": 0, "exception": 0})
        std = by_variant.get("standard", 0)
        ref = by_variant.get("exception", 0)
        summaries.append(
            {
                "doc_type": code,
                "display_name": defn.display_name,
                "form_section": defn.form_section,
                "record_count": std + ref,
                "standard_count": std,
                "reference_count": ref,
                "supports_reference": False,
            }
        )
    if counts.get("address_document"):
        by_variant = counts["address_document"]
        summaries.append(
            {
                "doc_type": "address_document",
                "display_name": "Address document",
                "form_section": "Địa chỉ / liên lạc (OCR)",
                "record_count": by_variant.get("standard", 0) + by_variant.get("exception", 0),
                "standard_count": by_variant.get("standard", 0),
                "reference_count": by_variant.get("exception", 0),
                "supports_reference": False,
            }
        )
    return summaries


async def list_reference_table_summaries(db: AsyncSession, applicant_id: uuid.UUID) -> list[dict]:
    """Bảng nguồn đối chiếu DS-260 — luôn trả 4 loại Luồng 1 (kể cả chưa upload)."""
    from app.services.ds260_conflicts import LUONG1_DOC_TYPES

    all_summaries = await list_table_summaries(db, applicant_id)
    by_type = {s["doc_type"]: s for s in all_summaries}
    out: list[dict] = []
    for defn in DOCUMENT_REGISTRY:
        if defn.code not in LUONG1_DOC_TYPES:
            continue
        base = by_type.get(defn.code, {})
        out.append(
            {
                "doc_type": defn.code,
                "display_name": defn.display_name,
                "form_section": "DS-260 — Nguồn đối chiếu (khách upload)",
                "record_count": base.get("reference_count", 0),
                "standard_count": base.get("standard_count", 0),
                "reference_count": base.get("reference_count", 0),
                "supports_reference": True,
                "upload_hint": f"{defn.display_name}_new.pdf",
            }
        )
    ds260_base = by_type.get("ds260_customer_form", {})
    out.append(
        {
            "doc_type": "ds260_customer_form",
            "display_name": "DS-260 (khách khai)",
            "form_section": "DS-260 mục 3–5 — Address, Contact, Social Media",
            "record_count": ds260_base.get("reference_count", 0) + ds260_base.get("standard_count", 0),
            "standard_count": ds260_base.get("standard_count", 0),
            "reference_count": ds260_base.get("reference_count", 0),
            "supports_reference": True,
            "upload_hint": "ds260.pdf hoặc DS260_new.pdf",
        }
    )
    return out
