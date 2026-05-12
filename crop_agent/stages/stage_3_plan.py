"""
Stage 3 — dynamic query planner.

The model writes its own queries based on parsed inputs and anomalies.
NOT a fixed list. Two farmers with different governorates or anomalies
get different queries.

This stage produces N PlannedQuery objects, each tagged with category,
language, and rationale. The rationale field is critical for debugging
— when the agent searches something weird, the rationale tells you why.
"""
from __future__ import annotations

from ..clients.llm import LLMClient
from ..config import CONFIG
from ..models import PlannedQuery
from ..prompts.templates import PLANNER_SYSTEM, planner_user
from ..state import PipelineState


async def run_stage_3_plan(state: PipelineState, llm: LLMClient) -> PipelineState:
    state.log("stage_3", "planning queries")
    assert state.parsed is not None, "stage 2 must run before stage 3"

    raw_queries = await llm.chat_json(
        system=PLANNER_SYSTEM,
        user=planner_user(state.parsed),
    )

    # Validate + coerce
    queries: list[PlannedQuery] = []
    for q in raw_queries[: CONFIG.max_initial_queries]:
        try:
            queries.append(PlannedQuery(**q))
        except Exception as e:
            state.log("stage_3", f"dropped malformed query: {e}")

    # Ensure minimum coverage per category — if the model under-represents
    # a category, log it. We could also retry, but logging is cheaper for
    # debugging the first time you see this happen.
    categories = {q.category for q in queries}
    for needed in ("fixed_knowledge", "live_signal", "arabic_ministry"):
        if needed not in categories:
            state.log("stage_3", f"WARNING: no query in category {needed}")

    state.queries.extend(queries)
    state.log("stage_3", f"planned {len(queries)} queries across {len(categories)} categories")
    return state
