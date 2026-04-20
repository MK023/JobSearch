"""Add source column to job_analyses for per-source notification aggregation.

Revision ID: 021
"""

import sqlalchemy as sa
from alembic import op

revision = "021"
down_revision = "020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Existing rows predate the source split — backfill them as `cowork`
    # because that was the only user-facing ingestion path before the
    # Chrome extension (inbox flow) landed. Default on the column stays
    # `manual` so future direct inserts without an explicit source are
    # flagged as such instead of silently inheriting `cowork`.
    op.add_column(
        "job_analyses",
        sa.Column(
            "source",
            sa.String(20),
            nullable=False,
            server_default="manual",
        ),
    )
    op.execute("UPDATE job_analyses SET source = 'cowork' WHERE source = 'manual'")
    op.create_index("ix_job_analyses_source", "job_analyses", ["source"])


def downgrade() -> None:
    op.drop_index("ix_job_analyses_source", table_name="job_analyses")
    op.drop_column("job_analyses", "source")
