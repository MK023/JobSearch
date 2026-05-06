"""Add english_level column to cv_profiles.

Stores the user-declared CEFR proficiency level (A1..C2/Native, normalized
via ``normalize_cefr_token``). Used by PR4 to compute match/gap vs the
``english_level_required`` field already extracted by AI on JobAnalysis.

Revision ID: 025
Revises: 024
Create Date: 2026-05-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "025"
down_revision: str | None = "024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "cv_profiles",
        sa.Column("english_level", sa.String(length=8), nullable=True, server_default=""),
    )


def downgrade() -> None:
    op.drop_column("cv_profiles", "english_level")
