"""Pydantic schemas for the inbox ingestion endpoint."""

from typing import Literal

from pydantic import BaseModel, Field, HttpUrl

InboxSourceLiteral = Literal[
    "linkedin",
    "indeed",
    "infojobs",
    "wttj",
    "remote_ok",
    "manual",
    "other",
]


class InboxRequest(BaseModel):
    """Payload sent by the Chrome extension.

    ``raw_text`` is the unmodified copy/paste from the job posting page. Server
    is responsible for sanitization — never trust the client.
    """

    raw_text: str = Field(..., min_length=50, max_length=50_000)
    source_url: HttpUrl
    source: InboxSourceLiteral


class InboxResponse(BaseModel):
    """Reply to the extension after successful ingestion."""

    inbox_id: str
    status: str
    analysis_id: str | None = None
    dedup: bool = False
    message: str = ""
