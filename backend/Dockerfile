FROM python:3.12-slim

WORKDIR /app/backend

COPY backend/requirements.txt .
# antiword: legacy .doc CV parsing (interview file uploads).
# postgresql-client-17: pg_dump for the disaster-recovery backup pipeline
# (db_dump.create_pg_dump_backup). Pinned to 17 to match the server major
# (Supabase + Neon both run PG 17). Debian slim ships pg-client 15, so we
# pull the apt.postgresql.org repo to get 17.
RUN apt-get update \
    && apt-get install -y --no-install-recommends antiword ca-certificates curl gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo $VERSION_CODENAME)-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-17 \
    && apt-get purge -y --auto-remove curl gnupg \
    && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY frontend/ /app/frontend/

# Production command. Render uses PORT env var (default 10000).
# Local dev: docker-compose overrides with --reload --port 8000
CMD sh -c "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"
