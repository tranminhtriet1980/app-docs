import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.entities import Applicant, User, UserRole
from app.services.auth import get_current_user
from app.services.permissions import can_access_applicant, is_staff_or_admin


async def get_owned_applicant(
    applicant_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> Applicant:
    result = await db.execute(select(Applicant).where(Applicant.id == applicant_id))
    applicant = result.scalar_one_or_none()
    if not applicant or not can_access_applicant(user, applicant):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Applicant not found")
    if applicant.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Applicant not found")
    return applicant


async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return user


async def require_staff_or_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if not is_staff_or_admin(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Staff or admin access required")
    return user
