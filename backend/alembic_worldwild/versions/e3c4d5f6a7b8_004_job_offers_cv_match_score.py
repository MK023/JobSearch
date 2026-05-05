"""004_job_offers_cv_match_score

Aggiunge ``cv_match_score`` a ``job_offers`` per la stack-match score
calcolata at-ingest (0-100, ``NULL`` quando l'offer non ha tech tokens
estraibili o il CV non era disponibile al momento dell'ingest).

- ``cv_match_score``  Integer, nullable (consistente con ``promotion_score``
  su ``decisions`` per i casi "non scoreable").

Plus indice per supportare future query "show offers with high match"
e i filtri dashboard tipo ``WHERE cv_match_score >= 50``.

Revision ID: e3c4d5f6a7b8
Revises: d2b3c4e5f6a7
Create Date: 2026-05-04 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e3c4d5f6a7b8"
down_revision: str | None = "d2b3c4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Single ALTER TABLE: aggiungiamo la colonna nullable senza default,
    # le righe pre-esistenti restano a NULL (semantica: "score sconosciuto,
    # ingest pre-feature"). Marco può fare backfill in batch quando vuole.
    op.add_column(
        "job_offers",
        sa.Column("cv_match_score", sa.Integer(), nullable=True),
    )
    # Indice per le query di filtraggio "alta match" sulla dashboard.
    # Senza, una scansione sequenziale parte una volta che la tabella cresce.
    op.create_index(
        "ix_job_offers_cv_match_score",
        "job_offers",
        ["cv_match_score"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_job_offers_cv_match_score", table_name="job_offers")
    op.drop_column("job_offers", "cv_match_score")
