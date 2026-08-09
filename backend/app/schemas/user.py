import re
import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, ConfigDict, field_validator

from app.models.user import UserRole


class UserBase(BaseModel):
    email: EmailStr
    full_name: str
    phone: str | None = None
    role: UserRole


class UserCreate(UserBase):
    password: str

    @field_validator("password")
    @classmethod
    def validate_password(cls, v: str) -> str:
        """
        Password must meet security requirements:
        - Minimum 8 characters
        - At least one uppercase letter
        - At least one digit
        """
        if len(v) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not re.search(r"[A-Z]", v):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"\d", v):
            raise ValueError("Password must contain at least one digit")
        return v


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool
    created_at: datetime


class UserUpdate(BaseModel):
    full_name: str | None = None
    phone: str | None = None
    is_active: bool | None = None
