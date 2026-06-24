import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.entities import Notification, User
from app.schemas import MessageOut, NotificationOut
from app.services.auth import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationOut])
async def list_notifications(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    unread_only: bool = False,
):
    q = select(Notification).where(Notification.user_id == user.id).order_by(Notification.created_at.desc()).limit(50)
    if unread_only:
        q = q.where(Notification.is_read.is_(False))
    result = await db.execute(q)
    return result.scalars().all()


@router.get("/unread-count")
async def unread_count(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    count = await db.scalar(
        select(func.count()).select_from(Notification).where(
            Notification.user_id == user.id, Notification.is_read.is_(False)
        )
    )
    return {"count": count or 0}


@router.post("/{notification_id}/read", response_model=MessageOut)
async def mark_read(
    notification_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    note = await db.get(Notification, notification_id)
    if not note or note.user_id != user.id:
        raise HTTPException(status_code=404, detail="Not found")
    note.is_read = True
    await db.commit()
    return MessageOut(message="OK")


@router.post("/read-all", response_model=MessageOut)
async def mark_all_read(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    result = await db.execute(select(Notification).where(Notification.user_id == user.id, Notification.is_read.is_(False)))
    for note in result.scalars().all():
        note.is_read = True
    await db.commit()
    return MessageOut(message="All marked read")
