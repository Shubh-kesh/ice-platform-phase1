import uuid
from datetime import date, datetime

from sqlalchemy import String, Date, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DailySiteLog(Base):
    """
    A site supervisor's end-of-day report for one project. This is the raw
    field data the command center's health indicators will eventually be
    computed from (Phase 2+ background job) — for now it's a simple
    append-only feed the supervisor writes and everyone with project access
    can read.
    """
    __tablename__ = "daily_site_logs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    log_date: Mapped[date] = mapped_column(Date, nullable=False)
    work_summary: Mapped[str] = mapped_column(Text, nullable=False)
    issues: Mapped[str | None] = mapped_column(Text, nullable=True)
    workers_present: Mapped[int | None] = mapped_column(Integer, nullable=True)
    weather: Mapped[str | None] = mapped_column(String(100), nullable=True)

    # Photo URLs — populated once GCS upload lands; empty list until then.
    photo_urls: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped["Project"] = relationship()  # noqa: F821
