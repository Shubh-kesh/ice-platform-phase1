"""
M9 — refresh-token lifecycle (issue / rotate / revoke).

Opaque refresh tokens are the single-use credentials behind the stateless JWT
access token. Each is stored only as a SHA-256 digest in `refresh_sessions`,
and every rotation is a single transaction guarded by a row lock:

    SELECT ... FOR UPDATE on the presented token's row
      - missing row      -> rejected (unknown token)
      - revoked row      -> reuse: within the grace window = benign race (reject
                             only); past the window = theft, revoke the family
      - expired          -> rejected (no family kill — staleness, not theft)
      - user deactivated -> revoke the family + reject   (cutoff, not JWT expiry)
      - otherwise        -> mark the row revoked('rotated'), insert a child row
                             in the same family, hand back a fresh token pair

The row lock is what makes rotation race-proof: two concurrent refreshes of the
same token serialize on the FOR UPDATE, so exactly one wins; the loser reads
the now-revoked row and is rejected (and, past the grace window, triggers
family revocation instead of a second success).

This module never commits — callers (the auth endpoints) add audit rows and
commit, so token state + audit land atomically.
"""
import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.refresh_session import RefreshSession
from app.models.user import User

RevokeReason = Literal[
    "logout", "rotated", "reuse_detected", "user_deactivated", "expired"
]


@dataclass
class RotateResult:
    """Outcome of a refresh attempt. `success=False` paths carry an optional
    audit `event` (and the affected `event_user_id`) for security rejections
    that must be recorded before the caller returns its 401."""

    success: bool = False
    user: User | None = None
    new_refresh_token: str | None = None
    new_session: RefreshSession | None = None
    event: str | None = None
    event_user_id: uuid.UUID | None = None


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(48)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _expiry() -> datetime:
    return _now() + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)


async def issue_session(
    db: AsyncSession, user: User, ip_address: str | None
) -> tuple[str, RefreshSession]:
    """Create a brand-new session (first in its family). Returns (raw_token, session).

    Caller commits; nothing is written to disk until then."""
    token = generate_refresh_token()
    session_id = uuid.uuid4()
    session = RefreshSession(
        id=session_id,
        user_id=user.id,
        token_hash=hash_token(token),
        family_id=session_id,
        parent_id=None,
        expires_at=_expiry(),
        ip_address=ip_address,
    )
    db.add(session)
    return token, session


async def rotate_session(
    db: AsyncSession, refresh_token: str, ip_address: str | None
) -> RotateResult:
    """Rotate one refresh token: the presented token dies, its child lives on.

    Reuse of an already-revoked token revokes the whole family (theft signal);
    a deactivated account's token does the same. Returns a RotateResult; the
    caller decides how to respond and audits in the same transaction."""
    session_result = await db.execute(
        select(RefreshSession)
        .where(RefreshSession.token_hash == hash_token(refresh_token))
        .with_for_update()
    )
    session = session_result.scalar_one_or_none()

    if session is None:
        return RotateResult()

    if session.revoked_at is not None:
        # Reuse of a dead token. Within a short grace window this is the benign
        # concurrent-race case (two tabs refreshing the same token at once): we
        # reject, but the winner's new token stays usable. Outside the window it
        # is assumed to be theft — kill the whole chain so a stolen rotation
        # can't keep rolling.
        if (
            session.revoked_reason == "rotated"
            and (_now() - session.revoked_at).total_seconds()
            <= settings.REFRESH_TOKEN_REUSE_GRACE_SECONDS
        ):
            return RotateResult()
        await revoke_family(db, session.family_id, "reuse_detected")
        return RotateResult(
            event="refresh_reuse_detected", event_user_id=session.user_id
        )

    if session.expires_at <= _now():
        return RotateResult()

    user_result = await db.execute(select(User).where(User.id == session.user_id))
    user = user_result.scalar_one_or_none()
    if user is None or not user.is_active:
        await revoke_family(db, session.family_id, "user_deactivated")
        return RotateResult(
            event="refresh_rejected_deactivated", event_user_id=session.user_id
        )

    session.revoked_at = _now()
    session.revoked_reason = "rotated"

    new_token = generate_refresh_token()
    new_session = RefreshSession(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=hash_token(new_token),
        family_id=session.family_id,
        parent_id=session.id,
        expires_at=_expiry(),
        ip_address=ip_address,
    )
    db.add(new_session)
    return RotateResult(success=True, user=user, new_refresh_token=new_token, new_session=new_session)


async def revoke_token(db: AsyncSession, refresh_token: str) -> RefreshSession | None:
    """Revoke the family of the presented token (logout). Returns the matched
    session, or None for an unknown token. Idempotent: revoking an already-dead
    family is a no-op on active rows. Deterministic vs a concurrent refresh —
    both paths take the same row lock first."""
    result = await db.execute(
        select(RefreshSession)
        .where(RefreshSession.token_hash == hash_token(refresh_token))
        .with_for_update()
    )
    session = result.scalar_one_or_none()
    if session is None:
        return None
    await revoke_family(db, session.family_id, "logout")
    return session


async def revoke_family(
    db: AsyncSession, family_id: uuid.UUID, reason: RevokeReason
) -> None:
    """Revoke every still-active session in a rotation family."""
    await db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.family_id == family_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=_now(), revoked_reason=reason)
    )


async def revoke_user_sessions(
    db: AsyncSession, user_id: uuid.UUID, reason: RevokeReason
) -> None:
    """Revoke every still-active session belonging to a user (deactivation)."""
    await db.execute(
        update(RefreshSession)
        .where(
            RefreshSession.user_id == user_id,
            RefreshSession.revoked_at.is_(None),
        )
        .values(revoked_at=_now(), revoked_reason=reason)
    )
