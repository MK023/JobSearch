"""003_decision_promotion_state

Adds the promotion-state machine fields to ``decisions``:

- ``promotion_state``      String(32), NOT NULL, default 'idle'
- ``promotion_score``      Integer, nullable (stack-match score 0-100)
- ``promotion_started_at`` DateTime tz, nullable (background task start)
- ``promotion_error``      String(500), default '' (last failure reason)

Plus an index on ``promotion_state`` to support the dashboard's
"in flight" / "skipped_low_match" filters.

Revision ID: d2b3c4e5f6a7
Revises: c1a2b3d4e5f6
Create Date: 2026-04-28 13:50:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d2b3c4e5f6a7"
down_revision: str | None = "c1a2b3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # All four new columns added in one ALTER TABLE — Postgres does this
    # atomically and we avoid four separate locks on a small table.
    op.add_column(
        "decisions",
        sa.Column(
            "promotion_state",
            sa.String(length=32),
            nullable=False,
            server_default="idle",
        ),
    )
    op.add_column(
        "decisions",
        sa.Column("promotion_score", sa.Integer(), nullable=True),
    )
    op.add_column(
        "decisions",
        sa.Column(
            "promotion_started_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "decisions",
        sa.Column(
            "promotion_error",
            sa.String(length=500),
            nullable=False,
            server_default="",
        ),
    )
    # Hot-path filter for the future "promotions in flight" dashboard view
    # (e.g. the UI badge that shows pending promotions). Without an index
    # this becomes a sequential scan once the table grows.
    op.create_index(
        "ix_decisions_promotion_state",
        "decisions",
        ["promotion_state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_decisions_promotion_state", table_name="decisions")
    op.drop_column("decisions", "promotion_error")
    op.drop_column("decisions", "promotion_started_at")
    op.drop_column("decisions", "promotion_score")
    op.drop_column("decisions", "promotion_state")
