"""Add career_track and track_reason to job_analyses.

Revision ID: 018
"""

import sqlalchemy as sa
from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("job_analyses", sa.Column("career_track", sa.String(30), nullable=True))
    op.add_column("job_analyses", sa.Column("track_reason", sa.Text, nullable=True))
    op.create_index("idx_job_analyses_career_track", "job_analyses", ["career_track"])


def downgrade() -> None:
    op.drop_index("idx_job_analyses_career_track", table_name="job_analyses")
    op.drop_column("job_analyses", "track_reason")
    op.drop_column("job_analyses", "career_track")
