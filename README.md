# aisprint-keheilan

Agentic crop recommendation pipeline for Egypt. 12 stages, hybrid model
split over OpenRouter (cheap worker for extraction, stronger reasoner
for decisions), regional soil defaults when measurements are missing,
crop-specific pest-alert detection, self-critique, and a
natural-language justification of the final recommendation.

Architecture details live in [`crop_agent/README.md`](crop_agent/README.md).

## Setup

Requires Python 3.10+.

```bash
git clone https://github.com/amaralazizy/aisprint-keheilan.git
cd aisprint-keheilan

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt

cp .env.example .env
# Edit .env — paste your OPENROUTER_API_KEY (https://openrouter.ai).
# SEARCH_API_KEY is optional; without it the pipeline uses canned stub data.
```

## Run the pipeline

```bash
python -m crop_agent.run             # sample: Sharqia winter smallholder
python -m crop_agent.run minya       # sample: Minya water-stressed farmer
python -m crop_agent.run salinity    # sample: highly-saline plot
```

Each run prints the final recommendation and a plain-language
justification, and saves the full output (with evidence, scores,
scenarios, and trace) to `crop_agent/outputs/<sample>_<timestamp>.json`.

## Tests

```bash
pytest crop_agent/tests/ -v
```

Tests run offline — no API keys needed.

## Configuration

All knobs are in [`crop_agent/config.py`](crop_agent/config.py):

| Setting | Default | Override via |
|---|---|---|
| Reasoner model | `openai/gpt-4o-mini` | `REASONER_MODEL` env var |
| Worker model | `meta-llama/llama-3.1-8b-instruct` | `WORKER_MODEL` env var |
| OpenRouter base URL | `https://openrouter.ai/api/v1` | `LLM_BASE_URL` env var |
| Reflection rounds | 1 | edit `max_reflection_rounds` |
| Parallel search burst | 3 | edit `parallel_search_limit` |

## What's where

```
aisprint-keheilan/
├── .env                          ← your API keys (gitignored)
├── .env.example
├── requirements.txt
└── crop_agent/                   ← Python package
    ├── run.py                    ← entry point
    ├── pipeline.py               ← orchestrator (12 stages)
    ├── config.py                 ← all tunable knobs
    ├── models.py                 ← Pydantic data models
    ├── state.py                  ← PipelineState flows through every stage
    ├── prompts/templates.py      ← every LLM prompt (grep here when debugging)
    ├── clients/                  ← LLM, search, soil + weather
    ├── stages/                   ← one file per stage
    └── tests/
```
