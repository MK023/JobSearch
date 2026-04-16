"""Add salary_data/company_news columns + salary_cache/news_cache tables.

Revision ID: 017
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "017"
down_revision = "016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_analyses", sa.Column("salary_data", sa.JSON, nullable=True))
    op.add_column("job_analyses", sa.Column("company_news", sa.JSON, nullable=True))

    op.create_table(
        "salary_cache",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("cache_key", sa.String(255), unique=True, index=True, nullable=False),
        sa.Column("salary_data", sa.Text, server_default=""),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
    )

    op.create_table(
        "news_cache",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_name", sa.String(255), unique=True, index=True, nullable=False),
        sa.Column("news_data", sa.Text, server_default=""),
        sa.Column("fetched_at", sa.DateTime(timezone=True)),
    )


def downgrade() -> None:
    op.drop_table("news_cache")
    op.drop_table("salary_cache")
    op.drop_column("job_analyses", "company_news")
    op.drop_column("job_analyses", "salary_data")
