from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_owned_applicant
from app.database import get_db
from app.models.entities import Applicant, User
from app.schemas import AiAssistantOut, AiAssistantRequest, AiChatOut, AiChatRequest
from app.services.ai_assistant import ask_global_assistant
from app.services.ai_chat import ask_applicant_ai
from app.services.audit import log_audit
from app.services.auth import get_current_user

router = APIRouter(tags=["ai-chat"])


@router.post("/ai/assistant", response_model=AiAssistantOut)
async def global_assistant(
    body: AiAssistantRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    """Trợ lý toàn cục: tìm hồ sơ trong dữ liệu + hỏi đáp định cư (fallback OpenAI)."""
    result = await ask_global_assistant(db, user=user, question=body.question)
    await log_audit(
        db,
        user=user,
        action="ai.assistant",
        entity_type="user",
        entity_id=user.id,
        payload={"question": body.question[:200], "source": result.get("source_type")},
    )
    await db.commit()
    return AiAssistantOut(**result)


@router.post("/applicants/{applicant_id}/ai/chat", response_model=AiChatOut)
async def chat_with_applicant(
    body: AiChatRequest,
    applicant: Annotated[Applicant, Depends(get_owned_applicant)],
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    result = await ask_applicant_ai(
        db,
        applicant_id=applicant.id,
        user_id=user.id,
        question=body.question,
    )
    await log_audit(
        db,
        user=user,
        action="ai.chat",
        entity_type="applicant",
        entity_id=applicant.id,
        payload={"question": body.question[:200]},
    )
    await db.commit()
    return AiChatOut(**result)
