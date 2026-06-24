import uuid
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_applicant
from app.database import get_db
from app.models.entities import Applicant, ApplicantDocRecord, Conflict, ConflictStatus, Document, ProfileField, User
from app.services.document_registry import RECORDABLE_DOC_TYPES, RECORDABLE_REGISTRY_BY_CODE
from app.services.profile_seed import apply_profile_seed, list_seeds
from app.schemas import (
    ConflictOut,
    ConflictResolve,
    DocRecordFieldUpdate,
    DocRecordOut,
    DocTableSummaryOut,
    Ds260FieldUpdate,
    Ds260FormOut,
    Ds260MappingOut,
    Ds260MappingSectionOut,
    Ds260MappingFieldOut,
    Ds260ValidationOut,
    MessageOut,
    ProfileFieldOut,
    ProfileFieldUpdate,
    ProfileSeedApply,
)
from app.services.doc_record_sync import (
    list_doc_records,
    list_reference_table_summaries,
    list_table_summaries,
    record_to_dict,
    update_doc_record_field,
)
from app.services.ds260_conflicts import (
    conflict_label_vi,
    conflict_type_from_field_key,
    ds260_manual_field_key,
    is_ds260_conflict_field,
    list_open_ds260_conflicts,
)
from app.services.auth import get_current_user
from app.services.permissions import can_edit_applicant_profile
from app.services.ds260_mapping import flatten_ds260_mappings, load_ds260_mapping, load_ds260_sections, resolve_ds260_form
from app.services.ds260_validate import validate_ds260

router = APIRouter(prefix="/applicants", tags=["profile"])


@router.get("/config/ds260-mapping", response_model=Ds260MappingOut)
async def get_ds260_mapping_config():
    """Bảng cấu hình DS260: field → document_type + source_field."""
    raw = load_ds260_mapping()
    sections = []
    for sec in load_ds260_sections():
        sections.append(
            Ds260MappingSectionOut(
                id=sec.id,
                title=sec.title,
                subtitle=sec.subtitle,
                fields=[
                    Ds260MappingFieldOut(
                        key=f.key,
                        label=f.label,
                        document=f.document,
                        field=f.field,
                        aliases=list(f.aliases),
                    )
                    for f in sec.fields
                ],
            )
        )
    return Ds260MappingOut(
        version=raw.get("version", 1),
        description=raw.get("description", ""),
        sections=sections,
    )


def _doc_record_out(record, filename: str | None) -> DocRecordOut:
    data = record_to_dict(record)
    return DocRecordOut(
        id=record.id,
        doc_type=data["doc_type"],
        display_name=data["display_name"],
        form_section=data["form_section"],
        variant=data["variant"],
        source_document_id=record.source_document_id,
        source_document_filename=filename,
        raw_data=data["raw_data"],
        form_data=data["form_data"],
        updated_at=record.updated_at,
    )


async def _filename_map(db: AsyncSession, records) -> dict[str, str]:
    doc_ids = [r.source_document_id for r in records if r.source_document_id]
    if not doc_ids:
        return {}
    result = await db.execute(select(Document).where(Document.id.in_(doc_ids)))
    return {str(doc.id): doc.original_filename or "" for doc in result.scalars().all()}


