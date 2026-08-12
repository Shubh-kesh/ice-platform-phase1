import enum
import uuid
from datetime import datetime

from sqlalchemy import Enum, String, Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class UserRole(str, enum.Enum):
    ADMIN = "admin"
    SITE_SUPERVISOR = "site_supervisor"
    PROCUREMENT_MANAGER = "procurement_manager"
    CLIENT = "client"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    # NULL iff the user is Google-only (hashed_password IS NULL + google_sub IS
    # NULL => "Pending Google link" — an invite, not yet activated).
    hashed_password: Mapped[str | None] = mapped_column(String(255), nullable=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # Authoritative Google identity (`sub` is immutable; email is never trusted
    # as identity on its own). Unique index -> one ICE account per Google id.
    google_sub: Mapped[str | None] = mapped_column(
        String(255), unique=True, index=True, nullable=True
    )
    google_email: Mapped[str | None] = mapped_column(String(255), nullable=True)

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", native_enum=True), nullable=False
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role.value})>"

    @property
    def google_linked(self) -> bool:
        """True once the account has a Google identity bound (linked/activated)."""
        return self.google_sub is not None

    @property
    def has_password(self) -> bool:
        return self.hashed_password is not None
