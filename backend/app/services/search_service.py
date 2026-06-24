import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import Applicant, Document, ExtractedField, User
from app.services.permissions import is_admin
from app.services.tags_util import parse_tags


async def search_records(
    db: AsyncSession,
    user: User,
    *,
    q: str,
    limit: int = 40,
) -> dict:
    term = f"%{q.strip()}%"
    if len(q.strip()) < 2:
        return {"query": q, "applicants": [], "documents": []}

    app_q = select(Applicant).where(
        Applicant.deleted_at.is_(None),
        or_(
            Applicant.display_name.ilike(term),
            Applicant.notes.ilike(term),
            Applicant.client_name.ilike(term),
            Applicant.project_name.ilike(term),
            Applicant.department.ilike(term),
            Applicant.tags.ilike(term),
        ),
    )
    if not is_admin(user):
        app_q = app_q.where(Applicant.user_id == user.id)
    app_q = app_q.order_by(Applicant.updated_at.desc()).limit(limit)
    applicants = (await db.execute(app_q)).scalars().all()

    doc_q = (
        select(Document)
        .join(Applicant, Document.applicant_id == Applicant.id)
        .where(
            Applicant.deleted_at.is_(None),
            or_(
                Document.original_filename.ilike(term),
                Document.document_type.ilike(term),
                Document.tags.ilike(term),
            ),
        )
        .options(selectinload(Document.applicant))
    )
    if not is_admin(user):
        doc_q = doc_q.where(Applicant.user_id == user.id)
    doc_q = doc_q.order_by(Document.uploaded_at.desc()).limit(limit)
    docs_by_meta = (await db.execute(doc_q)).scalars().all()

    content_q = (
        select(Document)
        .join(Applicant, Document.applicant_id == Applicant.id)
        .join(ExtractedField, ExtractedField.document_id == Document.id)
        .where(Applicant.deleted_at.is_(None), ExtractedField.field_value.ilike(term))
        .options(selectinload(Document.applicant))
    )
    if not is_admin(user):
        content_q = content_q.where(Applicant.user_id == user.id)
    content_q = content_q.order_by(Document.uploaded_at.desc()).limit(limit)
    docs_by_content = (await db.execute(content_q)).scalars().all()

    seen: set[uuid.UUID] = set()
    documents_out = []
    for doc in list(docs_by_meta) + list(docs_by_content):
        if doc.id in seen:
            continue
        seen.add(doc.id)
        documents_out.append(
            {
                "id": str(doc.id),
                "applicant_id": str(doc.applicant_id),
                "applicant_name": doc.applicant.display_name if doc.applicant else "",
                "filename": doc.original_filename,
                "document_type": doc.document_type,
                "status": doc.status.value,
                "tags": parse_tags(doc.tags),
            }
        )

    return {
        "query": q.strip(),
        "applicants": [
            {
                "id": str(a.id),
                "display_name": a.display_name,
                "status": a.status.value,
                "client_name": a.client_name,
                "project_name": a.project_name,
                "department": a.department,
                "tags": parse_tags(a.tags),
            }
            for a in applicants
        ],
        "documents": documents_out[:limit],
    }
