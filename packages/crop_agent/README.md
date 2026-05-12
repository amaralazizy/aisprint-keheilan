# Egypt Crop Recommender — Agentic Pipeline

A modular, debuggable implementation of the dynamic crop recommendation pipeline.

## Architecture

```
crop_agent/
├── models.py              # Pydantic data models — every typed thing
├── state.py               # PipelineState — flows through every stage
├── config.py              # All tunable knobs (weights, caps, model name)
├── pipeline.py            # Top-level orchestrator (run_pipeline)
├── prompts/templates.py   # All LLM prompts in one file — grep here when debugging
├── clients/
│   ├── llm.py             # OpenRouter (OpenAI-compatible) wrapper
│   ├── search.py          # SearchClient protocol + Stub + Tavily impls
│   └── soil_weather.py    # SoilGrids + NASA POWER (free, no key)
├── stages/
│   ├── stage_2_parse.py
│   ├── stage_3_plan.py
│   ├── stage_4_5_search_extract.py
│   ├── stage_6_reflect.py
│   ├── stages_7_8_score.py
│   ├── stages_9_10_score_scenarios.py
│   └── stages_11_12_critique_output.py
└── tests/
    ├── fixtures.py
    └── test_stages.py
```

## Debugging philosophy

Three things make this pipeline easy to debug:

1. **Typed state, one object.** `PipelineState` carries everything. Pickle it
   between stages, inspect any prior stage's output. No hidden globals.
2. **One file for prompts.** When the agent does something weird, grep
   `prompts/templates.py`. No prompt strings buried in stage code.
3. **Stages are independent functions.** Each stage takes state and returns
   state. You can hand-build state, call `run_stage_9_overall_score(state)`,
   and inspect the result without running anything else.

Every stage logs to `state.trace` and `state.log("stage_x", "msg")`. Print
`state.trace` after a run to see the full execution trail.

## Quick start

```python
from datetime import date
from crop_agent.models import FarmerGoal, RawInput, WaterSource
from crop_agent.pipeline import run_pipeline
from crop_agent.clients.search import StubSearchClient

raw = RawInput(
    latitude=30.71, longitude=31.74,
    area_feddan=5.0,
    water_source=WaterSource.NILE_CANAL,
    soil_type="clay",
    budget_egp=25000,
    start_date=date(2026, 11, 15),
    harvest_horizon_days=180,
    goal=FarmerGoal.PROFIT,
)

# With real APIs:
state = await run_pipeline(raw)

# With stubs (no API keys needed, faster for dev):
state = await run_pipeline(raw, search=StubSearchClient())

print(state.output.model_dump_json(indent=2))
print("\n".join(state.trace))
```

## Running tests

```bash
pip install pytest pytest-asyncio pydantic openai python-dotenv httpx
pytest crop_agent/tests/test_stages.py -v
```

Tests don't need API keys — they use stub clients and hand-built state.

## Environment

```bash
export OPENROUTER_API_KEY=sk-or-...                            # required
export REASONER_MODEL=openai/gpt-4o-mini                       # decisions/planning/critique
export WORKER_MODEL=meta-llama/llama-3.1-8b-instruct           # cheap extraction
export SEARCH_API_KEY=tvly-...                                  # optional, Tavily
```

## Plugging in real data sources

The `SearchClient` protocol in `clients/search.py` is the seam. Implement
`search(query, language, max_results)` and return `SearchResult` objects.
Drop-in replacements for Tavily: Serper, Brave Search, your own scraper.

For Egypt-specific sources where there's no public API:
- MALR Arabic bulletins → scrape MALR's site (e.g. agr-egypt.gov.eg)
- USDA-FAS GAIN reports → scrape gain.fas.usda.gov
- EMPRES alerts → scrape FAO EMPRES portal
- MWRI Nile bulletins → mwri.gov.eg

Wrap each scraper in its own client and route queries by category in the
planner. The agent will write Arabic queries for the MALR cluster
automatically because `prompts/templates.py` tells it to.

## What's hard-coded vs. dynamic

| Hard-coded | Dynamic |
|---|---|
| Crop profiles (pH bands, GDD, water needs) | Which crops to consider for a given season |
| Weight presets per goal | Which signals are surfaced for THIS farmer |
| Veto rules (e.g. rice decree governorates) | Whether the veto applies based on resolved governorate |
| Reflection cap (3 rounds, 3 searches/round) | Whether reflection fires at all, and on what |
| Scenario shock multipliers | Which crops the scenarios run on |

Slow-changing agronomic knowledge is hard-coded — there's no value in
asking the model what pH wheat likes every time. Fast-changing policy,
prices, and outbreaks are agent-driven.

## Known limitations / TODO

- Conflict detector is keyword-based. Upgrade to embedding similarity for
  fact alignment.
- Pest calendar is a small lookup table — wire to EMPRES + MALR bulletins.
- Crop price baselines need monthly refresh from USDA-FAS GAIN reports.
- No memory across farmers yet — each run is stateless. A second pass
  could surface "similar farmers in your governorate chose X."
