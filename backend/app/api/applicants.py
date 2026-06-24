import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_owned_applicant, require_admin, require_staff_or_admin
from app.database import get_db
from app.models.entities import Applicant, ApplicantStatus, CaseMember, Conflict, ConflictStatus, Document, Export, PersonRole, User, UserRole
from app.schemas import (
    ApplicantCreate,
    ApplicantOut,
    ApplicantUpdate,
    CaseMemberOut,
    CaseMemberUpdate,
    DashboardStatsOut,
    FamilyMembersAppend,
    FamilyMembersUpdate,
    MessageOut,
)
from app.services.audit import log_audit
from app.services.auth import get_current_user
from app.services.merge import build_profile_response, merge_applicant_profile
from app.services.notify import notify_applicant_event
from app.services.permissions import (
    can_access_applicant,
    can_create_applicant,
    can_delete_applicant,
    is_admin,
    is_staff_or_admin,
)
from app.models.entities import CaseType
from app.services.overview_stats import build_overview_extras
from app.services.quota import check_applicant_quota, count_applicants_this_month
from app.services.applicant_purge import purge_applicant_completely
from app.services.doc_record_sync import list_doc_records
from app.services.ds260_validate import validate_ds260
from app.services.family_case import (
    append_case_members,
    case_member_out_dict,
    create_case_members,
    load_case_members,
    member_number_map,
    serialize_case_members,
    _norm_member_name,
)
from app.services.tags_util import dump_tags, parse_tags

router = APIRouter(prefix="/applicants", tags=["applicants"])

TRASH_RETENTION_DAYS = 30


def _members_out(members: list[CaseMember]) -> list[CaseMemberOut]:
    return [CaseMemberOut(**row) for row in serialize_case_members(members)]


async def _applicant_out(db: AsyncSession, applicant: Applicant) -> ApplicantOut:
    doc_count = await db.scalar(
        select(func.count()).select_from(Document).where(Document.applicant_id == applicant.id)
    )
    conflict_count = await db.scalar(
        select(func.count())
        .select_from(Conflict)
        .where(Conflict.applicant_id == applicant.id, Conflict.status == ConflictStatus.open)
    )
    staff_email = None
    if applicant.assigned_staff_id:
        staff = await db.get(User, applicant.assigned_staff_id)
        staff_email = staff.email if staff else None
    member_count = await db.scalar(
        select(func.count()).select_from(CaseMember).where(CaseMember.applicant_id == applicant.id)
    )
    return ApplicantOut(
        id=applicant.id,
        display_name=applicant.display_name,
        status=applicant.status,
        notes=applicant.notes,
        client_name=applicant.client_name,
        project_name=applicant.project_name,
        department=applicant.department,
        case_type=applicant.case_type or CaseType.immigration.value,
        tags=parse_tags(applicant.tags),
        created_at=applicant.created_at,
        updated_at=applicant.updated_at,
        document_count=doc_count or 0,
        open_conflicts=conflict_count or 0,
        assigned_staff_id=applicant.assigned_staff_id,
        assigned_staff_email=staff_email,
        deleted_at=applicant.deleted_at,
        is_family_bundle=bool(applicant.is_family_bundle),
        member_count=member_count or 0,
    )


def _active_filter(q, user: User):
    q = q.where(Applicant.deleted_at.is_(None))
    if not is_admin(user):
        q = q.where(Applicant.user_id == user.id)
    return q


async def _weekly_trend(db: AsyncSession, user_id: uuid.UUID | None = None) -> list[dict]:
    trend = []
    for i in range(5, -1, -1):
        start = datetime.now(timezone.utc) - timedelta(days=(i + 1) * 7)
        end = datetime.now(timezone.utc) - timedelta(days=i * 7)
        q = select(func.count()).select_from(Applicant).where(
            Applicant.created_at >= start,
            Applicant.created_at < end,
            Applicant.deleted_at.is_(None),
        )
        if user_id:
            q = q.where(Applicant.user_id == user_id)
        count = await db.scalar(q) or 0
        trend.append({"week": f"T-{i}", "count": count})
    return trend


