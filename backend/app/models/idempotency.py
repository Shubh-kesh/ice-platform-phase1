"""
M8 — idempotency keys: server-side claim ledger for retry-safe POSTs.

Every request carrying an `Idempotency-Key` header inserts a claim row here in
the SAME transaction as the mutation it protects. The unique index on
(actor_id, operation, idempotency_key) is the enforcement point: a concurrent
duplicate INSERT blocks on it until the first transaction commits or aborts, so
exactly one business operation can win per key. Completed claims store the
response so a retry can be replayed verbatim instead of re-executed.

Rows are retained after completion for the replay window (see IDEMPOTENCY_TTL
in services/idempotency.py); reusing an expired key is rejected with a 409 so a
stale retry can never silently duplicate a record.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (
        UniqueConstraint(
            "actor_id", "operation", "idempotency_key",
            name="uq_idempotency_actor_operation_key",
        ),
        Index("ix_idempotency_created_at", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    # The authenticated user who owns the key — keys are namespaced per user, so
    # one actor can never collide with another's key.
    actor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    # Route template the key was used on, e.g. "/projects/{project_id}/job-costs".
    operation: Mapped[str] = mapped_column(String(255), nullable=False)
    # sha256 hex of the canonicalized request (method + route + params + body).
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)  # in_progress | completed

    # Completed claims snapshot the response for verbatim replay on retry.
    response_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_body: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
