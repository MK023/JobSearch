"""Add covering indexes for 3 unindexed FK trovati dal Supabase advisor.

L'advisor ``unindexed_foreign_keys`` su Pulse (post-PR7) ha rivelato 3 FK
ancora senza index covering — sfuggiti all'audit Explore precedente:

- ``batch_items.analysis_id`` — FK SET NULL su ``job_analyses``; usata da
  query "find batch item by analysis" + cascade lookup
- ``inbox_items.analysis_id`` — FK SET NULL su ``job_analyses``; usata da
  query "inbox triage state" + dedup post-promote
- ``user_profiles.source_run_id`` — FK SET NULL su ``analytics_runs``;
  usata da "qual è la run che ha generato il profile attuale"

Behavior-preserving: solo nuovi index, nessuna mutazione di shape.

Revision ID: 027
Revises: 026
Create Date: 2026-05-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "027"
down_revision: str | None = "026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("idx_batch_items_analysis_id", "batch_items", ["analysis_id"])
    op.create_index("idx_inbox_items_analysis_id", "inbox_items", ["analysis_id"])
    op.create_index("idx_user_profiles_source_run_id", "user_profiles", ["source_run_id"])


def downgrade() -> None:
    op.drop_index("idx_user_profiles_source_run_id", table_name="user_profiles")
    op.drop_index("idx_inbox_items_analysis_id", table_name="inbox_items")
    op.drop_index("idx_batch_items_analysis_id", table_name="batch_items")
