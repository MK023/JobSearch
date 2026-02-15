"""Authentication request/response schemas."""

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=255)


class UserResponse(BaseModel):
    id: str
    email: str
    is_active: bool

    model_config = {"from_attributes": True}
