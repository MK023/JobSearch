"""Add analytics_runs + user_profiles tables.

Revision ID: 019
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "019"
down_revision = "018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "analytics_runs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, index=True),
        sa.Column("analyses_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("triggered_by", sa.String(20), server_default="manual"),
        sa.Column("snapshot", sa.JSON, nullable=False, server_default="{}"),
    )

    op.create_table(
        "user_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
            index=True,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True)),
        sa.Column(
            "source_run_id",
            UUID(as_uuid=True),
            sa.ForeignKey("analytics_runs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("profile", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("prompt_snippet", sa.Text, server_default=""),
    )


def downgrade() -> None:
    op.drop_table("user_profiles")
    op.drop_table("analytics_runs")
