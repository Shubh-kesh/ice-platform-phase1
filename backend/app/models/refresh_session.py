"""
M9 — server-side refresh sessions: the rotating, revocable half of auth.

Every refresh token issued is an opaque random secret; only its SHA-256 digest
is stored here (`token_hash`), so a database leak never exposes a usable token.
Each row is single-use: a successful refresh marks the presented row revoked
(reason 'rotated') and inserts a child row in the same family. Reuse of a token
that should be dead is treated as theft and revokes the entire family, killing
any newer tokens the attacker's victim was relying on.

Access tokens remain stateless HS256 JWTs; this table never stores raw refresh
tokens. The design stays compatible with future M11 Google Sign-In by keying
everything off `user_id` and adding no provider-specific columns.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class RefreshSession(Base):
    __tablename__ = "refresh_sessions"
    __table_args__ = (
        Index("ix_refresh_sessions_user_revoked", "user_id", "revoked_at"),
        Index("ix_refresh_sessions_family", "family_id"),
        Index("ix_refresh_sessions_expires", "expires_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # SHA-256 hex digest of the opaque refresh token — never the token itself.
    # The unique index is the single-use guarantee at the DB level.
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    # Rotation chain group: the first session's id. Reuse of a dead token
    # revokes the whole family so a stolen chain can't keep rolling.
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # The session this one replaced, forming the rotation chain.
    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("refresh_sessions.id", ondelete="SET NULL"),
        nullable=True,
    )
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # logout | rotated | reuse_detected | user_deactivated | expired
    revoked_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # IP that issued this session (login, or the rotation that created it).
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
