#!/bin/sh

set -e

echo "==> Running database migrations..."
alembic upgrade head

echo "==> Database migrations completed."
echo "==> Starting application..."

exec "$@"