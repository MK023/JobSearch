FROM python:3.12-slim

WORKDIR /app/backend

COPY backend/requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends antiword && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY frontend/ /app/frontend/

# Production command. Render uses PORT env var (default 10000).
# Local dev: docker-compose overrides with --reload --port 8000
CMD sh -c "uvicorn src.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --forwarded-allow-ips='*'"
