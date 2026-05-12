"""
Pipeline orchestrator. Top-level entry point that runs every stage in
order. Keep this file BORING — it should be obvious what runs when.
Stage-specific logic lives in the stage modules, not here.

Usage:
    from crop_agent.pipeline import run_pipeline
    output = await run_pipeline(raw_input)
"""
from __future__ import annotations

import logging

from .clients.llm import LLMClient
from .clients.search import SearchClient, StubSearchClient
from .clients.soil_weather import NASAPowerClient, SoilGridsClient
from .models import RawInput
from .stages.stage_2_parse import run_stage_2_parse
from .stages.stage_3_plan import run_stage_3_plan
from .stages.stage_4_5_search_extract import run_stage_4_5_search_and_extract
from .stages.stage_6_reflect import run_stage_6_reflect
from .stages.stages_7_8_score import run_stages_7_8_score_dimensions
from .stages.stages_9_10_score_scenarios import (
    run_stage_9_overall_score,
    run_stage_10_scenarios,
)
from .stages.stages_11_12_critique_output import (
    run_stage_11_critique,
    run_stage_12_output,
)
from .state import PipelineState

logger = logging.getLogger(__name__)


async def run_pipeline(
    raw: RawInput,
    *,
    reasoner: LLMClient | None = None,
    worker: LLMClient | None = None,
    llm: LLMClient | None = None,  # back-compat: if set, used for both roles
    search: SearchClient | None = None,
    soilgrids: SoilGridsClient | None = None,
    power: NASAPowerClient | None = None,
) -> PipelineState:
    """
    Run the full pipeline. Two LLMs by role:
      reasoner — decisions, planning, reflection, critique
      worker   — mechanical extraction (cheap, high-throughput)

    Pass `llm=` to use one model for both (legacy / single-model testing).
    """
    from .config import CONFIG
    if llm is not None:
        reasoner = reasoner or llm
        worker = worker or llm
    reasoner = reasoner or LLMClient(model=CONFIG.reasoner_model)
    worker = worker or LLMClient(model=CONFIG.worker_model)
    search = search or StubSearchClient()
    soilgrids = soilgrids or SoilGridsClient()
    power = power or NASAPowerClient()

    state = PipelineState(raw=raw)
    state.log("pipeline", f"starting at lat={raw.latitude}, lon={raw.longitude}")
    state.log("pipeline", f"reasoner={reasoner.model}, worker={worker.model}")

    # Stage 2: parse + anomalies + soil fill (no LLM)
    await run_stage_2_parse(state, soilgrids=soilgrids)

    # Stage 3: dynamic query planning — REASONER
    await run_stage_3_plan(state, reasoner)

    # Stage 4 + 5: parallel search + evidence extraction — WORKER
    await run_stage_4_5_search_and_extract(state, search, worker)

    # Stage 6: reflective reasoning loop — REASONER drives, WORKER extracts
    await run_stage_6_reflect(state, reasoner, search, worker=worker)

    # Stage 7 + 8: per-crop dimension scores (no LLM)
    await run_stages_7_8_score_dimensions(state, power=power)

    # Stage 9: weighted overall scores
    run_stage_9_overall_score(state)

    # Stage 10: scenario stress tests
    run_stage_10_scenarios(state)

    # Stage 11: self-critique — REASONER
    await run_stage_11_critique(state, reasoner)

    # Stage 12: structured output
    run_stage_12_output(state)

    state.log("pipeline", "finished")
    return state
