import json
import logging
import uuid
from functools import lru_cache
from pathlib import Path
from typing import Annotated

import aiofiles
from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_owned_applicant
from app.config import settings
from app.database import async_session, get_db
from app.models.entities import Applicant, ApplicantDocRecord, ApplicantStatus, Document, DocumentStatus
from app.schemas import DocumentDetailOut, DocumentOut, DocumentTagsUpdate, DocumentTypeGuideOut, DocRecordOut, MessageOut
from app.services.document_registry import (
    CANONICAL_FILENAME_EXAMPLES,
    DOCUMENT_REGISTRY,
    EXCEPTION_SUFFIX,
    SUPPLEMENTAL_DOCUMENT_REGISTRY,
)
from app.services.family_case import (
    DocumentLabelInput,
    load_case_members,
    members_for_document_labeling,
    resolve_document_member_labels_batch,
)
from app.services.duplicate_check import file_sha256, find_duplicate
from app.services.tags_util import dump_tags, parse_tags
from app.services.doc_record_sync import (
    delete_doc_records_for_document,
    finalize_applicant_after_ocr,
    get_doc_record_for_document,
    record_to_dict,
    sync_doc_record_from_document,
)
from app.services.ocr_pipeline import process_document

logger = logging.getLogger(__name__)


def _document_sort_key(doc: DocumentOut) -> tuple[int, int, str]:
    member_num = int(doc.member_number) if doc.member_number and doc.member_number.isdigit() else 99
    file_seq = 99
    label = doc.member_file_label or ""
    if "_" in label:
        tail = label.split("_", 1)[1]
        if tail.isdigit():
            file_seq = int(tail)
    return (member_num, file_seq, (doc.original_filename or "").lower())

router = APIRouter(tags=["documents"])


@lru_cache(maxsize=1)
def _standard_field_labels() -> dict[str, dict[str, str]]:
    path = Path(__file__).resolve().parents[2] / "data" / "doc_schemas" / "standard_templates.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, str]] = {}
    for code, info in data.get("types", {}).items():
        out[code] = {
            key: meta.get("label", key) for key, meta in info.get("fields", {}).items()
        }
    return out


@router.get("/document-types", response_model=list[DocumentTypeGuideOut])
async def list_document_types():
    """Standard template naming guide (Data test folder)."""
    labels_by_type = _standard_field_labels()
    items: list[DocumentTypeGuideOut] = []
    for defn in DOCUMENT_REGISTRY:
        names = CANONICAL_FILENAME_EXAMPLES.get(defn.code, {})
        items.append(
            DocumentTypeGuideOut(
                code=defn.code,
                display_name=defn.display_name,
                form_section=defn.form_section,
                standard_filename=names.get("standard", defn.display_name),
                exception_filename=names.get("exception", f"{defn.display_name}{EXCEPTION_SUFFIX}"),
                extract_keys=list(defn.extract_keys),
                field_labels=labels_by_type.get(defn.code, {}),
            )
        )
    for defn in SUPPLEMENTAL_DOCUMENT_REGISTRY:
        names = CANONICAL_FILENAME_EXAMPLES.get(defn.code, {})
        items.append(
            DocumentTypeGuideOut(
                code=defn.code,
                display_name=defn.display_name,
                form_section=defn.form_section,
                standard_filename=names.get("standard", defn.display_name),
                exception_filename=names.get("exception", f"{defn.display_name}{EXCEPTION_SUFFIX}"),
                extract_keys=list(defn.extract_keys),
                field_labels=labels_by_type.get(defn.code, {}),
            )
        )
    return items

ALLOWED_MIME = {
    "application/pdf",
    "image/jpeg",
    "image/png",
    "image/webp",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    "text/plain",
}
ALLOWED_EXT = {".pdf", ".jpg", ".jpeg", ".png", ".webp", ".doc", ".docx", ".xlsx", ".xls", ".txt"}
MAX_SIZE = 50 * 1024 * 1024


def _doc_out(
    document: Document,
    *,
    member_number: str | None = None,
    member_display_name: str | None = None,
    member_file_label: str | None = None,
) -> DocumentOut:
    return DocumentOut(
        id=document.id,
        applicant_id=document.applicant_id,
        original_filename=document.original_filename,
        mime_type=document.mime_type,
        file_size=document.file_size,
        document_type=document.document_type,
        registry_doc_type=document.registry_doc_type,
        is_exception=document.is_exception,
        classification_confidence=document.classification_confidence,
        status=document.status,
        error_message=document.error_message,
        tags=parse_tags(document.tags),
        duplicate_warning=document.duplicate_warning,
        member_number=member_number,
        member_display_name=member_display_name,
        member_file_label=member_file_label,
        uploaded_at=document.uploaded_at,
        processed_at=document.processed_at,
    )


