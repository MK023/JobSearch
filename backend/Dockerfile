FROM python:3.12-slim

WORKDIR /app/backend

COPY backend/requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends antiword && rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ .
COPY frontend/ /app/frontend/

# Default command for local development (--reload enabled)
# Production (fly.toml) overrides this with its own process command
CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
