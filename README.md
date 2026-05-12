# aisprint-keheilan

Keheilan AISPRINT — AI-fractional agriculture platform. Monorepo managed
with [uv workspaces](https://docs.astral.sh/uv/concepts/workspaces/).

## Models

| Package | Role | Description |
|---|---|---|
| `packages/crop_agent` | **Model 2 — Farm Operations** | Agentic crop-recommendation pipeline (12 stages, OpenRouter LLMs, regional soil defaults, pest alerts, self-critique). |
| `packages/model1_land` | **Model 1 — Fractional Land** | FastAPI app: parcels, rule-based risk tiers, leasing, investor shares. No satellite layer yet. |

Model 3 (Hybrid) and the Investment Concierge will land as additional
workspace members.

## Setup

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
# install uv if needed
curl -LsSf https://astral.sh/uv/install.sh | sh

git clone https://github.com/amaralazizy/aisprint-keheilan.git
cd aisprint-keheilan

uv sync --all-packages              # creates .venv, installs every workspace member
cp .env.example .env                # add OPENROUTER_API_KEY for Model 2 (optional for Model 1)
```

## Run

### Model 1 — Fractional Land (FastAPI)

```bash
uv run python -m model1_land.seed                    # seed demo parcels
uv run uvicorn model1_land.main:app --reload         # http://localhost:8000
```

Endpoints:
- `GET /` — parcels list with risk-tier filter
- `GET /parcels/{id}` — detail + invest / lease forms
- `POST /parcels/{id}/invest|lease|retier`
- `GET /api/parcels` — JSON

### Model 2 — Crop Agent

```bash
uv run python -m crop_agent.run             # Sharqia winter smallholder
uv run python -m crop_agent.run minya       # water-stressed farmer
uv run python -m crop_agent.run salinity    # saline plot
```

Outputs saved to `packages/crop_agent/crop_agent/outputs/<sample>_<timestamp>.json`.

## Tests

```bash
uv run pytest                          # runs every package's tests, offline
```

## Workspace layout

```
aisprint-keheilan/
├── pyproject.toml                ← workspace root + dev tools
├── uv.lock                       ← single lockfile, all packages
└── packages/
    ├── crop_agent/
    │   ├── pyproject.toml        ← Model 2 deps (openai, httpx, pydantic, ...)
    │   └── crop_agent/           ← module
    │       ├── pipeline.py, run.py, config.py, state.py, models.py
    │       ├── clients/  prompts/  stages/  tests/  outputs/
    └── model1_land/
        ├── pyproject.toml        ← Model 1 deps (fastapi, sqlmodel, jinja2, ...)
        └── model1_land/          ← module
            ├── main.py, db.py, models.py, risk.py, seed.py
            └── templates/
```

## Adding a new package

```bash
mkdir -p packages/<name>/<name>
touch packages/<name>/<name>/__init__.py
# create packages/<name>/pyproject.toml with [project] name = "<name>"
uv sync --all-packages
```

To depend on another workspace member, add it to that package's
`dependencies` — uv resolves it locally via the root `[tool.uv.sources]`.

## Model 2 configuration

Knobs live in [`packages/crop_agent/crop_agent/config.py`](packages/crop_agent/crop_agent/config.py):

| Setting | Default | Override via |
|---|---|---|
| Reasoner model | `openai/gpt-4o-mini` | `REASONER_MODEL` env var |
| Worker model | `meta-llama/llama-3.1-8b-instruct` | `WORKER_MODEL` env var |
| OpenRouter base URL | `https://openrouter.ai/api/v1` | `LLM_BASE_URL` env var |
| Reflection rounds | 1 | edit `max_reflection_rounds` |
| Parallel search burst | 3 | edit `parallel_search_limit` |