async def _documents_out(db: AsyncSession, applicant_id: uuid.UUID, documents: list[Document]) -> list[DocumentOut]:
    applicant = await db.get(Applicant, applicant_id)
    members = await load_case_members(db, applicant_id)
    label_members = members_for_document_labeling(applicant, members)

    rec_by_doc_id: dict[uuid.UUID, ApplicantDocRecord] = {}
    rec_result = await db.execute(
        select(ApplicantDocRecord).where(ApplicantDocRecord.applicant_id == applicant_id)
    )
    for rec in rec_result.scalars().all():
        if rec.source_document_id:
            rec_by_doc_id[rec.source_document_id] = rec

    label_inputs = [
        DocumentLabelInput(
            document_id=document.id,
            filename=document.original_filename,
            registry_doc_type=document.registry_doc_type,
            doc_record=rec_by_doc_id.get(document.id),
            uploaded_at=document.uploaded_at,
        )
        for document in documents
    ]
    labels = resolve_document_member_labels_batch(items=label_inputs, members=label_members)

    out: list[DocumentOut] = []
    for document in documents:
        num, name, label = labels.get(document.id, (None, None, None))
        out.append(
            _doc_out(
                document,
                member_number=num,
                member_display_name=name,
                member_file_label=label,
            )
        )
    out.sort(key=_document_sort_key)
    return out


def _mime_ok(filename: str | None, content_type: str | None) -> bool:
    if content_type and content_type in ALLOWED_MIME:
        return True
    ext = Path(filename or "").suffix.lower()
    return ext in ALLOWED_EXT


async def _save_upload(
    db: AsyncSession,
    applicant: Applicant,
    *,
    filename: str,
    content: bytes,
    content_type: str,
) -> Document:
    doc_id = uuid.uuid4()
    ext = Path(filename or "upload.bin").suffix or ".bin"
    dest_dir = settings.upload_path / str(applicant.id) / str(doc_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"original{ext}"

    async with aiofiles.open(dest_path, "wb") as f:
        await f.write(content)

    fhash = file_sha256(content)
    dup = await find_duplicate(db, file_hash=fhash, applicant_id=applicant.id)

    document = Document(
        id=doc_id,
        applicant_id=applicant.id,
        original_filename=filename or "unknown",
        file_path=str(dest_path),
        mime_type=content_type or "application/octet-stream",
        file_size=len(content),
        status=DocumentStatus.uploaded,
        file_hash=fhash,
        duplicate_warning=dup is not None,
    )
    db.add(document)
    applicant.status = ApplicantStatus.processing
    await db.flush()
    return document


async def _run_applicant_pipeline(applicant_id: uuid.UUID) -> None:
    """OCR từng file → lưu bảng doc_type. Không merge profile."""
    async with async_session() as db:
        applicant = await db.get(Applicant, applicant_id)
        if not applicant:
            return
        applicant.status = ApplicantStatus.processing
        await db.commit()

        result = await db.execute(
            select(Document)
            .where(
                Document.applicant_id == applicant_id,
                Document.status.in_([DocumentStatus.uploaded, DocumentStatus.processing]),
            )
            .order_by(Document.uploaded_at.asc())
        )
        pending = list(result.scalars().all())
        logger.info("Pipeline start applicant=%s pending_docs=%d", applicant_id, len(pending))

        for document in pending:
            doc_id = document.id
            try:
                await process_document(db, document)
                await sync_doc_record_from_document(db, document)
                await db.commit()
                logger.info("Processed doc=%s status=%s", doc_id, document.status.value)
            except Exception as exc:
                await db.rollback()
                logger.exception("OCR failed doc=%s", doc_id)
                doc = await db.get(Document, doc_id)
                if doc:
                    doc.status = DocumentStatus.failed
                    doc.error_message = str(exc)[:2000]
                    await db.commit()

        try:
            await finalize_applicant_after_ocr(db, applicant_id)
            await db.commit()
            logger.info("Pipeline done applicant=%s (no profile merge)", applicant_id)
        except Exception:
            await db.rollback()
            logger.exception("Finalize failed applicant=%s", applicant_id)
            applicant = await db.get(Applicant, applicant_id)
            if applicant:
                applicant.status = ApplicantStatus.review
                await db.commit()


def _schedule_pipeline(background_tasks: BackgroundTasks, applicant_id: uuid.UUID) -> None:
    """One background job per applicant — avoids lost tasks when batch-uploading many files."""
    background_tasks.add_task(_run_applicant_pipeline, applicant_id)


@router.get("/applicants/{applicant_id}/documents", response_model=list[DocumentOut])
async def list_documents(
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Document).where(Document.applicant_id == applicant.id).order_by(Document.uploaded_at.desc())
    )
    docs = list(result.scalars().all())
    return await _documents_out(db, applicant.id, docs)


@router.post("/applicants/{applicant_id}/documents", response_model=DocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    file: UploadFile = File(...),
):
    if not _mime_ok(file.filename, file.content_type):
        raise HTTPException(status_code=400, detail=f"Unsupported file type: {file.content_type}")

    content = await file.read()
    if len(content) > MAX_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")

    document = await _save_upload(
        db,
        applicant,
        filename=file.filename or "unknown",
        content=content,
        content_type=file.content_type or "application/octet-stream",
    )
    _schedule_pipeline(background_tasks, applicant.id)
    await db.commit()
    await db.refresh(document)
    return _doc_out(document)


