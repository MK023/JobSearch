"""Secondary database engine for the WorldWild ingest layer (Supabase).

Kept fully separate from the primary engine in ``base.py``: different declarative
``WorldwildBase``, different ``sessionmaker``, different metadata. The two
databases never share migrations or ORM relationships — promotion of curated
job offers from Supabase into Neon's ``job_analyses`` happens in application
code, not via cross-DB FK or query.

When ``WORLDWILD_DATABASE_URL`` is empty (the default in dev / CI / test),
``engine`` and ``WorldwildSessionLocal`` are ``None``. Callers must check
``worldwild_enabled`` before using the session factory; routes degrade
gracefully with a 503 when the layer is disabled.
"""

from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import QueuePool

from ..config import settings

# Same keepalive args as base.py: Supabase Session Pooler exhibits the same
# idle-SSL-drop behavior as Neon when batch work holds a session open while
# waiting on a slow upstream (Adzuna API, Anthropic analyzer). Tuned for
# psycopg2 on Linux; total recovery window ~80 s.
_KEEPALIVE_ARGS: dict[str, int] = {
    "keepalives": 1,
    "keepalives_idle": 30,
    "keepalives_interval": 10,
    "keepalives_count": 5,
}


class WorldwildBase(DeclarativeBase):
    """Declarative base for ORM models stored in the secondary DB.

    Intentionally separate from primary ``Base``: prevents accidental
    ``Base.metadata.create_all(worldwild_engine)`` from leaking primary tables
    onto Supabase, and vice versa.
    """

    pass


def _build_engine() -> Engine | None:
    url = settings.effective_worldwild_database_url
    if not url:
        return None
    connect_args = _KEEPALIVE_ARGS if url.startswith("postgresql") else {}
    return create_engine(
        url,
        poolclass=QueuePool,
        # Smaller pool than primary: WorldWild is cron-driven (1 ingest/day)
        # plus low-traffic interactive page. 3+5 leaves plenty of headroom on
        # Supabase free tier connection limits.
        pool_size=3,
        max_overflow=5,
        pool_pre_ping=True,
        pool_recycle=240,
        connect_args=connect_args,
    )


engine: Engine | None = _build_engine()
WorldwildSessionLocal: sessionmaker[Session] | None = sessionmaker(bind=engine) if engine is not None else None
worldwild_enabled: bool = engine is not None


def get_worldwild_db() -> Generator[Session, None, None]:
    """Yield a WorldWild session, or raise if the secondary DB is disabled.

    Routes that depend on this should check ``worldwild_enabled`` first and
    return a 503 / friendly empty-state, so the runtime error here is a
    safety net, not the primary degradation path.
    """
    if WorldwildSessionLocal is None:
        raise RuntimeError(
            "WorldWild secondary DB is not configured (WORLDWILD_DATABASE_URL is empty). Check Render env vars."
        )
    db = WorldwildSessionLocal()
    try:
        yield db
    finally:
        db.close()
