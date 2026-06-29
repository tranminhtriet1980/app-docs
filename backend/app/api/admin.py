import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import require_admin, require_staff_or_admin
from app.database import get_db
from app.models.entities import (
    Applicant,
    ApplicantStatus,
    AuditLog,
    Conflict,
    ConflictStatus,
    Document,
    Export,
    FormTemplate,
    User,
    UserRole,
)
from app.schemas import (
    AdminPasswordReset,
    ApplicantAdminOut,
    AuditLogOut,
    BackupInfoOut,
    DashboardStatsOut,
    FormTemplateAdminOut,
    MessageOut,
    UserAdminCreate,
    UserAdminOut,
    UserAdminUpdate,
)
from app.services.audit import log_audit
from app.services.auth import get_user_by_email, hash_password
from app.services.export import delete_form_template
from app.services.overview_stats import build_overview_extras, build_period_responsible_stats
from app.services.backup import create_sqlite_backup, list_backups, restore_sqlite_backup
from app.services.reporting import applicants_csv, load_applicants_for_export

router = APIRouter(prefix="/admin", tags=["admin"])


async def _applicant_admin_out(db: AsyncSession, applicant: Applicant) -> ApplicantAdminOut:
    doc_count = await db.scalar(
        select(func.count()).select_from(Document).where(Document.applicant_id == applicant.id)
    )
    conflict_count = await db.scalar(
        select(func.count())
        .select_from(Conflict)
        .where(Conflict.applicant_id == applicant.id, Conflict.status == ConflictStatus.open)
    )
    export_count = await db.scalar(
        select(func.count()).select_from(Export).where(Export.applicant_id == applicant.id)
    )
    owner_email = applicant.user.email if applicant.user else None
    return ApplicantAdminOut(
        id=applicant.id,
        display_name=applicant.display_name,
        status=applicant.status,
        notes=applicant.notes,
        created_at=applicant.created_at,
        updated_at=applicant.updated_at,
        document_count=doc_count or 0,
        open_conflicts=conflict_count or 0,
        export_count=export_count or 0,
        owner_id=applicant.user_id,
        owner_email=owner_email,
    )


@router.get("/stats", response_model=DashboardStatsOut)
async def dashboard_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_staff_or_admin)],
    scope: str = Query("all", pattern="^(all|mine)$"),
):
    """Aggregate stats for dashboard. Admin sees all; others limited to own data."""
    applicant_filter = []
    if scope == "mine" or user.role != UserRole.admin:
        applicant_filter.append(Applicant.user_id == user.id)

    def _apply(q):
        for f in applicant_filter:
            q = q.where(f)
        return q.where(Applicant.deleted_at.is_(None))

    total_applicants = await db.scalar(_apply(select(func.count()).select_from(Applicant))) or 0
    total_documents = await db.scalar(
        _apply(
            select(func.count())
            .select_from(Document)
            .join(Applicant, Document.applicant_id == Applicant.id)
        )
    ) or 0
    total_exports = await db.scalar(
        _apply(
            select(func.count())
            .select_from(Export)
            .join(Applicant, Export.applicant_id == Applicant.id)
        )
    ) or 0
    open_conflicts = await db.scalar(
        _apply(
            select(func.count())
            .select_from(Conflict)
            .join(Applicant, Conflict.applicant_id == Applicant.id)
            .where(Conflict.status == ConflictStatus.open)
        )
    ) or 0

    status_rows = await db.execute(
        _apply(
            select(Applicant.status, func.count())
            .select_from(Applicant)
            .group_by(Applicant.status)
        )
    )
    by_status = {row[0].value: row[1] for row in status_rows.all()}

    total_users = None
    if user.role == UserRole.admin:
        total_users = await db.scalar(select(func.count()).select_from(User)) or 0

    trend = []
    for i in range(5, -1, -1):
        start = datetime.now(timezone.utc) - timedelta(days=(i + 1) * 7)
        end = datetime.now(timezone.utc) - timedelta(days=i * 7)
        count = await db.scalar(
            _apply(
                select(func.count())
                .select_from(Applicant)
                .where(Applicant.created_at >= start, Applicant.created_at < end)
            )
        ) or 0
        trend.append({"week": f"T-{i}", "count": count})

    overview_uid = user.id if scope == "mine" else None
    overview = await build_overview_extras(db, user_id=overview_uid)
    periods = await build_period_responsible_stats(db, user_id=overview_uid)

    return DashboardStatsOut(
        total_applicants=total_applicants,
        total_documents=total_documents,
        total_exports=total_exports,
        open_conflicts=open_conflicts,
        applicants_this_week=periods["applicants_this_week"],
        applicants_this_month=periods["applicants_this_month"],
        applicants_this_year=periods["applicants_this_year"],
        by_responsible=periods["by_responsible"],
        by_status=by_status,
        total_users=total_users,
        trend_weekly=trend,
        pending_count=overview["pending_count"],
        completed_count=overview["completed_count"],
        overdue_count=overview["overdue_count"],
        by_case_type=overview["by_case_type"],
        processing_trend=overview["processing_trend"],
        monthly_growth_pct=overview["monthly_growth_pct"],
    )


