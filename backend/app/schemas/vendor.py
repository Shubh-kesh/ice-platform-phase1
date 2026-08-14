"""Pydantic request/response contracts for vendor master data (Phase 5, M14)."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class VendorBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    payment_terms: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=2000)
    notes: str | None = Field(default=None, max_length=2000)


class VendorCreate(VendorBase):
    """Create a vendor. No money fields; the name is unique (app 409)."""


class VendorUpdate(BaseModel):
    """All-optional partial update; `is_active=false` is a soft deactivate."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    contact_name: str | None = Field(default=None, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    payment_terms: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=2000)
    is_active: bool | None = None
    notes: str | None = Field(default=None, max_length=2000)


class VendorRead(VendorBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    is_active: bool
    created_at: datetime
    updated_at: datetime
