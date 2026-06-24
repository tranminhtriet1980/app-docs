from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.entities import User
from app.schemas import SearchResultOut
from app.services.auth import get_current_user
from app.services.search_service import search_records

router = APIRouter(prefix="/search", tags=["search"])


@router.get("", response_model=SearchResultOut)
async def global_search(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
    q: str = Query(..., min_length=2, max_length=200),
    limit: int = Query(40, le=100),
):
    data = await search_records(db, user, q=q, limit=limit)
    return SearchResultOut(**data)
