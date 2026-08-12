from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi.util import get_remote_address
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.database import get_db
from app.core.rate_limit import limiter, AUTH_RATE_LIMIT, REFRESH_RATE_LIMIT, LOGOUT_RATE_LIMIT
from app.core.security import create_token, verify_password
from app.middleware.audit import record_audit
from app.models.user import User
from app.schemas.auth import LoginRequest, LogoutRequest, RefreshRequest, TokenResponse
from app.schemas.user import UserRead
from app.services.auth_tokens import issue_session, revoke_token, rotate_session

router = APIRouter(prefix="/auth", tags=["auth"])


def _client_ip(request: Request) -> str | None:
    """Same source as the rate-limiter key, so audited IPs match throttled IPs."""
    try:
        return get_remote_address(request)
    except Exception:
        return request.client.host if request.client else None


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

    ip = _client_ip(request)
    refresh_token, _ = await issue_session(db, user, ip)

    # Auth events are audited in the same transaction as the session write.
    await record_audit(
        db,
        user_id=user.id,
        action="login",
        table_name="auth",
        record_id=str(user.id),
        changes={},
        ip_address=ip,
    )
    await db.commit()

    return TokenResponse(
        access_token=create_token(str(user.id), user.role.value, "access"),
        refresh_token=refresh_token,
    )


@router.post("/refresh", response_model=TokenResponse)
@limiter.limit(REFRESH_RATE_LIMIT)
async def refresh(request: Request, payload: RefreshRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    ip = _client_ip(request)
    outcome = await rotate_session(db, payload.refresh_token, ip)

    if not outcome.success:
        # Security rejections (reuse/theft, deactivated account) are audited
        # before the 401 so the signal survives the transaction rollback on
        # the request's exception path.
        if outcome.event is not None and outcome.event_user_id is not None:
            await record_audit(
                db,
                user_id=outcome.event_user_id,
                action=outcome.event,
                table_name="auth",
                record_id=str(outcome.event_user_id),
                changes={},
                ip_address=ip,
            )
            await db.commit()
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token"
        )

    assert outcome.user is not None
    assert outcome.new_refresh_token is not None

    await record_audit(
        db,
        user_id=outcome.user.id,
        action="refresh",
        table_name="auth",
        record_id=str(outcome.user.id),
        changes={"event": "refresh_rotation"},
        ip_address=ip,
    )
    await db.commit()

    return TokenResponse(
        access_token=create_token(str(outcome.user.id), outcome.user.role.value, "access"),
        refresh_token=outcome.new_refresh_token,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit(LOGOUT_RATE_LIMIT)
async def logout(request: Request, payload: LogoutRequest, db: Annotated[AsyncSession, Depends(get_db)]):
    ip = _client_ip(request)
    session = await revoke_token(db, payload.refresh_token)
    if session is not None:
        await record_audit(
            db,
            user_id=session.user_id,
            action="logout",
            table_name="auth",
            record_id=str(session.user_id),
            changes={},
            ip_address=ip,
        )
        await db.commit()
    # Always 204: logout is idempotent and must not reveal whether a token was valid.


@router.get("/me", response_model=UserRead)
async def read_current_user(user: Annotated[User, Depends(get_current_user)]):
    return user
