import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, ConfigDict, field_validator, model_validator

from app.models.user import UserRole


class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    phone: str | None = None
    role: UserRole


class UserCreate(UserBase):
    # google_only=true  -> no password; the user is an invite ("Pending Google
    #   link") who activates by signing in with a matching verified Google email.
    # google_only=false -> unchanged: password required, existing validators.
    google_only: bool = False
    password: str | None = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str | None) -> str | None:
        """
        Password must meet security requirements:
        - Minimum 8 characters
        - At least one uppercase letter
        - At least one digit
        """
        if v is None:
            return v
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v

    @model_validator(mode="after")
    def check_google_only_password(self) -> "UserCreate":
        if self.google_only and self.password is not None:
            raise ValueError("Password must not be provided for a Google-only account")
        if not self.google_only and self.password is None:
            raise ValueError("Password is required unless the account is Google-only")
        return self


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool
    created_at: datetime
    # Derived from the model: google_linked = google_sub bound; has_password =
    # password credential exists (Google-only invites expose both).
    google_linked: bool
    has_password: bool
    google_email: str | None = None


class UserUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    is_active: bool | None = None
    role: UserRole | None = None