@router.post("/applicants/{applicant_id}/documents/batch", response_model=list[DocumentOut])
async def upload_documents_batch(
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
    files: list[UploadFile] = File(...),
):
    if not files:
        raise HTTPException(status_code=400, detail="No files provided")
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Maximum 20 files per batch")

    out: list[DocumentOut] = []
    for file in files:
        if not _mime_ok(file.filename, file.content_type):
            continue
        content = await file.read()
        if len(content) > MAX_SIZE:
            continue
        document = await _save_upload(
            db,
            applicant,
            filename=file.filename or "unknown",
            content=content,
            content_type=file.content_type or "application/octet-stream",
        )
        out.append(_doc_out(document))
    if out:
        _schedule_pipeline(background_tasks, applicant.id)
    elif files:
        raise HTTPException(
            status_code=400,
            detail="Không file nào hợp lệ. Chấp nhận PDF, Word, Excel, ảnh, TXT — tối đa 50MB/file.",
        )
    await db.commit()
    return out


@router.patch("/applicants/{applicant_id}/documents/{document_id}/tags", response_model=DocumentOut)
async def update_document_tags(
    document_id: uuid.UUID,
    body: DocumentTagsUpdate,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.applicant_id == applicant.id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    document.tags = dump_tags(body.tags)
    await db.commit()
    await db.refresh(document)
    return _doc_out(document)


@router.get("/applicants/{applicant_id}/documents/{document_id}", response_model=DocumentDetailOut)
async def get_document(
    document_id: uuid.UUID,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Document)
        .where(Document.id == document_id, Document.applicant_id == applicant.id)
        .options(selectinload(Document.extracted_fields))
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentDetailOut(
        **_doc_out(document).model_dump(),
        extracted_fields=document.extracted_fields,
    )


@router.get("/applicants/{applicant_id}/documents/{document_id}/table-record", response_model=DocRecordOut)
async def get_document_table_record(
    document_id: uuid.UUID,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Dữ liệu bảng (theo doc_type) của một file cụ thể — không qua merge profile."""
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.applicant_id == applicant.id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    record = await get_doc_record_for_document(db, applicant.id, document_id)
    if not record:
        raise HTTPException(status_code=404, detail="No table record for this document (unsupported doc type or not processed)")

    data = record_to_dict(record)
    return DocRecordOut(
        id=record.id,
        doc_type=data["doc_type"],
        display_name=data["display_name"],
        form_section=data["form_section"],
        variant=data["variant"],
        source_document_id=record.source_document_id,
        source_document_filename=document.original_filename,
        raw_data=data["raw_data"],
        form_data=data["form_data"],
        updated_at=record.updated_at,
    )


@router.post("/applicants/{applicant_id}/documents/{document_id}/reprocess", response_model=MessageOut)
async def reprocess_document(
    document_id: uuid.UUID,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.applicant_id == applicant.id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    document.status = DocumentStatus.uploaded
    document.processed_at = None
    document.error_message = None
    applicant.status = ApplicantStatus.processing
    await db.commit()
    background_tasks.add_task(_run_applicant_pipeline, applicant.id)
    return MessageOut(message="Reprocessing started")


@router.post("/applicants/{applicant_id}/documents/reprocess-all", response_model=MessageOut)
async def reprocess_all_documents(
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    background_tasks: BackgroundTasks,
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Document).where(Document.applicant_id == applicant.id).order_by(Document.uploaded_at.asc())
    )
    documents = result.scalars().all()
    if not documents:
        raise HTTPException(status_code=404, detail="No documents found")

    for document in documents:
        document.status = DocumentStatus.uploaded
        document.processed_at = None
        document.error_message = None

    applicant.status = ApplicantStatus.processing
    await db.commit()
    background_tasks.add_task(_run_applicant_pipeline, applicant.id)
    return MessageOut(message=f"Reprocessing started for {len(documents)} documents")


@router.get("/applicants/{applicant_id}/documents/{document_id}/file")
async def download_document_file(
    document_id: uuid.UUID,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.applicant_id == applicant.id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")
    path = Path(document.file_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")
    return FileResponse(path, filename=document.original_filename, media_type=document.mime_type)


@router.delete("/applicants/{applicant_id}/documents/{document_id}", response_model=MessageOut)
async def delete_document(
    document_id: uuid.UUID,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    result = await db.execute(
        select(Document).where(Document.id == document_id, Document.applicant_id == applicant.id)
    )
    document = result.scalar_one_or_none()
    if not document:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = Path(document.file_path)
    folder_path = file_path.parent

    await delete_doc_records_for_document(db, document.id)
    await db.delete(document)
    await db.flush()
    await finalize_applicant_after_ocr(db, applicant.id)
    await db.commit()

    # Cleanup file/folder after DB commit; ignore filesystem errors.
    try:
        if file_path.exists():
            file_path.unlink()
        if folder_path.exists():
            folder_path.rmdir()
    except OSError:
        pass

    return MessageOut(message="Document deleted")