@router.patch("/{applicant_id}/profile/fields/{field_key:path}", response_model=ProfileFieldOut)
async def update_profile_field(
    field_key: str,
    body: ProfileFieldUpdate,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    if not can_edit_applicant_profile(user, applicant):
        raise HTTPException(status_code=403, detail="Chỉ chủ hồ sơ được chỉnh sửa các trường này")
    result = await db.execute(
        select(ProfileField).where(
            ProfileField.applicant_id == applicant.id,
            ProfileField.field_key == field_key,
        )
    )
    pf = result.scalar_one_or_none()
    if pf:
        pf.field_value = body.field_value
        pf.is_manual = True
        pf.updated_at = datetime.now(timezone.utc)
    else:
        pf = ProfileField(
            applicant_id=applicant.id,
            field_key=field_key,
            field_value=body.field_value,
            is_manual=True,
        )
        db.add(pf)
    await db.commit()
    await db.refresh(pf)
    return ProfileFieldOut(
        field_key=pf.field_key,
        field_value=pf.field_value,
        source_document_id=pf.source_document_id,
        confidence=pf.confidence,
        is_manual=pf.is_manual,
        updated_at=pf.updated_at,
    )


@router.post("/{applicant_id}/profile/apply-seed", response_model=MessageOut)
async def apply_ds160_seed(
    body: ProfileSeedApply,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    if not can_edit_applicant_profile(user, applicant):
        raise HTTPException(status_code=403, detail="Chỉ chủ hồ sơ được chỉnh sửa các trường này")
    try:
        stats = await apply_profile_seed(
            db,
            applicant.id,
            body.seed_name,
            fill_empty_only=body.fill_empty_only,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await db.commit()
    return MessageOut(
        message=(
            f"Đã áp dụng seed '{body.seed_name}': "
            f"+{stats['added']} mới, ~{stats['updated']} cập nhật, "
            f"{stats['skipped']} giữ nguyên (đã có dữ liệu)."
        )
    )


@router.get("/profile-seeds", response_model=list[str])
async def get_profile_seeds():
    return list_seeds()


@router.post("/{applicant_id}/conflicts/{conflict_id}/resolve", response_model=ConflictOut)
async def resolve_conflict(
    conflict_id: uuid.UUID,
    body: ConflictResolve,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    if not can_edit_applicant_profile(user, applicant):
        raise HTTPException(status_code=403, detail="Chỉ chủ hồ sơ được giải quyết xung đột")
    result = await db.execute(
        select(Conflict).where(Conflict.id == conflict_id, Conflict.applicant_id == applicant.id)
    )
    conflict = result.scalar_one_or_none()
    if not conflict:
        raise HTTPException(status_code=404, detail="Conflict not found")

    conflict.status = ConflictStatus.resolved
    conflict.resolved_value = body.resolved_value
    conflict.resolved_at = datetime.now(timezone.utc)

    if not is_ds260_conflict_field(conflict.field_key):
        pf_result = await db.execute(
            select(ProfileField).where(
                ProfileField.applicant_id == applicant.id,
                ProfileField.field_key == conflict.field_key,
            )
        )
        pf = pf_result.scalar_one_or_none()
        if pf:
            pf.field_value = body.resolved_value
            pf.is_manual = True
        else:
            db.add(
                ProfileField(
                    applicant_id=applicant.id,
                    field_key=conflict.field_key,
                    field_value=body.resolved_value,
                    is_manual=True,
                )
            )
    await db.commit()
    await db.refresh(conflict)
    return conflict


@router.get("/{applicant_id}/tables", response_model=list[DocTableSummaryOut])
async def list_document_tables(
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """8 bảng mẫu + số file đã lưu (standard / reference)."""
    summaries = await list_table_summaries(db, applicant.id)
    return [DocTableSummaryOut(**s) for s in summaries]


@router.get("/{applicant_id}/tables/reference", response_model=list[DocTableSummaryOut])
async def list_reference_document_tables(
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Bảng nguồn đối chiếu DS-260 — khách upload (_new), 4 loại Luồng 1."""
    summaries = await list_reference_table_summaries(db, applicant.id)
    return [DocTableSummaryOut(**s) for s in summaries]


@router.get("/{applicant_id}/tables/{doc_type}", response_model=list[DocRecordOut])
async def get_document_table(
    doc_type: str,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    variant: str | None = None,
):
    """Lấy toàn bộ dòng trong một bảng (mỗi dòng = một file upload). variant: standard | exception."""
    if doc_type not in RECORDABLE_DOC_TYPES:
        raise HTTPException(status_code=404, detail=f"Unknown table type: {doc_type}")
    if variant and variant not in {"standard", "exception"}:
        raise HTTPException(status_code=400, detail="variant must be standard or exception")

    records = await list_doc_records(db, applicant.id, doc_type=doc_type, variant=variant)
    names = await _filename_map(db, records)
    return [
        _doc_record_out(r, names.get(str(r.source_document_id)))
        for r in records
    ]


@router.get("/{applicant_id}/doc-records", response_model=list[DocRecordOut])
async def get_doc_records(
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    doc_type: str | None = None,
    document_id: uuid.UUID | None = None,
):
    """Tất cả bản ghi theo file — lọc theo doc_type hoặc document_id."""
    records = await list_doc_records(
        db, applicant.id, doc_type=doc_type, document_id=document_id
    )
    names = await _filename_map(db, records)
    return [
        _doc_record_out(r, names.get(str(r.source_document_id)))
        for r in records
    ]


@router.patch("/{applicant_id}/doc-records/{record_id}/fields/{field_key:path}", response_model=DocRecordOut)
async def patch_doc_record_field(
    record_id: uuid.UUID,
    field_key: str,
    body: DocRecordFieldUpdate,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Chỉnh tay field OCR trên từng file giấy tờ — ảnh hưởng DS-260 khi resolve lại."""
    if not can_edit_applicant_profile(user, applicant):
        raise HTTPException(status_code=403, detail="Không có quyền chỉnh sửa giấy tờ")

    result = await db.execute(
        select(ApplicantDocRecord).where(
            ApplicantDocRecord.id == record_id,
            ApplicantDocRecord.applicant_id == applicant.id,
        )
    )
    record = result.scalar_one_or_none()
    if not record:
        raise HTTPException(status_code=404, detail="Doc record not found")

    update_doc_record_field(record, field_key, body.value)
    await db.commit()
    await db.refresh(record)

    filename = None
    if record.source_document_id:
        doc = await db.get(Document, record.source_document_id)
        filename = doc.original_filename if doc else None
    return _doc_record_out(record, filename)


@router.get("/{applicant_id}/ds260-form", response_model=Ds260FormOut)
async def get_ds260_form(
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    member_id: uuid.UUID | None = Query(None),
):
    """
    Fill DS260 từng field từ document chỉ định — không merge profile.
    Bộ hồ sơ gia đình: truyền member_id để xem DS-260 của từng người.
    """
    records = await list_doc_records(db, applicant.id)
    names = await _filename_map(db, records)
    data = await resolve_ds260_form(db, applicant.id, filename_map=names, member_id=member_id)
    return Ds260FormOut(**data)


@router.patch("/{applicant_id}/ds260-form/fields/{field_key}", response_model=Ds260FormOut)
async def update_ds260_form_field(
    field_key: str,
    body: Ds260FieldUpdate,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    member_id: uuid.UUID | None = Query(None),
):
    """Chỉnh tay giá trị DS-260 trước khi xuất Word — ưu tiên cao hơn OCR/mapping."""
    if not can_edit_applicant_profile(user, applicant):
        raise HTTPException(status_code=403, detail="Không có quyền chỉnh sửa DS-260")

    if field_key not in flatten_ds260_mappings():
        raise HTTPException(status_code=404, detail=f"Unknown DS-260 field: {field_key}")

    storage_key = ds260_manual_field_key(field_key, str(member_id) if member_id else None)
    result = await db.execute(
        select(ProfileField).where(
            ProfileField.applicant_id == applicant.id,
            ProfileField.field_key == storage_key,
        )
    )
    pf = result.scalar_one_or_none()
    value = (body.value or "").strip()

    from app.services.ds260_dates import format_ds260_display_date, is_date_field_key

    if value and is_date_field_key(field_key):
        formatted = format_ds260_display_date(value)
        if formatted:
            value = formatted

    if not value:
        if pf:
            await db.delete(pf)
    elif pf:
        pf.field_value = value
        pf.is_manual = True
        pf.updated_at = datetime.now(timezone.utc)
    else:
        db.add(
            ProfileField(
                applicant_id=applicant.id,
                field_key=storage_key,
                field_value=value,
                is_manual=True,
            )
        )
    await db.commit()

    records = await list_doc_records(db, applicant.id)
    names = await _filename_map(db, records)
    data = await resolve_ds260_form(db, applicant.id, filename_map=names, member_id=member_id)
    return Ds260FormOut(**data)


@router.get("/{applicant_id}/ds260-validate", response_model=Ds260ValidationOut)
async def get_ds260_validation(
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Validate DS260 trước approve / export."""
    records = await list_doc_records(db, applicant.id)
    names = await _filename_map(db, records)
    result = await validate_ds260(db, applicant.id, filename_map=names)
    return Ds260ValidationOut(**result)


@router.get("/{applicant_id}/ds260-conflicts", response_model=list[ConflictOut])
async def get_ds260_conflicts(
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Xung đột Luồng 1 vs _new và Luồng 1 vs DS-260 worksheet."""
    conflicts = await list_open_ds260_conflicts(db, applicant.id)
    doc_ids = {c.document_a_id for c in conflicts if c.document_a_id} | {
        c.document_b_id for c in conflicts if c.document_b_id
    }
    names: dict[uuid.UUID, str] = {}
    if doc_ids:
        doc_result = await db.execute(select(Document).where(Document.id.in_(doc_ids)))
        names = {doc.id: doc.original_filename or "" for doc in doc_result.scalars().all()}

    out: list[ConflictOut] = []
    for c in conflicts:
        base = ConflictOut.model_validate(c)
        out.append(
            base.model_copy(
                update={
                    "document_a_filename": names.get(c.document_a_id) if c.document_a_id else None,
                    "document_b_filename": names.get(c.document_b_id) if c.document_b_id else None,
                    "conflict_type": conflict_type_from_field_key(c.field_key),
                    "field_label": conflict_label_vi(c.field_key),
                }
            )
        )
    return out