@router.get("/applicants", response_model=list[ApplicantAdminOut])
async def list_all_applicants(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
    status_filter: ApplicantStatus | None = Query(None, alias="status"),
    search: str | None = Query(None, min_length=1),
    owner_id: uuid.UUID | None = None,
    case_type: str | None = Query(None),
    year: int | None = Query(None, ge=2000, le=2100),
):
    q = (
        select(Applicant)
        .options(selectinload(Applicant.user))
        .where(Applicant.deleted_at.is_(None))
        .order_by(Applicant.created_at.desc())
    )
    if owner_id:
        q = q.where(Applicant.user_id == owner_id)
    if status_filter:
        q = q.where(Applicant.status == status_filter)
    if case_type:
        q = q.where(Applicant.case_type == case_type)
    if year:
        start = datetime(year, 1, 1, tzinfo=timezone.utc)
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        q = q.where(Applicant.created_at >= start, Applicant.created_at < end)
    if search:
        q = q.where(Applicant.display_name.ilike(f"%{search}%"))
    result = await db.execute(q)
    applicants = result.scalars().all()
    return [await _applicant_admin_out(db, a) for a in applicants]


@router.get("/users", response_model=list[UserAdminOut])
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    users = result.scalars().all()
    out: list[UserAdminOut] = []
    for u in users:
        count = await db.scalar(select(func.count()).select_from(Applicant).where(Applicant.user_id == u.id)) or 0
        out.append(
            UserAdminOut(
                id=u.id,
                email=u.email,
                full_name=u.full_name,
                role=u.role,
                is_active=u.is_active,
                can_create_applicants=u.can_create_applicants,
                max_applicants_per_month=u.max_applicants_per_month or 50,
                totp_enabled=u.totp_enabled,
                created_at=u.created_at,
                applicant_count=count,
            )
        )
    return out


@router.post("/users", response_model=UserAdminOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserAdminCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(require_admin)],
):
    existing = await get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email đã được sử dụng")

    user = User(
        email=body.email.strip().lower(),
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
        role=body.role,
        is_active=body.is_active,
        can_create_applicants=body.can_create_applicants,
        max_applicants_per_month=body.max_applicants_per_month,
    )
    db.add(user)
    await log_audit(
        db,
        user=current,
        action="user.create",
        entity_type="user",
        entity_id=user.id,
        payload={"email": user.email, "role": user.role.value},
    )
    await db.commit()
    await db.refresh(user)
    return UserAdminOut(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        role=user.role,
        is_active=user.is_active,
        can_create_applicants=user.can_create_applicants,
        max_applicants_per_month=user.max_applicants_per_month or 50,
        totp_enabled=user.totp_enabled,
        created_at=user.created_at,
        applicant_count=0,
    )


@router.patch("/users/{user_id}", response_model=UserAdminOut)
async def update_user(
    user_id: uuid.UUID,
    body: UserAdminUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(require_admin)],
):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if target.id == current.id and body.is_active is False:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate yourself")

    if body.full_name is not None:
        target.full_name = body.full_name
    if body.role is not None:
        if target.id == current.id and body.role != UserRole.admin:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot demote yourself")
        target.role = body.role
    if body.is_active is not None:
        target.is_active = body.is_active
    if body.can_create_applicants is not None:
        target.can_create_applicants = body.can_create_applicants
    if body.max_applicants_per_month is not None:
        target.max_applicants_per_month = body.max_applicants_per_month

    await log_audit(db, user=current, action="user.update", entity_type="user", entity_id=target.id)
    await db.commit()
    await db.refresh(target)
    count = await db.scalar(select(func.count()).select_from(Applicant).where(Applicant.user_id == target.id)) or 0
    return UserAdminOut(
        id=target.id,
        email=target.email,
        full_name=target.full_name,
        role=target.role,
        is_active=target.is_active,
        can_create_applicants=target.can_create_applicants,
        max_applicants_per_month=target.max_applicants_per_month or 50,
        totp_enabled=target.totp_enabled,
        created_at=target.created_at,
        applicant_count=count,
    )


