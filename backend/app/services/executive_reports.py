from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import (
    ApiUsageLog,
    Applicant,
    Document,
    DocumentStatus,
    ProfileField,
    User,
)
from app.services.permissions import is_admin


async def executive_dashboard(db: AsyncSession, user: User) -> dict:
    active = Applicant.deleted_at.is_(None)
    today = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)

    app_filter = [active]
    if not is_admin(user):
        app_filter.append(Applicant.user_id == user.id)

    total_applicants = await db.scalar(select(func.count()).select_from(Applicant).where(*app_filter)) or 0

    doc_q = select(func.count()).select_from(Document).join(Applicant, Document.applicant_id == Applicant.id).where(*app_filter)
    total_documents = await db.scalar(doc_q) or 0

    docs_today = await db.scalar(
        select(func.count())
        .select_from(Document)
        .join(Applicant, Document.applicant_id == Applicant.id)
        .where(*app_filter, Document.uploaded_at >= today)
    ) or 0

    new_week = await db.scalar(
        select(func.count()).select_from(Applicant).where(*app_filter, Applicant.created_at >= week_ago)
    ) or 0

    ai_ok = await db.scalar(
        select(func.count())
        .select_from(Document)
        .join(Applicant, Document.applicant_id == Applicant.id)
        .where(*app_filter, Document.status == DocumentStatus.extracted)
    ) or 0
    ai_failed = await db.scalar(
        select(func.count())
        .select_from(Document)
        .join(Applicant, Document.applicant_id == Applicant.id)
        .where(*app_filter, Document.status == DocumentStatus.failed)
    ) or 0
    ai_total = ai_ok + ai_failed
    ai_rate = round((ai_ok / ai_total) * 100, 1) if ai_total else 0.0

    duplicates = await db.scalar(
        select(func.count())
        .select_from(Document)
        .join(Applicant, Document.applicant_id == Applicant.id)
        .where(*app_filter, Document.duplicate_warning.is_(True))
    ) or 0

    # Applicants with fewer than 3 filled profile fields
    incomplete = 0
    apps = (await db.execute(select(Applicant.id).where(*app_filter))).scalars().all()
    for aid in apps:
        filled = await db.scalar(
            select(func.count())
            .select_from(ProfileField)
            .where(
                ProfileField.applicant_id == aid,
                ProfileField.field_value.is_not(None),
                ProfileField.field_value != "",
            )
        )
        if (filled or 0) < 3:
            incomplete += 1

    type_rows = await db.execute(
        select(Document.document_type, func.count())
        .join(Applicant, Document.applicant_id == Applicant.id)
        .where(*app_filter, Document.document_type.is_not(None))
        .group_by(Document.document_type)
        .order_by(func.count().desc())
        .limit(10)
    )
    by_document_type = {row[0] or "other": row[1] for row in type_rows.all()}

    upload_trend = []
    for i in range(5, -1, -1):
        start = datetime.now(timezone.utc) - timedelta(days=(i + 1) * 7)
        end = datetime.now(timezone.utc) - timedelta(days=i * 7)
        c = await db.scalar(
            select(func.count())
            .select_from(Document)
            .join(Applicant, Document.applicant_id == Applicant.id)
            .where(*app_filter, Document.uploaded_at >= start, Document.uploaded_at < end)
        ) or 0
        upload_trend.append({"week": f"T-{i}", "count": c})

    top_users = []
    if is_admin(user):
        rows = await db.execute(
            select(User.email, func.count(Document.id))
            .join(Applicant, Applicant.user_id == User.id)
            .join(Document, Document.applicant_id == Applicant.id)
            .where(active)
            .group_by(User.email)
            .order_by(func.count(Document.id).desc())
            .limit(5)
        )
        top_users = [{"email": r[0], "uploads": r[1]} for r in rows.all()]

    month_start = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    ai_calls = await db.scalar(
        select(func.count()).select_from(ApiUsageLog).where(ApiUsageLog.created_at >= month_start)
    ) or 0
    ai_tokens = await db.scalar(
        select(func.coalesce(func.sum(ApiUsageLog.total_tokens), 0)).where(ApiUsageLog.created_at >= month_start)
    ) or 0

    return {
        "total_applicants": total_applicants,
        "total_documents": total_documents,
        "documents_today": docs_today,
        "new_applicants_this_week": new_week,
        "ai_success_rate": ai_rate,
        "ai_processed_documents": ai_ok,
        "duplicate_documents": duplicates,
        "profiles_incomplete": incomplete,
        "by_document_type": by_document_type,
        "upload_trend_weekly": upload_trend,
        "top_users": top_users,
        "ai_calls_this_month": ai_calls,
        "ai_tokens_this_month": int(ai_tokens),
    }
