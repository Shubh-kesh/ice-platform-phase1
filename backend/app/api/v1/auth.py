from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.rate_limit import limiter, AUTH_RATE_LIMIT, REFRESH_RATE_LIMIT
from app.core.security import create_token, decode_token, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, RefreshRequest, TokenResponse
from app.schemas.user import UserRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
@limiter.limit(AUTH_RATE_LIMIT)
async def login(request: Request, payload: LoginRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    result = await db.execute(select(User).where(User.email == payload.email))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.hashed_password):
        # Deliberately identical error for "no such user" and "wrong password"
        # so login can't be used to enumerate valid emails.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
        )

    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated",
        )

    return TokenResponse(
        access_token=create_token(str(user.id), user.role.value, "access"),
        refresh_token=create_token(str(user.id), user.role.value, "refresh"),
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(REFRESH_RATE_LIMIT)
async def refresh(request: Request, payload: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    decoded = decode_token(payload.refresh_token)
    if decoded is None or decoded.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    import uuid as uuid_lib

    result = await db.execute(select(User).where(User.id == uuid_lib.UUID(decoded["sub"])))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    return TokenResponse(
        access_token=create_token(str(user.id), user.role.value, "access"),
        refresh_token=create_token(str(user.id), user.role.value, "refresh"),
    )


@router.get("/me", response_model=UserRead)
async def read_current_user(user: Annotated[User, Depends(get_current_user)]):
    return user
