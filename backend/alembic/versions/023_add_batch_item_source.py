"""Add source column to batch_items so the batch pipeline preserves its origin.

Revision ID: 023

The Cowork workflow calls the MCP ``batch_add`` tool, which goes through
``/api/v1/batch/add`` → ``add_to_queue`` → ``_execute_analysis`` →
``run_analysis``. Until now ``run_analysis`` ran with its default
``source=manual`` because ``BatchItem`` had no place to carry the
caller's source through.

Result: every analysis from the Cowork workflow ended up tagged
``source=manual`` in ``job_analyses``, which made the dashboard
"Da valutare — Cowork" widget filter (``source=cowork``) miss them.

This migration adds the column with default ``manual`` so existing rows
stay valid; new Cowork batches will populate it via the API parameter
added in the same PR.
"""

import sqlalchemy as sa
from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "batch_items",
        sa.Column(
            "source",
            sa.String(20),
            nullable=False,
            server_default="manual",
        ),
    )


def downgrade() -> None:
    op.drop_column("batch_items", "source")
