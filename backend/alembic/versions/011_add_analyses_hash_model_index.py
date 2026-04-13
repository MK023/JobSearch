"""Add composite index on (content_hash, model_used) to job_analyses.

find_existing_analysis filters on both columns; today only content_hash
is indexed, forcing a filter pass over all rows that share the same hash.
The composite index makes the lookup a single index probe.

Uses raw SQL with IF NOT EXISTS so the migration is safe to re-run on any
database where the index was already created manually.

Revision ID: 011
Revises: 010
Create Date: 2026-04-13
"""

from collections.abc import Sequence

from alembic import op

revision: str = "011"
down_revision: str | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE INDEX IF NOT EXISTS idx_analyses_content_hash_model ON job_analyses (content_hash, model_used)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_analyses_content_hash_model")
