#!/bin/sh

set -e

# ICE_RUN_MIGRATIONS=false → skip migrate+seed (UAT/prod on Cloud Run: the CD
# pipeline owns `alembic upgrade head` as an explicit deploy step). Unset/true
# preserves the historical dev behavior (migrate + conditional seed on boot).
if [ "${ICE_RUN_MIGRATIONS:-true}" = "false" ]; then
  echo "==> ICE_RUN_MIGRATIONS=false — skipping migrations and seed (CD owns them)."
else
  echo "==> Running database migrations..."
  alembic upgrade head

  echo "==> Database migrations completed."

  # Demo data is gated inside app/seed.py — this is a no-op unless
  # ICE_SEED_DEMO is truthy (1/true/yes). Intentionally unconditional here so
  # the flag has a single source of truth (Render Free has no pre-deploy hook,
  # so everything must happen on container startup).
  echo "==> Loading demo seed (no-op unless ICE_SEED_DEMO=true)..."
  python -m app.seed
fi

# ICE_RUN_MIGRATIONS_ONLY=true → migrate (above) then exit without starting a
# server. Used by the CD migration job (gcloud run jobs), which overrides CMD
# but not ENTRYPOINT — the entrypoint does the migration work and stops.
if [ "${ICE_RUN_MIGRATIONS_ONLY:-false}" = "true" ]; then
  echo "==> ICE_RUN_MIGRATIONS_ONLY=true — migration job done, exiting."
  exit 0
fi

echo "==> Starting application..."

exec "$@"