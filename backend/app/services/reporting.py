import io
import csv
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.entities import Applicant, User


async def applicants_csv(db: AsyncSession, applicants: list[Applicant]) -> bytes:
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(
        [
            "id",
            "display_name",
            "status",
            "owner_email",
            "assigned_staff_email",
            "document_count",
            "open_conflicts",
            "created_at",
            "updated_at",
            "deleted_at",
        ]
    )
    for a in applicants:
        owner_email = a.user.email if a.user else ""
        staff_email = a.assigned_staff.email if a.assigned_staff else ""
        doc_count = len(a.documents) if a.documents else 0
        writer.writerow(
            [
                str(a.id),
                a.display_name,
                a.status.value,
                owner_email,
                staff_email,
                doc_count,
                "",
                a.created_at.isoformat() if a.created_at else "",
                a.updated_at.isoformat() if a.updated_at else "",
                a.deleted_at.isoformat() if a.deleted_at else "",
            ]
        )
    return buf.getvalue().encode("utf-8-sig")


async def load_applicants_for_export(db: AsyncSession, include_deleted: bool = False) -> list[Applicant]:
    q = select(Applicant).options(
        selectinload(Applicant.user),
        selectinload(Applicant.assigned_staff),
        selectinload(Applicant.documents),
    )
    if not include_deleted:
        q = q.where(Applicant.deleted_at.is_(None))
    q = q.order_by(Applicant.created_at.desc())
    result = await db.execute(q)
    return list(result.scalars().all())
