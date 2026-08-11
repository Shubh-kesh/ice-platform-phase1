"""
Schema for audited manual health overrides (Phase 3, M3).

Computed project health (Timeline/Budget/Safety + Overall) is derived on read
from source-of-truth rows (tasks, job-cost ledger, lifecycle). The only *manual*
health write is a `health_overrides` row: an admin can override a green/amber/red
verdict on a dimension or on Overall. Overrides are immutable after creation —
revocation is a soft timestamp on an otherwise-append-only record (same
convention as daily_site_logs / audit_logs).
"""
import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.project import Project


class HealthOverrideTarget(str, enum.Enum):
    """Which verdict an override replaces: a single dimension or the Overall."""
    OVERALL = "overall"
    TIMELINE = "timeline"
    BUDGET = "budget"
    SAFETY = "safety"


class HealthOverrideValue(str, enum.Enum):
    """Override verdicts are always a color — NOT_RATED is NOT overridable
    (you cannot override a data shortage away)."""
    GREEN = "green"
    AMBER = "amber"
    RED = "red"


class HealthOverride(Base):
    __tablename__ = "health_overrides"
    __table_args__ = (
        # Single-active-per-target is a DB guarantee: at most one *non-revoked*
        # override per (project, applied_to). Postgres forbids `now()` (STABLE)
        # in an index predicate, so expiry is deliberately NOT part of the index
        # — it is honoured by the application layer (the effective verdict) and
        # by the create flow, which revokes every prior non-revoked override for
        # the target (expired ones included) before inserting the new one. A row
        # leaves the active set on revoke, so history for the same target grows
        # without violating uniqueness.
        Index(
            "uq_health_overrides_active_per_target",
            "project_id",
            "applied_to",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    applied_to: Mapped[HealthOverrideTarget] = mapped_column(
        Enum(HealthOverrideTarget, name="health_override_target"), nullable=False
    )
    value: Mapped[HealthOverrideValue] = mapped_column(
        Enum(HealthOverrideValue, name="health_override_value"), nullable=False
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    set_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    project: Mapped["Project"] = relationship()