@router.post("/users/{user_id}/reset-password", response_model=MessageOut)
async def reset_user_password(
    user_id: uuid.UUID,
    body: AdminPasswordReset,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(require_admin)],
):
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    target.hashed_password = hash_password(body.new_password)
    await log_audit(
        db,
        user=current,
        action="user.password_reset",
        entity_type="user",
        entity_id=target.id,
        payload={"email": target.email},
    )
    await db.commit()
    return MessageOut(message=f"Đã đổi mật khẩu cho {target.email}")


@router.delete("/users/{user_id}", response_model=MessageOut)
async def deactivate_user(
    user_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    current: Annotated[User, Depends(require_admin)],
):
    if user_id == current.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot deactivate yourself")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    target.is_active = False
    await log_audit(db, user=current, action="user.deactivate", entity_type="user", entity_id=target.id)
    await db.commit()
    return MessageOut(message="User deactivated")


@router.get("/audit-logs", response_model=list[AuditLogOut])
async def list_audit_logs(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
    limit: int = Query(100, le=500),
):
    result = await db.execute(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(limit))
    logs = result.scalars().all()
    out = []
    for log in logs:
        email = None
        if log.user_id:
            u = await db.get(User, log.user_id)
            email = u.email if u else None
        out.append(
            AuditLogOut(
                id=log.id,
                user_id=log.user_id,
                user_email=email,
                action=log.action,
                entity_type=log.entity_type,
                entity_id=log.entity_id,
                payload=log.payload,
                created_at=log.created_at,
            )
        )
    return out


@router.get("/export/csv")
async def export_applicants_csv(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_staff_or_admin)],
    include_deleted: bool = False,
):
    from fastapi.responses import Response

    applicants = await load_applicants_for_export(db, include_deleted=include_deleted)
    data = await applicants_csv(db, applicants)
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=applicants_report.csv"},
    )


@router.get("/backups", response_model=list[BackupInfoOut])
async def list_db_backups(_: Annotated[User, Depends(require_admin)]):
    return [BackupInfoOut(**b) for b in list_backups()]


@router.post("/backups", response_model=MessageOut)
async def create_db_backup(
    user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    info = create_sqlite_backup()
    await log_audit(db, user=user, action="backup.create", entity_type="backup", entity_id=info["filename"])
    await db.commit()
    return MessageOut(message=f"Backup created: {info['filename']}", detail=info)


@router.post("/backups/restore", response_model=MessageOut)
async def restore_db_backup(
    user: Annotated[User, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    filename: str = Query(...),
):
    info = restore_sqlite_backup(filename)
    await log_audit(db, user=user, action="backup.restore", entity_type="backup", entity_id=filename)
    await db.commit()
    return MessageOut(message="Database restored. Restart backend.", detail=info)


@router.get("/form-templates", response_model=list[FormTemplateAdminOut])
async def list_all_templates(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(require_admin)],
):
    result = await db.execute(select(FormTemplate).order_by(FormTemplate.name))
    return result.scalars().all()


@router.patch("/form-templates/{template_id}", response_model=FormTemplateAdminOut)
async def toggle_template(
    template_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_admin)],
    is_active: bool = Query(...),
):
    tpl = await db.get(FormTemplate, template_id)
    if not tpl:
        raise HTTPException(status_code=404, detail="Template not found")
    tpl.is_active = is_active
    await log_audit(db, user=user, action="template.toggle", entity_type="template", entity_id=tpl.id, payload={"active": is_active})
    await db.commit()
    await db.refresh(tpl)
    return tpl


@router.delete("/form-templates/{template_id}", response_model=MessageOut)
async def delete_template(
    template_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_admin)],
):
    tpl = await delete_form_template(db, template_id)
    await log_audit(db, user=user, action="template.delete", entity_type="template", entity_id=tpl.id, payload={"code": tpl.code})
    await db.commit()
    return MessageOut(message=f"Đã xóa mẫu form '{tpl.name}' ({tpl.code})")
