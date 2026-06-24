import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.entities import AuditLog, User


async def log_audit(
    db: AsyncSession,
    *,
    user: User | None,
    action: str,
    entity_type: str,
    entity_id: str | uuid.UUID,
    payload: dict | None = None,
) -> AuditLog:
    entry = AuditLog(
        user_id=user.id if user else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id),
        payload=json.dumps(payload, ensure_ascii=False) if payload else None,
    )
    db.add(entry)
    await db.flush()
    return entry