async def _user_stats(db: AsyncSession, user: User) -> DashboardStatsOut:
    uid = user.id
    base = Applicant.user_id == uid
    active = Applicant.deleted_at.is_(None)
    total_applicants = await db.scalar(select(func.count()).select_from(Applicant).where(base, active)) or 0
    total_documents = await db.scalar(
        select(func.count())
        .select_from(Document)
        .join(Applicant, Document.applicant_id == Applicant.id)
        .where(base, active)
    ) or 0
    total_exports = await db.scalar(
        select(func.count())
        .select_from(Export)
        .join(Applicant, Export.applicant_id == Applicant.id)
        .where(base, active)
    ) or 0
    open_conflicts = await db.scalar(
        select(func.count())
        .select_from(Conflict)
        .join(Applicant, Conflict.applicant_id == Applicant.id)
        .where(base, active, Conflict.status == ConflictStatus.open)
    ) or 0
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    applicants_this_week = await db.scalar(
        select(func.count()).select_from(Applicant).where(base, active, Applicant.created_at >= week_ago)
    ) or 0
    status_rows = await db.execute(
        select(Applicant.status, func.count())
        .select_from(Applicant)
        .where(base, active)
        .group_by(Applicant.status)
    )
    by_status = {row[0].value: row[1] for row in status_rows.all()}
    quota_used = await count_applicants_this_month(db, uid)
    overview = await build_overview_extras(db, user_id=uid)
    return DashboardStatsOut(
        total_applicants=total_applicants,
        total_documents=total_documents,
        total_exports=total_exports,
        open_conflicts=open_conflicts,
        applicants_this_week=applicants_this_week,
        by_status=by_status,
        trend_weekly=await _weekly_trend(db, uid),
        quota_used=quota_used,
        quota_limit=user.max_applicants_per_month or 50,
        pending_count=overview["pending_count"],
        completed_count=overview["completed_count"],
        overdue_count=overview["overdue_count"],
        by_case_type=overview["by_case_type"],
        processing_trend=overview["processing_trend"],
        monthly_growth_pct=overview["monthly_growth_pct"],
    )


