"""Add benefits, recruiter_info and experience_required columns to job_analyses.

All three columns are nullable JSON (default NULL). Existing rows are unaffected.

Revision ID: 010
Revises: 009
Create Date: 2026-04-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "010"
down_revision: str | None = "009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("job_analyses", sa.Column("benefits", sa.JSON(), nullable=True))
    op.add_column("job_analyses", sa.Column("recruiter_info", sa.JSON(), nullable=True))
    op.add_column("job_analyses", sa.Column("experience_required", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("job_analyses", "experience_required")
    op.drop_column("job_analyses", "recruiter_info")
    op.drop_column("job_analyses", "benefits")
