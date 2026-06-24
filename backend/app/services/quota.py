from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Applicant, User


async def count_applicants_this_month(db: AsyncSession, user_id) -> int:
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    return (
        await db.scalar(
            select(func.count())
            .select_from(Applicant)
            .where(
                Applicant.user_id == user_id,
                Applicant.created_at >= month_start,
                Applicant.deleted_at.is_(None),
            )
        )
        or 0
    )


async def check_applicant_quota(db: AsyncSession, user: User) -> None:
    limit = user.max_applicants_per_month or 50
    count = await count_applicants_this_month(db, user.id)
    if count >= limit:
        from fastapi import HTTPException, status

        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Đã đạt giới hạn {limit} hồ sơ/tháng. Liên hệ admin để tăng quota.",
        )
