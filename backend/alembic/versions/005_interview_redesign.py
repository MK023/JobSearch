"""Interview redesign: add platform, interviewer_name, meeting_id; rename phone_pin to access_pin; repurpose interview_type.

Revision ID: 005
Revises: 004
Create Date: 2026-03-12
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "005"
down_revision: str | None = "004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add new columns
    op.add_column("interviews", sa.Column("platform", sa.String(20), nullable=True))
    op.add_column("interviews", sa.Column("interviewer_name", sa.String(255), nullable=True))
    op.add_column("interviews", sa.Column("meeting_id", sa.String(100), nullable=True))

    # Rename phone_pin → access_pin
    op.alter_column("interviews", "phone_pin", new_column_name="access_pin")

    # Migrate existing interview_type values to platform:
    # virtual → platform=other, phone → platform=phone, in_person → platform=in_person
    op.execute(
        "UPDATE interviews SET platform = CASE "
        "WHEN interview_type = 'virtual' THEN 'other' "
        "WHEN interview_type = 'phone' THEN 'phone' "
        "WHEN interview_type = 'in_person' THEN 'in_person' "
        "ELSE NULL END"
    )

    # Clear interview_type (will now hold: tecnico, hr, conoscitivo, finale, other)
    op.execute("UPDATE interviews SET interview_type = NULL")


def downgrade() -> None:
    # Restore interview_type from platform
    op.execute(
        "UPDATE interviews SET interview_type = CASE "
        "WHEN platform = 'phone' THEN 'phone' "
        "WHEN platform = 'in_person' THEN 'in_person' "
        "WHEN platform IS NOT NULL THEN 'virtual' "
        "ELSE NULL END"
    )

    # Rename access_pin → phone_pin
    op.alter_column("interviews", "access_pin", new_column_name="phone_pin")

    # Drop new columns
    op.drop_column("interviews", "meeting_id")
    op.drop_column("interviews", "interviewer_name")
    op.drop_column("interviews", "platform")
