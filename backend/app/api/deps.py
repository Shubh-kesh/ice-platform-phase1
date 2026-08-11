"""
Reusable FastAPI dependencies.

get_current_user   -> decodes the bearer token, loads the user, 401s if invalid.
require_role(...)  -> a dependency factory for RBAC on top of get_current_user.

Usage on an endpoint:
    @router.get("/admin-only")
    async def handler(user: User = Depends(require_role(UserRole.ADMIN))):
        ...
"""
import uuid
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import decode_token
from app.models.user import User, UserRole
from app.services.idempotency import (
    IDEMPOTENCY_KEY_HEADER,
    IDEMPOTENCY_KEY_MAX_LENGTH,
    IDEMPOTENCY_KEY_MIN_LENGTH,
    IdempotencyGuard,
    claim_idempotency,
)

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> User:
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_token(token)
    if payload is None or payload.get("type") != "access":
        raise credentials_error

    user_id = payload.get("sub")
    if user_id is None:
        raise credentials_error

    result = await db.execute(select(User).where(User.id == uuid.UUID(user_id)))
    user = result.scalar_one_or_none()

    if user is None or not user.is_active:
        raise credentials_error

    return user


def require_role(*allowed_roles: UserRole):
    async def role_checker(
        user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role.value}' is not permitted to perform this action",
            )
        return user

    return role_checker


async def get_idempotency_guard(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    user: Annotated[User, Depends(get_current_user)],
) -> IdempotencyGuard:
    """Claim the `Idempotency-Key` header for this request (M8).

    Requests without a header get a no-op guard. Requests with one are either
    (a) the first attempt — a claim row is inserted into the handler's
        transaction and finalized with the response before its commit;
    (b) a retry — the already-committed response is returned verbatim; or
    (c) a conflicting reuse — HTTP 409.
    """
    key = (request.headers.get(IDEMPOTENCY_KEY_HEADER) or "").strip()
    if not key:
        return IdempotencyGuard(enabled=False)
    if not (IDEMPOTENCY_KEY_MIN_LENGTH <= len(key) <= IDEMPOTENCY_KEY_MAX_LENGTH):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Idempotency-Key must be "
                f"{IDEMPOTENCY_KEY_MIN_LENGTH}-{IDEMPOTENCY_KEY_MAX_LENGTH} characters"
            ),
        )
    return await claim_idempotency(request, db, user, key)
