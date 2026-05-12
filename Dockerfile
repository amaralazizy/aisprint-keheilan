FROM python:3.12-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

WORKDIR /app

# System deps (none currently needed beyond Python).
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy workspace manifests first for cache
COPY pyproject.toml uv.lock ./
COPY packages/crop_agent/pyproject.toml packages/crop_agent/pyproject.toml
COPY packages/model1_land/pyproject.toml packages/model1_land/pyproject.toml

# Copy sources
COPY packages packages

# Sync workspace deps into /app/.venv
ENV UV_LINK_MODE=copy
RUN uv sync --all-packages --frozen --no-dev

ENV PATH="/app/.venv/bin:${PATH}"

# DATABASE_URL must be supplied by the host (Render → Neon connection string).
# Falls back to local SQLite file inside the container if missing.

# Entrypoint: seed (idempotent) then start uvicorn on $PORT.
COPY scripts/entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

EXPOSE 8080
CMD ["/entrypoint.sh"]
