"""Add covering indexes for 2 unindexed foreign keys.

Postgres does NOT auto-create indexes on FK columns. Without them the FK
side of JOIN queries falls back to seq scan even when the referenced row
is found via the parent PK. Production hot paths fixed:

- ``batch_items.cv_id`` — cron pickup query filters by ``cv_id + status``
  on every batch run; without index this scans the full ``batch_items``
  table on each tick (still small today, but grows monotonically).
- ``audit_logs.user_id`` — security audit lookups "show actions by user X"
  on a table that grows ~10 rows/day permanently.

(``job_analyses.cv_id`` and ``interviews.analysis_id`` already had Index
entries in their respective ``__table_args__``, see PR5b / PR5a — they
are NOT duplicated here.)

Behavior-preserving: solo nuovi index, nessuna mutazione di shape.

Revision ID: 026
Revises: 025
Create Date: 2026-05-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "026"
down_revision: str | None = "025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("idx_batch_items_cv_id", "batch_items", ["cv_id"])
    op.create_index("idx_audit_logs_user_id", "audit_logs", ["user_id"])


def downgrade() -> None:
    op.drop_index("idx_audit_logs_user_id", table_name="audit_logs")
    op.drop_index("idx_batch_items_cv_id", table_name="batch_items")
