# syntax=docker/dockerfile:1.7
#
# Multi-stage Python 3.12 image — K8s-ready, CIS Docker Benchmark aligned.
#
# Stage 1 (builder): native build deps + pip wheels in an isolated venv.
#                    Never reaches the runtime image.
# Stage 2 (runtime): slim base, non-root user, immutable application code,
#                    runtime-only system packages, no compilers.

# ──────────────────────────────────────────────────────────────────────
# Stage 1 — Builder
# ──────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# gcc + libpq-dev needed to build psycopg2-binary, cryptography, lxml
# wheels on linux/arm64. Discarded at end of stage.
RUN apt-get update \
    && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Isolated virtualenv → clean copy boundary into the runtime image.
# Avoids polluting the system site-packages of the final layer.
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt


# ──────────────────────────────────────────────────────────────────────
# Stage 2 — Runtime
# ──────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

# ── Best practice: runtime-only system packages ──────────────────────
# - antiword:           legacy .doc CV parsing (interview file uploads)
# - postgresql-client-17: pg_dump for the DR backup pipeline. Pinned to
#                       17 to match server major (Supabase + Neon both
#                       run PG 17). Debian slim ships pg-client 15, so
#                       we pull the apt.postgresql.org repo.
# - curl:               K8s livenessProbe / readinessProbe via httpGet,
#                       and Compose healthcheck via `curl -fsS`.
# Build tools deliberately absent — see the builder stage for those.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        antiword \
        ca-certificates \
        curl \
        gnupg \
    && install -d /usr/share/postgresql-common/pgdg \
    && curl -fsSL https://www.postgresql.org/media/keys/ACCC4CF8.asc \
        -o /usr/share/postgresql-common/pgdg/apt.postgresql.org.asc \
    && echo "deb [signed-by=/usr/share/postgresql-common/pgdg/apt.postgresql.org.asc] https://apt.postgresql.org/pub/repos/apt $(. /etc/os-release && echo $VERSION_CODENAME)-pgdg main" \
        > /etc/apt/sources.list.d/pgdg.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client-17 \
    && apt-get purge -y --auto-remove gnupg \
    && rm -rf /var/lib/apt/lists/*

# ── Security: non-root user (CIS Docker Benchmark 4.1) ───────────────
# uid=1001 sits above the Debian system range (0-999) and avoids
# collisions with distroless conventions. K8s
# `securityContext.runAsNonRoot: true` requires this to be enforceable
# at admission time without falling back to uid 0.
RUN groupadd --system --gid 1001 app \
    && useradd --system --uid 1001 --gid 1001 \
        --no-create-home --shell /usr/sbin/nologin app

# ── Security: immutable application code ─────────────────────────────
# venv + app code copied with --chown=app:app; runtime user cannot
# overwrite them. This unlocks
# `securityContext.readOnlyRootFilesystem: true` in K8s (with /tmp
# mounted as emptyDir for libs that need scratch space).
COPY --from=builder --chown=app:app /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

WORKDIR /app/backend
COPY --chown=app:app backend/ .
COPY --chown=app:app frontend/ /app/frontend/

# ── Runtime hygiene ──────────────────────────────────────────────────
# - PYTHONUNBUFFERED:        stdout/stderr unbuffered → 12-factor logs
#                            captured by the container engine in real
#                            time, no log loss on SIGTERM.
# - PYTHONDONTWRITEBYTECODE: no .pyc files written at runtime → smaller
#                            writes, compatible with read-only root FS.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER app

EXPOSE 8000

# Render reads $PORT (default 10000). Compose dev / CI uses 8000.
# Uvicorn handles SIGTERM correctly (graceful shutdown of in-flight
# requests within the configured timeout) — no `tini` / `dumb-init`
# wrapper needed for PID 1 signal reaping.
CMD ["sh", "-c", "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"]
