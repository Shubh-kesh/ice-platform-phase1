# ---- Stage 1: builder — installs deps into a venv, nothing else ----
FROM python:3.12-slim AS builder

WORKDIR /build

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

RUN python -m venv /venv
ENV PATH="/venv/bin:$PATH"

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# ---- Stage 2: runtime — slim image, only the venv + app code, non-root ----
FROM python:3.12-slim AS runtime

# libpq5 is the runtime lib for psycopg2 (used by Alembic); asyncpg is pure Python.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd -r ice && useradd -r -g ice -d /app -s /sbin/nologin ice

COPY --from=builder /venv /venv
ENV PATH="/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app
COPY --chown=ice:ice . .

USER ice

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Cloud Run injects $PORT; default to 8080 for local docker-compose use.
# Gunicorn manages uvicorn workers — resilient to a single worker crashing.
CMD exec gunicorn app.main:app \
    --workers 4 \
    --worker-class uvicorn.workers.UvicornWorker \
    --bind 0.0.0.0:${PORT:-8080} \
    --timeout 60 \
    --access-logfile - \
    --error-logfile -
