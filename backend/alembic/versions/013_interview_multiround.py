"""Multi-round interview support.

Drop the 1:1 unique constraint on interviews.analysis_id so a single
JobAnalysis can have multiple Interview rows (one per round). Add
``round_number`` (ordinal of the round, 1-indexed) and ``outcome``
(per-round result: passed, rejected, withdrawn, pending; null while the
round is still future-scheduled).

Revision ID: 013
Revises: 012
Create Date: 2026-04-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: str | None = "012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # Drop unique constraint so multiple rounds can share the same analysis.
    # Postgres named the constraint via SQLAlchemy convention; SQLite needs
    # batch mode to recreate the table without it. Detect and branch.
    is_sqlite = bind.dialect.name == "sqlite"

    existing_constraints = {uc["name"] for uc in inspector.get_unique_constraints("interviews")}

    if is_sqlite:
        with op.batch_alter_table("interviews") as batch:
            for name in existing_constraints:
                if name:
                    batch.drop_constraint(name, type_="unique")
            batch.add_column(sa.Column("round_number", sa.Integer(), nullable=False, server_default="1"))
            batch.add_column(sa.Column("outcome", sa.String(length=20), nullable=True))
            batch.create_index("idx_interviews_analysis_id", ["analysis_id"])
    else:
        for name in existing_constraints:
            if name:
                op.drop_constraint(name, "interviews", type_="unique")
        op.add_column(
            "interviews",
            sa.Column("round_number", sa.Integer(), nullable=False, server_default="1"),
        )
        op.add_column("interviews", sa.Column("outcome", sa.String(length=20), nullable=True))
        op.create_index("idx_interviews_analysis_id", "interviews", ["analysis_id"])


def downgrade() -> None:
    bind = op.get_bind()
    is_sqlite = bind.dialect.name == "sqlite"

    if is_sqlite:
        with op.batch_alter_table("interviews") as batch:
            batch.drop_index("idx_interviews_analysis_id")
            batch.drop_column("outcome")
            batch.drop_column("round_number")
            batch.create_unique_constraint("uq_interviews_analysis_id", ["analysis_id"])
    else:
        op.drop_index("idx_interviews_analysis_id", table_name="interviews")
        op.drop_column("interviews", "outcome")
        op.drop_column("interviews", "round_number")
        op.create_unique_constraint("uq_interviews_analysis_id", "interviews", ["analysis_id"])
