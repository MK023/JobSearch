"""Contact request/response schemas."""

from pydantic import BaseModel, Field


class ContactCreateRequest(BaseModel):
    analysis_id: str = ""
    name: str = Field("", max_length=255)
    email: str = Field("", max_length=255)
    phone: str = Field("", max_length=50)
    company: str = Field("", max_length=255)
    linkedin_url: str = Field("", max_length=500)
    notes: str = ""
    source: str = Field("manual", max_length=20)


class ContactResponse(BaseModel):
    id: str
    name: str
    email: str
    phone: str
    company: str
    linkedin_url: str
    notes: str
    source: str

    model_config = {"from_attributes": True}
