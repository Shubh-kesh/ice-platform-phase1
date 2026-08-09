import enum
import uuid
from datetime import date, datetime

from sqlalchemy import Enum, String, Date, DateTime, ForeignKey, Numeric, func, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ProjectStatus(str, enum.Enum):
    PLANNING = "planning"
    ACTIVE = "active"
    ON_HOLD = "on_hold"
    COMPLETED = "completed"


class HealthStatus(str, enum.Enum):
    """Drives the color-coded indicators on the command center dashboard."""
    GREEN = "green"    # on track
    AMBER = "amber"    # at risk
    RED = "red"        # off track / blocked


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    site_address: Mapped[str] = mapped_column(Text, nullable=False)
    client_name: Mapped[str] = mapped_column(String(255), nullable=False)

    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"), default=ProjectStatus.PLANNING, nullable=False
    )

    # Command-center health indicators — computed periodically by a
    # background job in Phase 2, manually settable for now.
    timeline_health: Mapped[HealthStatus] = mapped_column(
        Enum(HealthStatus, name="timeline_health"), default=HealthStatus.GREEN, nullable=False
    )
    budget_health: Mapped[HealthStatus] = mapped_column(
        Enum(HealthStatus, name="budget_health"), default=HealthStatus.GREEN, nullable=False
    )
    safety_health: Mapped[HealthStatus] = mapped_column(
        Enum(HealthStatus, name="safety_health"), default=HealthStatus.GREEN, nullable=False
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    target_end_date: Mapped[date] = mapped_column(Date, nullable=False)

    budget_total: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    budget_spent: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    percent_complete: Mapped[int] = mapped_column(default=0)  # 0-100

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    assignments: Mapped[list["ProjectAssignment"]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class ProjectAssignment(Base):
    """
    Links users to projects — a Site Supervisor is assigned to the sites
    they run, a Client is assigned (view-only) to their own project(s).
    Admin and Procurement Manager see all projects regardless of assignment.
    """
    __tablename__ = "project_assignments"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship(back_populates="assignments")
