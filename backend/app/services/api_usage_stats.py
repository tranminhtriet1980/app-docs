from datetime import datetime, timedelta, timezone

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.entities import ApiUsageLog, User
from app.services.llm_usage import estimate_cost_usd


async def usage_summary(
    db: AsyncSession,
    *,
    user_id=None,
    days: int = 30,
) -> dict:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    filters = [ApiUsageLog.created_at >= since]
    if user_id:
        filters.append(ApiUsageLog.user_id == user_id)

    totals = await db.execute(
        select(
            func.count(ApiUsageLog.id),
            func.coalesce(func.sum(ApiUsageLog.prompt_tokens), 0),
            func.coalesce(func.sum(ApiUsageLog.completion_tokens), 0),
            func.coalesce(func.sum(ApiUsageLog.total_tokens), 0),
            func.coalesce(func.sum(case((ApiUsageLog.success.is_(True), 1), else_=0)), 0),
        ).where(*filters)
    )
    calls, prompt, completion, total, success_count = totals.one()

    by_operation = await db.execute(
        select(
            ApiUsageLog.operation,
            func.count(ApiUsageLog.id),
            func.coalesce(func.sum(ApiUsageLog.total_tokens), 0),
        )
        .where(*filters)
        .group_by(ApiUsageLog.operation)
        .order_by(func.sum(ApiUsageLog.total_tokens).desc())
    )
    by_operation_list = [
        {"operation": row[0], "calls": row[1], "total_tokens": int(row[2] or 0)}
        for row in by_operation.all()
    ]

    by_model = await db.execute(
        select(
            ApiUsageLog.model,
            func.count(ApiUsageLog.id),
            func.coalesce(func.sum(ApiUsageLog.total_tokens), 0),
        )
        .where(*filters)
        .group_by(ApiUsageLog.model)
    )
    by_model_list = [
        {"model": row[0], "calls": row[1], "total_tokens": int(row[2] or 0)}
        for row in by_model.all()
    ]

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    today_filters = [ApiUsageLog.created_at >= today_start]
    if user_id:
        today_filters.append(ApiUsageLog.user_id == user_id)
    today_tokens = await db.scalar(
        select(func.coalesce(func.sum(ApiUsageLog.total_tokens), 0)).where(*today_filters)
    ) or 0

    cost_usd = estimate_cost_usd(int(prompt or 0), int(completion or 0))
    budget = settings.monthly_token_budget or None
    total_int = int(total or 0)

    return {
        "period_days": days,
        "total_calls": int(calls or 0),
        "successful_calls": int(success_count or 0),
        "failed_calls": int((calls or 0) - (success_count or 0)),
        "prompt_tokens": int(prompt or 0),
        "completion_tokens": int(completion or 0),
        "total_tokens": total_int,
        "tokens_today": int(today_tokens),
        "estimated_cost_usd": cost_usd,
        "monthly_token_budget": budget,
        "budget_used_percent": round((total_int / budget) * 100, 1) if budget else None,
        "by_operation": by_operation_list,
        "by_model": by_model_list,
        "current_model": settings.openai_model,
    }


async def usage_by_user(db: AsyncSession, days: int = 30) -> list[dict]:
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = await db.execute(
        select(
            ApiUsageLog.user_id,
            User.email,
            func.count(ApiUsageLog.id),
            func.coalesce(func.sum(ApiUsageLog.total_tokens), 0),
        )
        .outerjoin(User, User.id == ApiUsageLog.user_id)
        .where(ApiUsageLog.created_at >= since)
        .group_by(ApiUsageLog.user_id, User.email)
        .order_by(func.sum(ApiUsageLog.total_tokens).desc())
    )
    return [
        {
            "user_id": str(row[0]) if row[0] else None,
            "email": row[1] or "—",
            "calls": int(row[2] or 0),
            "total_tokens": int(row[3] or 0),
        }
        for row in rows.all()
    ]


async def recent_usage_logs(db: AsyncSession, *, user_id=None, limit: int = 50) -> list[ApiUsageLog]:
    q = select(ApiUsageLog).order_by(ApiUsageLog.created_at.desc()).limit(limit)
    if user_id:
        q = q.where(ApiUsageLog.user_id == user_id)
    result = await db.execute(q)
    return list(result.scalars().all())
