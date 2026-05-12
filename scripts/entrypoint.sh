#!/usr/bin/env bash
set -euo pipefail

# Seed demo data on first boot (idempotent — skips if rows exist).
python -m model1_land.seed || echo "seed step failed (continuing anyway)"

# Bind to Fly's injected $PORT (defaults to 8080 locally).
exec uvicorn model1_land.main:app --host 0.0.0.0 --port "${PORT:-8080}"
