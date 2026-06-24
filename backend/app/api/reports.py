from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_staff_or_admin
from app.database import get_db
from app.models.entities import User
from app.schemas import ExecutiveDashboardOut
from app.services.executive_reports import executive_dashboard

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/executive", response_model=ExecutiveDashboardOut)
async def get_executive_dashboard(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(require_staff_or_admin)],
):
    data = await executive_dashboard(db, user)
    return ExecutiveDashboardOut(**data)
