"""Authentication request/response schemas."""

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    """Schema for login form submission."""

    email: EmailStr
    password: str = Field(..., min_length=1, max_length=255)


class UserResponse(BaseModel):
    """Public-facing user representation (no password hash)."""

    id: str
    email: str
    is_active: bool

    model_config = {"from_attributes": True}
