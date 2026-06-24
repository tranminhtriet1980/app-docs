from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_staff_or_admin
from app.database import get_db
from app.models.entities import User
from app.schemas import ApiUsageLogOut, ApiUsageStatsOut
from app.services.api_usage_stats import recent_usage_logs, usage_by_user, usage_summary
from app.services.auth import get_current_user
from app.services.permissions import is_admin

router = APIRouter(prefix="/api-usage", tags=["api-usage"])


def _log_out(log, user_email: str | None = None) -> ApiUsageLogOut:
    return ApiUsageLogOut(
        id=log.id,
        user_id=log.user_id,
        user_email=user_email,
        applicant_id=log.applicant_id,
        document_id=log.document_id,
        operation=log.operation,
        model=log.model,
        prompt_tokens=log.prompt_tokens,
        completion_tokens=log.completion_tokens,
        total_tokens=log.total_tokens,
        filename=log.filename,
        doc_type=log.doc_type,
        success=log.success,
        error_message=log.error_message,
        created_at=log.created_at,
    )


@router.get("/stats", response_model=ApiUsageStatsOut)
async def get_usage_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    days: int = Query(30, ge=1, le=365),
):
    """Token usage summary for current user, or all users if admin."""
    uid = None if is_admin(user) else user.id
    data = await usage_summary(db, user_id=uid, days=days)
    if is_admin(user):
        data["by_user"] = await usage_by_user(db, days=days)
    return ApiUsageStatsOut(**data)


@router.get("/logs", response_model=list[ApiUsageLogOut])
async def list_usage_logs(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    limit: int = Query(50, le=200),
):
    uid = None if is_admin(user) else user.id
    logs = await recent_usage_logs(db, user_id=uid, limit=limit)
    out: list[ApiUsageLogOut] = []
    for log in logs:
        email = None
        if log.user_id:
            u = await db.get(User, log.user_id)
            email = u.email if u else None
        out.append(_log_out(log, email))
    return out


@router.get("/admin/summary", response_model=ApiUsageStatsOut)
async def admin_usage_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_staff_or_admin)],
    days: int = Query(30, ge=1, le=365),
):
    data = await usage_summary(db, user_id=None, days=days)
    data["by_user"] = await usage_by_user(db, days=days)
    return ApiUsageStatsOut(**data)
