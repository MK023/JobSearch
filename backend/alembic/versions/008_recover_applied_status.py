"""Recover 'candidato' status lost due to model/DB type mismatch.

The status column was created as VARCHAR(20) in migration 001 but the
SQLAlchemy model was later changed to SQLEnum, causing a silent reset
of 'candidato' values to 'da_valutare' on deploy.

Recovery uses applied_at (set only when status changes to candidato/colloquio)
to identify affected rows.

Revision ID: 008
Revises: 007
Create Date: 2026-04-07
"""

from collections.abc import Sequence

from alembic import op

revision: str = "008"
down_revision: str | None = "007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Restore 'candidato' for rows that have applied_at but were reset to 'da_valutare'.
    # 'colloquio' rows are unaffected (confirmed intact).
    op.execute("UPDATE job_analyses SET status = 'candidato' WHERE applied_at IS NOT NULL AND status = 'da_valutare'")


def downgrade() -> None:
    # Cannot reverse: we don't know which rows were originally 'da_valutare'
    pass
