"""002_decisions_unique_and_decision_idx

Adds:
- ``UNIQUE(job_offer_id)`` on ``decisions`` — one decision per offer
  (idempotency at the DB layer, not just the app layer).
- ``ix_decisions_decision`` — supports the hot filter ``WHERE decision = 'pending'``
  used by both ``_query_offers`` and ``_quick_counts``.

Revision ID: c1a2b3d4e5f6
Revises: b17f6abc63d9
Create Date: 2026-04-28 11:50:00.000000
"""

from collections.abc import Sequence

from alembic import op

revision: str = "c1a2b3d4e5f6"
down_revision: str | None = "b17f6abc63d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Drop the previous (non-unique) index on job_offer_id and replace with a
    # UNIQUE one. This enforces "one decision per offer" at the schema level —
    # the app layer already does upsert, but a DB-level guard prevents drift.
    op.drop_index("ix_decisions_job_offer_id", table_name="decisions")
    op.create_index(
        "ix_decisions_job_offer_id",
        "decisions",
        ["job_offer_id"],
        unique=True,
    )
    # Hot-path filter on decision='pending' from the WorldWild page query
    # and the badge counts; without this, a sequential scan kicks in once
    # the table grows past a few thousand rows.
    op.create_index(
        "ix_decisions_decision",
        "decisions",
        ["decision"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_decisions_decision", table_name="decisions")
    op.drop_index("ix_decisions_job_offer_id", table_name="decisions")
    op.create_index(
        "ix_decisions_job_offer_id",
        "decisions",
        ["job_offer_id"],
        unique=False,
    )