@router.get("/stats", response_model=DashboardStatsOut)
async def my_stats(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    return await _user_stats(db, user)


@router.get("/trash", response_model=list[ApplicantOut])
async def list_trash(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    cutoff = datetime.now(timezone.utc) - timedelta(days=TRASH_RETENTION_DAYS)
    q = (
        select(Applicant)
        .where(Applicant.deleted_at.is_not(None), Applicant.deleted_at >= cutoff)
        .order_by(Applicant.deleted_at.desc())
    )
    if not is_admin(user):
        q = q.where(Applicant.user_id == user.id)
    result = await db.execute(q)
    return [await _applicant_out(db, a) for a in result.scalars().all()]


@router.get("", response_model=list[ApplicantOut])
async def list_applicants(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    status_filter: ApplicantStatus | None = Query(None, alias="status"),
    search: str | None = Query(None, min_length=1),
):
    q = select(Applicant).order_by(Applicant.created_at.desc())
    q = _active_filter(q, user)
    if status_filter:
        q = q.where(Applicant.status == status_filter)
    if search:
        q = q.where(Applicant.display_name.ilike(f"%{search}%"))
    result = await db.execute(q)
    return [await _applicant_out(db, a) for a in result.scalars().all()]


@router.post("", response_model=ApplicantOut, status_code=status.HTTP_201_CREATED)
async def create_applicant(
    body: ApplicantCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    if not can_create_applicant(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bạn không có quyền tạo hồ sơ.")
    await check_applicant_quota(db, user)
    applicant = Applicant(
        user_id=user.id,
        display_name=body.display_name,
        notes=body.notes,
        client_name=body.client_name,
        project_name=body.project_name,
        department=body.department,
        case_type=body.case_type.value,
        tags=dump_tags(body.tags),
        is_family_bundle=bool(body.is_family_bundle),
    )
    db.add(applicant)
    await db.flush()
    if body.is_family_bundle and body.members:
        await create_case_members(
            db,
            applicant.id,
            [{"role": m.role, "display_name": m.display_name} for m in body.members],
        )
    elif body.is_family_bundle:
        await create_case_members(
            db,
            applicant.id,
            [{"role": "principal", "display_name": body.display_name}],
        )
    await log_audit(db, user=user, action="applicant.create", entity_type="applicant", entity_id=applicant.id, payload={"name": body.display_name, "family": body.is_family_bundle})
    await db.commit()
    await db.refresh(applicant)
    return await _applicant_out(db, applicant)


@router.get("/{applicant_id}/members", response_model=list[CaseMemberOut])
async def list_case_members(
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    members = await load_case_members(db, applicant.id)
    return _members_out(members)


@router.put("/{applicant_id}/members", response_model=list[CaseMemberOut])
async def set_case_members(
    body: FamilyMembersUpdate,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Thiết lập thành viên gia đình (chủ hồ sơ, vợ/chồng, con) để xuất DS-260 riêng từng người."""
    existing = await load_case_members(db, applicant.id)
    if existing:
        for row in existing:
            await db.delete(row)
        await db.flush()

    members_payload = [{"role": m.role, "display_name": m.display_name} for m in body.members]
    if not any(m["role"] == "principal" for m in members_payload):
        members_payload.insert(0, {"role": "principal", "display_name": applicant.display_name})

    created = await create_case_members(db, applicant.id, members_payload)
    applicant.is_family_bundle = True
    await log_audit(
        db,
        user=user,
        action="applicant.members.set",
        entity_type="applicant",
        entity_id=applicant.id,
        payload={"member_count": len(created)},
    )
    await db.commit()
    return _members_out(created)


@router.post("/{applicant_id}/members", response_model=list[CaseMemberOut])
async def add_case_members(
    body: FamilyMembersAppend,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Bổ sung vợ hoặc con vào hồ sơ gia đình đã có — không thay đổi thành viên hiện tại."""
    existing = await load_case_members(db, applicant.id)
    if not existing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Hồ sơ chưa có thành viên. Dùng thiết lập lần đầu trên trang Review.",
        )

    for m in body.members:
        if m.role == "principal":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Không thể thêm chủ hồ sơ mới. Chỉ bổ sung vợ hoặc con.",
            )

    added = await append_case_members(
        db,
        applicant.id,
        [{"role": m.role, "display_name": m.display_name} for m in body.members],
    )
    if not added:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không có thành viên mới (trùng tên hoặc đã có phối ngẫu).",
        )

    applicant.is_family_bundle = True
    await log_audit(
        db,
        user=user,
        action="applicant.members.append",
        entity_type="applicant",
        entity_id=applicant.id,
        payload={"added": [m.display_name for m in added], "total": len(existing) + len(added)},
    )
    await db.commit()
    return _members_out(await load_case_members(db, applicant.id))


@router.patch("/{applicant_id}/members/{member_id}", response_model=CaseMemberOut)
async def update_case_member(
    member_id: uuid.UUID,
    body: CaseMemberUpdate,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Sửa tên thành viên (chủ hồ sơ, phối ngẫu, con) — khớp lại với tên trên giấy tờ upload."""
    result = await db.execute(
        select(CaseMember).where(
            CaseMember.id == member_id,
            CaseMember.applicant_id == applicant.id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thành viên không tồn tại")

    new_name = body.display_name.strip()
    if not new_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Tên không được để trống")

    norm_new = _norm_member_name(new_name)
    others = await load_case_members(db, applicant.id)
    for other in others:
        if other.id != member_id and _norm_member_name(other.display_name) == norm_new:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Trùng tên với thành viên khác: {other.display_name}",
            )

    old_name = member.display_name
    member.display_name = new_name
    if member.role == PersonRole.principal.value:
        applicant.display_name = new_name

    await log_audit(
        db,
        user=user,
        action="applicant.member.update",
        entity_type="case_member",
        entity_id=member.id,
        payload={"old_name": old_name, "new_name": new_name, "role": member.role},
    )
    await db.commit()
    await db.refresh(member)
    numbers = member_number_map(await load_case_members(db, applicant.id))
    return CaseMemberOut(**case_member_out_dict(member, numbers[member.id]))


@router.delete("/{applicant_id}/members/{member_id}", response_model=MessageOut)
async def delete_case_member(
    member_id: uuid.UUID,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Xóa thành viên khỏi hồ sơ gia đình (không xóa chủ hồ sơ)."""
    result = await db.execute(
        select(CaseMember).where(
            CaseMember.id == member_id,
            CaseMember.applicant_id == applicant.id,
        )
    )
    member = result.scalar_one_or_none()
    if not member:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Thành viên không tồn tại")
    if member.role == PersonRole.principal.value:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Không thể xóa chủ hồ sơ. Chỉnh sửa tên nếu sai.",
        )

    name = member.display_name
    await db.delete(member)
    await log_audit(
        db,
        user=user,
        action="applicant.member.delete",
        entity_type="case_member",
        entity_id=member_id,
        payload={"display_name": name, "role": member.role},
    )
    await db.commit()
    return MessageOut(message=f"Đã xóa thành viên {name}")


@router.get("/{applicant_id}", response_model=ApplicantOut)
async def get_applicant(applicant: Annotated[Applicant, Depends(get_owned_applicant)], db: Annotated[AsyncSession, Depends(get_db)]):
    return await _applicant_out(db, applicant)


@router.patch("/{applicant_id}", response_model=ApplicantOut)
async def update_applicant(
    body: ApplicantUpdate,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    if body.display_name is not None:
        applicant.display_name = body.display_name
    if body.notes is not None:
        applicant.notes = body.notes
    if body.client_name is not None:
        applicant.client_name = body.client_name
    if body.project_name is not None:
        applicant.project_name = body.project_name
    if body.department is not None:
        applicant.department = body.department
    if body.case_type is not None:
        applicant.case_type = body.case_type.value
    if body.tags is not None:
        applicant.tags = dump_tags(body.tags)
    if body.assigned_staff_id is not None and is_staff_or_admin(user):
        staff = await db.get(User, body.assigned_staff_id)
        if not staff or staff.role not in {UserRole.staff, UserRole.admin}:
            raise HTTPException(status_code=400, detail="Staff không hợp lệ")
        applicant.assigned_staff_id = body.assigned_staff_id
    await log_audit(db, user=user, action="applicant.update", entity_type="applicant", entity_id=applicant.id)
    await db.commit()
    await db.refresh(applicant)
    return await _applicant_out(db, applicant)


@router.delete("/{applicant_id}", response_model=MessageOut)
async def delete_applicant(
    applicant_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    force: bool = Query(False),
    permanent: bool = Query(False),
):
    result = await db.execute(select(Applicant).where(Applicant.id == applicant_id))
    applicant = result.scalar_one_or_none()
    if not applicant or not can_access_applicant(user, applicant):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Applicant not found")

    if permanent:
        if not can_delete_applicant(user, applicant, permanent=True):
            raise HTTPException(status_code=403, detail="Không có quyền xóa vĩnh viễn hồ sơ này")
        if is_admin(user) and applicant.deleted_at is None and not force:
            raise HTTPException(
                status_code=400,
                detail="Hồ sơ chưa trong thùng rác — chuyển vào thùng rác trước hoặc dùng ?force=true",
            )

        stats = await purge_applicant_completely(db, applicant.id)
        await log_audit(
            db,
            user=user,
            action="applicant.purge",
            entity_type="applicant",
            entity_id=applicant.id,
            payload=stats,
        )
        await db.commit()
        return MessageOut(
            message=(
                "Đã xóa vĩnh viễn hồ sơ và toàn bộ dữ liệu liên quan "
                f"({stats.get('documents', 0)} giấy tờ, {stats.get('doc_records', 0)} bản ghi OCR, "
                f"{stats.get('exports', 0)} file xuất)."
            )
        )

    if applicant.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Hồ sơ đã trong thùng rác — dùng Khôi phục hoặc Xóa vĩnh viễn")

    admin_force = force and is_admin(user)
    if not can_delete_applicant(user, applicant, force=admin_force, permanent=False):
        raise HTTPException(status_code=403, detail="Không có quyền xóa hồ sơ này")

    applicant.deleted_at = datetime.now(timezone.utc)
    await log_audit(db, user=user, action="applicant.soft_delete", entity_type="applicant", entity_id=applicant.id)
    await db.commit()
    return MessageOut(message="Đã chuyển hồ sơ vào thùng rác (30 ngày)")


@router.post("/{applicant_id}/restore", response_model=ApplicantOut)
async def restore_applicant(
    applicant_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(select(Applicant).where(Applicant.id == applicant_id))
    applicant = result.scalar_one_or_none()
    if not applicant or applicant.deleted_at is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy trong thùng rác")
    if not is_admin(user) and applicant.user_id != user.id:
        raise HTTPException(status_code=403, detail="Không có quyền")
    applicant.deleted_at = None
    await log_audit(db, user=user, action="applicant.restore", entity_type="applicant", entity_id=applicant.id)
    await db.commit()
    await db.refresh(applicant)
    return await _applicant_out(db, applicant)


@router.post("/{applicant_id}/merge", response_model=MessageOut)
async def trigger_merge(
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    await merge_applicant_profile(db, applicant.id)
    open_count = await db.scalar(
        select(func.count())
        .select_from(Conflict)
        .where(Conflict.applicant_id == applicant.id, Conflict.status == ConflictStatus.open)
    )
    owner = await db.get(User, applicant.user_id)
    if owner and open_count and open_count > 0:
        await notify_applicant_event(db, owner=owner, applicant_name=applicant.display_name, applicant_id=applicant.id, event="conflict")
    await db.commit()
    return MessageOut(message="Profile merged from OCR (opt-in). Use tables API for per-file data.")


@router.get("/{applicant_id}/profile")
async def get_profile(
    applicant_id: uuid.UUID,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    """Profile thủ công / sau merge — không tự merge từ OCR."""
    result = await db.execute(
        select(Applicant)
        .where(Applicant.id == applicant_id)
        .options(
            selectinload(Applicant.profile_fields),
            selectinload(Applicant.conflicts),
            selectinload(Applicant.documents),
        )
    )
    app = result.scalar_one()
    return build_profile_response(app, list(app.conflicts), list(app.profile_fields))


@router.post("/{applicant_id}/review/approve", response_model=MessageOut)
async def approve_review(
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    open_count = await db.scalar(
        select(func.count())
        .select_from(Conflict)
        .where(Conflict.applicant_id == applicant.id, Conflict.status == ConflictStatus.open)
    )
    if open_count and open_count > 0:
        raise HTTPException(status_code=400, detail="Resolve all conflicts before approving")

    records = await list_doc_records(db, applicant.id)
    doc_ids = [r.source_document_id for r in records if r.source_document_id]
    names: dict[str, str] = {}
    if doc_ids:
        doc_result = await db.execute(select(Document).where(Document.id.in_(doc_ids)))
        names = {str(doc.id): doc.original_filename or "" for doc in doc_result.scalars().all()}

    validation = await validate_ds260(db, applicant.id, filename_map=names)
    if not validation["valid"]:
        first = validation["errors"][0]["message"] if validation["errors"] else "DS260 validation failed"
        raise HTTPException(
            status_code=400,
            detail=f"DS260 chưa hợp lệ ({validation['error_count']} lỗi): {first}",
        )

    applicant.status = ApplicantStatus.ready_for_export
    owner = await db.get(User, applicant.user_id)
    if owner:
        await notify_applicant_event(db, owner=owner, applicant_name=applicant.display_name, applicant_id=applicant.id, event="ready")
    await db.commit()
    msg = "DS260 validated — approved for export"
    if validation.get("warning_count"):
        msg += f" ({validation['warning_count']} cảnh báo)"
    return MessageOut(message=msg)
