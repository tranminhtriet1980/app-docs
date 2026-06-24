import hashlib

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Document


def file_sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


async def find_duplicate(
    db: AsyncSession,
    *,
    file_hash: str,
    applicant_id=None,
    exclude_document_id=None,
) -> Document | None:
    q = select(Document).where(Document.file_hash == file_hash)
    if applicant_id:
        q = q.where(Document.applicant_id == applicant_id)
    if exclude_document_id:
        q = q.where(Document.id != exclude_document_id)
    result = await db.execute(q.limit(1))
    return result.scalar_one_or_none()
