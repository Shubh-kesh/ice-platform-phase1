#!/bin/sh

set -e

echo "==> Running database migrations..."
alembic upgrade head

echo "==> Database migrations completed."

# Demo data is gated inside app/seed.py — this is a no-op unless
# ICE_SEED_DEMO is truthy (1/true/yes). Intentionally unconditional here so
# the flag has a single source of truth (Render Free has no pre-deploy hook,
# so everything must happen on container startup).
echo "==> Loading demo seed (no-op unless ICE_SEED_DEMO=true)..."
python -m app.seed

echo "==> Starting application..."

exec "$@"