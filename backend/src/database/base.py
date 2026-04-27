"""Database engine, session factory, and base model."""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import QueuePool

from ..config import settings

# TCP keepalives keep idle SSL connections alive during long-running
# work that doesn't touch the DB (e.g. ``/api/v1/batch/run`` waits on
# Anthropic for ~10–30 s while holding the session open). Without them
# Neon silently drops the SSL socket and the eventual ``db.close()`` →
# implicit rollback raises OperationalError (Sentry: JOBSEARCH-E,
# regressed 2026-04-27). Pool pre-ping covers checkout-time staleness
# but not mid-request drops, so we need both layers.
#
# Values tuned for psycopg2 on a Linux host:
#   keepalives=1            enable
#   keepalives_idle=30      first probe after 30 s of inactivity
#   keepalives_interval=10  follow-up probes every 10 s
#   keepalives_count=5      give up after 5 missed probes
# Total recovery window ≈ 80 s — well below Neon's idle drop threshold.
_KEEPALIVE_ARGS: dict[str, int] = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 5,
}
_db_url = settings.effective_database_url
_connect_args = _KEEPALIVE_ARGS if _db_url.startswith("postgresql") else {}

engine = create_engine(
    _db_url,
    poolclass=QueuePool,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,
    # Recycle connections before Neon's 5-min idle autosuspend kicks in.
    pool_recycle=240,
    connect_args=_connect_args,
)

SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    """SQLAlchemy declarative base for all ORM models."""

    pass


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and ensure it is closed after use."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
