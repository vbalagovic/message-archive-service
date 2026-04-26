#!/usr/bin/env bash
# Run DB migrations, then exec into the requested command (uvicorn by default).
set -euo pipefail

echo "[entrypoint] running database migrations..."
alembic upgrade head

echo "[entrypoint] starting: $*"
exec "$@"
