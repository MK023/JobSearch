"""Add linkedin_applications table for LinkedIn Easy Apply import.

The table may already exist in some environments (it was bootstrapped directly
on Neon during exploratory data analysis on 2026-04-22, ahead of this
migration). The upgrade path is written to be idempotent so the migration can
re-apply cleanly in those environments and still initialise fresh databases.

Revision ID: 022
"""

from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Idempotent DDL — safe to re-run on DBs where the table was created
    # manually ahead of this migration.
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS linkedin_applications (
            id SERIAL PRIMARY KEY,
            application_date TIMESTAMPTZ,
            contact_email TEXT,
            contact_phone TEXT,
            company_name TEXT,
            job_title TEXT,
            job_url TEXT,
            resume_name TEXT,
            question_and_answers TEXT,
            import_source TEXT NOT NULL DEFAULT 'linkedin_easy_apply',
            imported_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            CONSTRAINT uq_linkedin_apps_url_date UNIQUE (job_url, application_date)
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_linkedin_apps_company ON linkedin_applications (LOWER(company_name))")
    op.execute("CREATE INDEX IF NOT EXISTS ix_linkedin_apps_title ON linkedin_applications (LOWER(job_title))")
    op.execute("CREATE INDEX IF NOT EXISTS ix_linkedin_apps_date ON linkedin_applications (application_date)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_linkedin_apps_date")
    op.execute("DROP INDEX IF EXISTS ix_linkedin_apps_title")
    op.execute("DROP INDEX IF EXISTS ix_linkedin_apps_company")
    op.execute("DROP TABLE IF EXISTS linkedin_applications")
