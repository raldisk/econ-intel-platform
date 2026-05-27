#!/bin/sh
# entrypoint.sh — PH-Dashboard container startup
#
# Enforces the three-phase initialization contract:
#   1. Bootstrap  — create/validate DuckDB schema (write connection, once, pre-fork)
#   2. Validate   — lifespan hook confirms DB is complete inside each worker (read-only)
#   3. Serve      — uvicorn workers handle requests read-only
#
# This script runs as PID 1. It exits non-zero on any failure so the
# container orchestrator (Docker, Kubernetes) can restart or alert rather
# than serving a broken API silently.

set -e

echo "[entrypoint] Phase 1: DuckDB schema bootstrap"
python -m db.init
echo "[entrypoint] Bootstrap complete."

echo "[entrypoint] Phase 2+3: Starting uvicorn (lifespan will validate, then serve)"
exec uvicorn api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --workers "${UVICORN_WORKERS:-4}" \
    --log-level info
