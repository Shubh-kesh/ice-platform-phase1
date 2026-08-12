import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role, get_current_user
from app.core.database import get_db
from app.core.security import hash_password
from app.middleware.audit import record_audit
from app.models.user import User, UserRole
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.services.auth_tokens import revoke_user_sessions

router = APIRouter(prefix="/users", tags=["users"])

# Only the Admin manages accounts — every other role is provisioned by them.
admin_only = require_role(UserRole.ADMIN)


@router.get("", response_model=list[UserRead])
async def list_users(
    db: Annotated[AsyncSession, Depends(get_db)],
    _: Annotated[User, Depends(admin_only)],
):
    result = await db.execute(select(User).order_by(User.created_at.desc()))
    return result.scalars().all()


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    existing = await db.execute(select(User).where(User.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="A user with this email already exists")

    user = User(
        email=payload.email,
        full_name=payload.full_name,
        phone=payload.phone,
        role=payload.role,
        hashed_password=hash_password(payload.password),
    )
    db.add(user)
    await db.flush()  # Get user.id before recording audit

    # Record audit trail
    await record_audit(
        db,
        user_id=admin.id,
        action="create",
        table_name="users",
        record_id=str(user.id),
        changes={"email": {"old": None, "new": user.email}},
    )

    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    admin: Annotated[User, Depends(admin_only)],
):
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")

    # Track changes for audit log
    changes = {}
    for field, value in payload.model_dump(exclude_unset=True).items():
        old_value = getattr(user, field, None)
        if old_value != value:
            changes[field] = {"old": old_value, "new": value}
        setattr(user, field, value)

    # M9 deactivated-user cutoff: flipping is_active True -> False revokes every
    # outstanding refresh session so the account can't keep refreshing, and a
    # later reactivation requires a fresh login. Same transaction as the update.
    deactivation = changes.get("is_active") == {"old": True, "new": False}
    if deactivation:
        await revoke_user_sessions(db, user.id, "user_deactivated")

    await db.flush()

    # Record audit trail if changes were made
    if changes:
        await record_audit(
            db,
            user_id=admin.id,
            action="update",
            table_name="users",
            record_id=str(user.id),
            changes=changes,
        )

    await db.commit()
    await db.refresh(user)
    return user
