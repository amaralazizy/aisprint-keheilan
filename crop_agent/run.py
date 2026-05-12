"""
Local runner. Loads .env, runs the pipeline on a sample farmer, prints output.

Usage (from the repo root, i.e. the parent of the inner crop_agent/ package):
    python -m crop_agent.run                  # sample_sharqia_winter
    python -m crop_agent.run minya            # sample_minya_water_stress
    python -m crop_agent.run salinity         # sample_salinity_blocked
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import os

from crop_agent.clients.llm import LLMClient
from crop_agent.clients.search import StubSearchClient, TavilySearchClient
from crop_agent.config import CONFIG
from crop_agent.pipeline import run_pipeline
from crop_agent.tests.fixtures import (
    sample_minya_water_stress,
    sample_salinity_blocked,
    sample_sharqia_winter,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

SAMPLES = {
    "sharqia": sample_sharqia_winter,
    "minya": sample_minya_water_stress,
    "salinity": sample_salinity_blocked,
}


async def main() -> None:
    key = sys.argv[1] if len(sys.argv) > 1 else "sharqia"
    raw = SAMPLES[key]()
    reasoner = LLMClient(model=CONFIG.reasoner_model)
    worker = LLMClient(model=CONFIG.worker_model)
    print(f"Reasoner: {reasoner.model}\nWorker:   {worker.model}")

    if os.getenv("SEARCH_API_KEY"):
        search = TavilySearchClient()
        print("Search:   Tavily (real web search)\n")
    else:
        search = StubSearchClient()
        print(
            "Search:   StubSearchClient (offline canned data) — "
            "set SEARCH_API_KEY=tvly-... in .env for real search.\n"
        )

    state = await run_pipeline(raw, reasoner=reasoner, worker=worker, search=search)

    narrative = await _write_narrative(reasoner, state)

    def _dump(obj):
        if hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")
        return obj

    payload = state.output.model_dump(mode="json")
    justification = {
        "narrative": narrative,
        "parsed_input": _dump(state.parsed) if state.parsed else None,
        "planned_queries": [_dump(q) for q in state.queries],
        "evidence": [_dump(e) for e in state.evidence],
        "conflicts": [_dump(c) for c in state.conflicts],
        "scores": [_dump(s) for s in state.scores],
        "scenarios": [_dump(s) for s in state.scenarios],
        "assumptions": state.assumptions,
        "reflection_rounds": state.reflection_rounds,
        "reflection_log": state.reflection_log,
        "critique_passed": state.critique_passed,
        "trace": state.trace,
    }
    full = {"output": payload, "justification": justification}
    rendered = json.dumps(full, indent=2, ensure_ascii=False, default=str)

    out_dir = Path(__file__).parent / "outputs"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{key}_{stamp}.json"
    out_path.write_text(rendered, encoding="utf-8")

    print("\n===== FINAL OUTPUT =====")
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    print("\n===== JUSTIFICATION =====")
    print(narrative)
    print(f"\nSaved (output + justification): {out_path}")


async def _write_narrative(llm: LLMClient, state) -> str:
    """One LLM call: write per-crop natural-language reasoning.

    Uses overall_confidence_pct as the single source of truth (Fix 7) so the
    narrative agrees with the metadata. If the critique reduced confidence by
    more than 10 points, the prompt asks the model to explain why.
    """
    out = state.output
    crops = [out.top, *out.alternatives]
    overall_conf = out.overall_confidence_pct
    raw_top = getattr(state, "_raw_top_confidence_pct", overall_conf)
    reduction = max(0, raw_top - overall_conf)

    crop_blocks = []
    for c in crops:
        crop_blocks.append(
            f"Crop: {c.crop} (rank {c.rank})\n"
            f"  Score breakdown: {c.score_breakdown}\n"
            f"  Rationales: {state.scores[c.rank - 1].rationale if c.rank - 1 < len(state.scores) else {}}\n"
            f"  Yield t/feddan: {c.yield_range_t_per_feddan}\n"
            f"  Revenue EGP/feddan: {c.revenue_egp_per_feddan}"
        )

    evidence_lines = [
        f"- {e.fact} (source: {e.source_name}, confidence: {e.confidence})"
        for e in state.evidence[:25]
    ]

    confidence_block = f"Overall recommendation confidence: {overall_conf}%."
    if reduction > 10:
        confidence_block += (
            f" The self-critique reduced confidence from {raw_top}% to {overall_conf}%"
            f" ({reduction} points). Explain to the farmer in one sentence why"
            " the model is less sure (e.g. missing soil data, weak market evidence,"
            " unresolved conflicts, regional defaults used)."
        )

    user_prompt = (
        f"Farmer context:\n"
        f"  location: lat={state.raw.latitude}, lon={state.raw.longitude}\n"
        f"  area: {state.raw.area_feddan} feddan\n"
        f"  water: {state.raw.water_source}\n"
        f"  soil: {state.raw.soil_type}\n"
        f"  budget: {state.raw.budget_egp} EGP\n"
        f"  start: {state.raw.start_date}, horizon: {state.raw.harvest_horizon_days} days\n"
        f"  goal: {state.raw.goal}\n\n"
        f"{confidence_block}\n\n"
        f"Recommended crops (already chosen by the scoring pipeline):\n"
        + "\n".join(crop_blocks)
        + "\n\nEvidence gathered during research:\n"
        + ("\n".join(evidence_lines) if evidence_lines else "(no external evidence collected)")
        + "\n\nWrite a clear, plain-language justification for the farmer. "
        "For EACH crop above, give 2-4 sentences explaining WHY it was chosen "
        "for this farmer's situation — reference soil fit, timing, water, market, "
        "and risk where relevant. Use the overall confidence number, not any "
        "per-crop number. End with one paragraph contrasting the top crop "
        "against the alternatives so the farmer understands the trade-offs."
    )

    return await llm.chat(
        system="You are an agronomist explaining a crop recommendation to a smallholder farmer in Egypt. Be concrete, avoid jargon, cite specific numbers from the score breakdown when useful.",
        user=user_prompt,
    )


if __name__ == "__main__":
    asyncio.run(main())
