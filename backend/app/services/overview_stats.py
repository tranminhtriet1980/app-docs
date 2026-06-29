from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import Applicant, ApplicantStatus, CaseType, User


def _active_filters(user_id=None):
    filters = [Applicant.deleted_at.is_(None)]
    if user_id:
        filters.append(Applicant.user_id == user_id)
    return filters


async def build_overview_extras(db: AsyncSession, *, user_id=None) -> dict:
    filters = _active_filters(user_id)
    now = datetime.now(timezone.utc)
    stale = now - timedelta(days=14)

    total = await db.scalar(select(func.count()).select_from(Applicant).where(*filters)) or 0

    pending = await db.scalar(
        select(func.count())
        .select_from(Applicant)
        .where(
            *filters,
            Applicant.status.in_([ApplicantStatus.draft, ApplicantStatus.processing, ApplicantStatus.review]),
        )
    ) or 0

    completed = await db.scalar(
        select(func.count())
        .select_from(Applicant)
        .where(
            *filters,
            Applicant.status.in_([ApplicantStatus.ready_for_export, ApplicantStatus.exported]),
        )
    ) or 0

    overdue = await db.scalar(
        select(func.count())
        .select_from(Applicant)
        .where(
            *filters,
            Applicant.status.in_([ApplicantStatus.processing, ApplicantStatus.review]),
            Applicant.updated_at < stale,
        )
    ) or 0

    case_rows = await db.execute(
        select(Applicant.case_type, func.count())
        .where(*filters)
        .group_by(Applicant.case_type)
    )
    by_case_type: dict[str, int] = {}
    for row in case_rows.all():
        key = row[0] or CaseType.other.value
        by_case_type[key] = int(row[1] or 0)

    processing_trend = []
    for i in range(6, -1, -1):
        start = now - timedelta(days=(i + 1))
        end = now - timedelta(days=i)
        day_label = end.strftime("%d/%m")
        base = [Applicant.created_at >= start, Applicant.created_at < end, *filters]

        done = await db.scalar(
            select(func.count())
            .select_from(Applicant)
            .where(*base, Applicant.status.in_([ApplicantStatus.ready_for_export, ApplicantStatus.exported]))
        ) or 0
        proc = await db.scalar(
            select(func.count())
            .select_from(Applicant)
            .where(
                *base,
                Applicant.status.in_([ApplicantStatus.processing, ApplicantStatus.review, ApplicantStatus.draft]),
            )
        ) or 0
        late = await db.scalar(
            select(func.count())
            .select_from(Applicant)
            .where(
                *base,
                Applicant.status.in_([ApplicantStatus.processing, ApplicantStatus.review]),
                Applicant.updated_at < stale,
            )
        ) or 0
        processing_trend.append(
            {"day": day_label, "completed": done, "processing": proc, "overdue": late}
        )

    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    prev_month_start = (month_start - timedelta(days=1)).replace(day=1)
    this_month = await db.scalar(
        select(func.count()).select_from(Applicant).where(*filters, Applicant.created_at >= month_start)
    ) or 0
    last_month = await db.scalar(
        select(func.count())
        .select_from(Applicant)
        .where(*filters, Applicant.created_at >= prev_month_start, Applicant.created_at < month_start)
    ) or 0
    growth_pct = round(((this_month - last_month) / last_month) * 100, 1) if last_month else None

    return {
        "pending_count": int(pending),
        "completed_count": int(completed),
        "overdue_count": int(overdue),
        "by_case_type": by_case_type,
        "processing_trend": processing_trend,
        "total_applicants": int(total),
        "monthly_growth_pct": growth_pct,
    }


def _period_boundaries(now: datetime) -> tuple[datetime, datetime, datetime]:
    """Mốc đầu tuần (Thứ 2), đầu tháng, đầu năm — theo lịch."""
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = midnight - timedelta(days=now.weekday())
    month_start = midnight.replace(day=1)
    year_start = midnight.replace(month=1, day=1)
    return week_start, month_start, year_start


async def build_period_responsible_stats(db: AsyncSession, *, user_id=None) -> dict:
    """
    Số bộ hồ sơ làm trong tuần này / tháng này / năm này, kèm bảng theo người phụ trách
    (người tạo hồ sơ). user_id=None → toàn bộ (view quản lý); có user_id → chỉ người đó.
    """
    filters = _active_filters(user_id)
    now = datetime.now(timezone.utc)
    week_start, month_start, year_start = _period_boundaries(now)

    async def _total(boundary: datetime) -> int:
        return await db.scalar(
            select(func.count())
            .select_from(Applicant)
            .where(*filters, Applicant.created_at >= boundary)
        ) or 0

    async def _by_user(boundary: datetime) -> dict:
        rows = await db.execute(
            select(Applicant.user_id, func.count())
            .select_from(Applicant)
            .where(*filters, Applicant.created_at >= boundary)
            .group_by(Applicant.user_id)
        )
        return {row[0]: int(row[1]) for row in rows.all()}

    this_week = await _total(week_start)
    this_month = await _total(month_start)
    this_year = await _total(year_start)

    week_by, month_by, year_by = (
        await _by_user(week_start),
        await _by_user(month_start),
        await _by_user(year_start),
    )

    ids = set(week_by) | set(month_by) | set(year_by)
    names: dict = {}
    if ids:
        urows = await db.execute(select(User).where(User.id.in_(ids)))
        for u in urows.scalars():
            names[u.id] = {"name": (u.full_name or u.email or "—"), "email": u.email or ""}

    by_responsible = [
        {
            "name": names.get(uid, {}).get("name", "—"),
            "email": names.get(uid, {}).get("email", ""),
            "week": week_by.get(uid, 0),
            "month": month_by.get(uid, 0),
            "year": year_by.get(uid, 0),
        }
        for uid in ids
    ]
    by_responsible.sort(key=lambda r: (r["year"], r["month"], r["week"]), reverse=True)

    return {
        "applicants_this_week": int(this_week),
        "applicants_this_month": int(this_month),
        "applicants_this_year": int(this_year),
        "by_responsible": by_responsible,
    }
