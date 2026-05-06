"""Add english_level_required column to job_analyses.

Tracks the English proficiency level demanded by a JD (extracted by AI in a
later PR). Stored as compact CEFR string (A1/A2/B1/B2/C1/C2 + ``Native``)
so we can do ordinal comparison in Python; empty string when the JD does
not mention English at all.

Revision ID: 024
Revises: 023
Create Date: 2026-05-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "024"
down_revision: str | None = "023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "job_analyses",
        sa.Column("english_level_required", sa.String(length=8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("job_analyses", "english_level_required")
