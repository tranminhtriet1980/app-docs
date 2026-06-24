"""Xóa vĩnh viễn toàn bộ dữ liệu hồ sơ — DB + file trên đĩa."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.entities import (
    Applicant,
    ApplicantDocRecord,
    ApiUsageLog,
    CaseMember,
    Conflict,
    Document,
    Export,
    ExtractedField,
    ProfileField,
)


async def purge_applicant_completely(db: AsyncSession, applicant_id: uuid.UUID) -> dict[str, int]:
    """
    Xóa sạch mọi bản ghi liên quan tới applicant_id rồi xóa applicant.
    Trả về số lượng đã xóa (ước lượng) để audit.
    """
    applicant = await db.get(Applicant, applicant_id)
    if not applicant:
        return {"applicant": 0}

    docs_result = await db.execute(select(Document).where(Document.applicant_id == applicant_id))
    documents = list(docs_result.scalars().all())
    doc_ids = [d.id for d in documents]

    exports_result = await db.execute(select(Export).where(Export.applicant_id == applicant_id))
    exports = list(exports_result.scalars().all())

    upload_dirs: set[Path] = set()
    for doc in documents:
        parent = Path(doc.file_path).parent
        upload_dirs.add(parent)

    export_paths = [Path(e.file_path) for e in exports if e.file_path]
    export_dir = settings.export_path / str(applicant_id)

    extracted = 0
    if doc_ids:
        extracted_result = await db.execute(
            delete(ExtractedField).where(ExtractedField.document_id.in_(doc_ids))
        )
        extracted = extracted_result.rowcount or 0

    doc_records_result = await db.execute(
        delete(ApplicantDocRecord).where(ApplicantDocRecord.applicant_id == applicant_id)
    )
    conflicts_result = await db.execute(delete(Conflict).where(Conflict.applicant_id == applicant_id))
    profile_result = await db.execute(delete(ProfileField).where(ProfileField.applicant_id == applicant_id))
    exports_del = await db.execute(delete(Export).where(Export.applicant_id == applicant_id))

    usage_applicant = await db.execute(
        delete(ApiUsageLog).where(ApiUsageLog.applicant_id == applicant_id)
    )
    if doc_ids:
        await db.execute(delete(ApiUsageLog).where(ApiUsageLog.document_id.in_(doc_ids)))

    documents_result = await db.execute(delete(Document).where(Document.applicant_id == applicant_id))
    members_result = await db.execute(delete(CaseMember).where(CaseMember.applicant_id == applicant_id))

    await db.delete(applicant)
    await db.flush()

    _remove_paths(export_paths)
    _remove_dir(export_dir)
    for folder in upload_dirs:
        _remove_dir(folder)
    # Thư mục uploads/{applicant_id} nếu còn sót file
    _remove_dir(settings.upload_path / str(applicant_id))

    return {
        "applicant": 1,
        "documents": documents_result.rowcount or len(documents),
        "extracted_fields": extracted,
        "doc_records": doc_records_result.rowcount or 0,
        "conflicts": conflicts_result.rowcount or 0,
        "profile_fields": profile_result.rowcount or 0,
        "exports": exports_del.rowcount or len(exports),
        "case_members": members_result.rowcount or 0,
        "api_usage_logs": usage_applicant.rowcount or 0,
    }


def _remove_paths(paths: list[Path]) -> None:
    for path in paths:
        try:
            if path.is_file():
                path.unlink()
        except OSError:
            pass


def _remove_dir(path: Path) -> None:
    try:
        if path.is_dir():
            shutil.rmtree(path)
    except OSError:
        pass
