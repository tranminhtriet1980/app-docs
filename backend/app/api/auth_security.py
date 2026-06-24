from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.entities import User
from app.schemas import MessageOut, PasswordChange, TokenResponse, TotpSetupOut, TotpVerify, UserOut
from app.services.audit import log_audit
from app.services.auth import create_access_token, get_current_user, hash_password, verify_password
from app.services.totp import generate_totp_secret, totp_provisioning_uri, verify_totp

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/change-password", response_model=MessageOut)
async def change_password(
    body: PasswordChange,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    if not verify_password(body.current_password, user.hashed_password):
        raise HTTPException(status_code=400, detail="Mật khẩu hiện tại không đúng")
    user.hashed_password = hash_password(body.new_password)
    await log_audit(db, user=user, action="auth.password_change", entity_type="user", entity_id=user.id)
    await db.commit()
    return MessageOut(message="Đã đổi mật khẩu")


@router.post("/totp/setup", response_model=TotpSetupOut)
async def setup_totp(
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    secret = generate_totp_secret()
    user.totp_secret = secret
    user.totp_enabled = False
    await db.commit()
    return TotpSetupOut(secret=secret, provisioning_uri=totp_provisioning_uri(secret, user.email))


@router.post("/totp/enable", response_model=MessageOut)
async def enable_totp(
    body: TotpVerify,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    if not user.totp_secret or not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status_code=400, detail="Mã 2FA không hợp lệ")
    user.totp_enabled = True
    await log_audit(db, user=user, action="auth.totp_enable", entity_type="user", entity_id=user.id)
    await db.commit()
    return MessageOut(message="2FA đã bật")


@router.post("/totp/disable", response_model=MessageOut)
async def disable_totp(
    body: TotpVerify,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
):
    if not user.totp_secret or not verify_totp(user.totp_secret, body.code):
        raise HTTPException(status_code=400, detail="Mã 2FA không hợp lệ")
    user.totp_enabled = False
    user.totp_secret = None
    await log_audit(db, user=user, action="auth.totp_disable", entity_type="user", entity_id=user.id)
    await db.commit()
    return MessageOut(message="2FA đã tắt")
