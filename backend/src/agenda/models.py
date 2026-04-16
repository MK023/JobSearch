"""Agenda to-do item model."""

from datetime import UTC, datetime

from sqlalchemy import Boolean, Column, DateTime, Integer, String

from ..database.base import Base


class TodoItem(Base):
    """A user-created task on the agenda page."""

    __tablename__ = "todo_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    text = Column(String(500), nullable=False)
    done = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC))
    completed_at = Column(DateTime(timezone=True), nullable=True)
