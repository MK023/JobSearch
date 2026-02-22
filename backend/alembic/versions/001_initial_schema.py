"""Initial schema with all tables, foreign keys, JSONB columns.

Revision ID: 001
Revises: None
Create Date: 2025-02-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision: str = "001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("email", sa.String(255), unique=True, nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), default=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"])

    op.create_table(
        "cv_profiles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("name", sa.String(255), default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_cv_profiles_user_id", "cv_profiles", ["user_id"])

    op.create_table(
        "job_analyses",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("cv_id", UUID(as_uuid=True), sa.ForeignKey("cv_profiles.id", ondelete="CASCADE"), nullable=False),
        sa.Column("job_description", sa.Text(), nullable=False),
        sa.Column("job_url", sa.String(500), default=""),
        sa.Column("content_hash", sa.String(64), default=""),
        sa.Column("job_summary", sa.Text(), default=""),
        sa.Column("company", sa.String(255), default=""),
        sa.Column("role", sa.String(255), default=""),
        sa.Column("location", sa.String(255), default=""),
        sa.Column("work_mode", sa.String(50), default=""),
        sa.Column("salary_info", sa.String(255), default=""),
        sa.Column("score", sa.Integer(), default=0),
        sa.Column("recommendation", sa.String(20), default=""),
        sa.Column("status", sa.String(20), default="da_valutare"),
        sa.Column("strengths", JSONB(), default=[]),
        sa.Column("gaps", JSONB(), default=[]),
        sa.Column("interview_scripts", JSONB(), default=[]),
        sa.Column("advice", sa.Text(), default=""),
        sa.Column("company_reputation", JSONB(), default={}),
        sa.Column("full_response", sa.Text(), default=""),
        sa.Column("model_used", sa.String(50), default=""),
        sa.Column("tokens_input", sa.Integer(), default=0),
        sa.Column("tokens_output", sa.Integer(), default=0),
        sa.Column("cost_usd", sa.Float(), default=0.0),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("followed_up", sa.Boolean(), default=False),
    )
    op.create_index("idx_analyses_score", "job_analyses", ["score"])
    op.create_index("idx_analyses_status", "job_analyses", ["status"])
    op.create_index("idx_analyses_created", "job_analyses", ["created_at"])
    op.create_index("idx_analyses_cv_id", "job_analyses", ["cv_id"])
    op.create_index("idx_analyses_content_hash", "job_analyses", ["content_hash"])

    op.create_table(
        "app_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("anthropic_budget", sa.Float(), default=0.0),
        sa.Column("total_cost_usd", sa.Float(), default=0.0),
        sa.Column("total_tokens_input", sa.Integer(), default=0),
        sa.Column("total_tokens_output", sa.Integer(), default=0),
        sa.Column("total_analyses", sa.Integer(), default=0),
        sa.Column("total_cover_letters", sa.Integer(), default=0),
        sa.Column("today_date", sa.String(10), default=""),
        sa.Column("today_cost_usd", sa.Float(), default=0.0),
        sa.Column("today_tokens_input", sa.Integer(), default=0),
        sa.Column("today_tokens_output", sa.Integer(), default=0),
        sa.Column("today_analyses", sa.Integer(), default=0),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "cover_letters",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id", UUID(as_uuid=True), sa.ForeignKey("job_analyses.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("language", sa.String(20), default="italiano"),
        sa.Column("content", sa.Text(), default=""),
        sa.Column("subject_lines", JSONB(), default=[]),
        sa.Column("model_used", sa.String(50), default=""),
        sa.Column("tokens_input", sa.Integer(), default=0),
        sa.Column("tokens_output", sa.Integer(), default=0),
        sa.Column("cost_usd", sa.Float(), default=0.0),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_cover_letters_analysis_id", "cover_letters", ["analysis_id"])

    op.create_table(
        "contacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "analysis_id", UUID(as_uuid=True), sa.ForeignKey("job_analyses.id", ondelete="CASCADE"), nullable=True
        ),
        sa.Column("name", sa.String(255), default=""),
        sa.Column("email", sa.String(255), default=""),
        sa.Column("phone", sa.String(50), default=""),
        sa.Column("company", sa.String(255), default=""),
        sa.Column("linkedin_url", sa.String(500), default=""),
        sa.Column("notes", sa.Text(), default=""),
        sa.Column("source", sa.String(20), default="manual"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_contacts_analysis_id", "contacts", ["analysis_id"])

    op.create_table(
        "glassdoor_cache",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("company_name", sa.String(255), unique=True, nullable=False),
        sa.Column("glassdoor_data", sa.Text(), default=""),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("review_count", sa.Integer(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_glassdoor_cache_company_name", "glassdoor_cache", ["company_name"])


def downgrade() -> None:
    op.drop_table("glassdoor_cache")
    op.drop_table("contacts")
    op.drop_table("cover_letters")
    op.drop_table("app_settings")
    op.drop_table("job_analyses")
    op.drop_table("cv_profiles")
    op.drop_table("users")
