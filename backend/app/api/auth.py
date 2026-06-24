from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.entities import User
from app.schemas import TokenResponse, UserOut, UserRegister
from app.services.auth import create_access_token, get_current_user, get_user_by_email, hash_password, verify_password
from app.services.totp import verify_totp

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def register(body: UserRegister, db: Annotated[AsyncSession, Depends(get_db)]):
    existing = await get_user_by_email(db, body.email)
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")
    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        full_name=body.full_name,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.post("/login", response_model=TokenResponse)
async def login(
    form: Annotated[OAuth2PasswordRequestForm, Depends()],
    db: Annotated[AsyncSession, Depends(get_db)],
):
    user = await get_user_by_email(db, form.username)
    password = form.password
    totp_code: str | None = None
    if user and user.totp_enabled:
        if "|" not in form.password:
            raise HTTPException(status_code=401, detail="2FA required. Login: password|123456")
        password, totp_code = form.password.rsplit("|", 1)
    if not user or not verify_password(password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account deactivated")
    if user.totp_enabled and not verify_totp(user.totp_secret or "", totp_code or ""):
        raise HTTPException(status_code=401, detail="Invalid 2FA code")
    token = create_access_token(str(user.id))
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UserOut)
async def me(user: Annotated[User, Depends(get_current_user)]):
    return user
