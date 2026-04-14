"""Add app_preferences table for persisted runtime settings.

A generic key-value store for toggles/settings that used to live as env vars.
First consumer: ai_sonnet_fallback_on_low_confidence (was in config.py).

Keys are VARCHAR(100) PK, values are JSON (JSONB on Postgres, JSON on SQLite).
Access is whitelisted by the preferences service — no arbitrary key writes.

Revision ID: 012
Revises: 011
Create Date: 2026-04-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: str | None = "011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_preferences",
        sa.Column("key", sa.String(length=100), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("app_preferences")
