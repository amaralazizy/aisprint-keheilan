"""
Stage 6 — reflective reasoning loop.

The model asks "what am I still uncertain about?" and either:
- fires up to 3 follow-up searches (calls Stage 4/5 with a smaller query set)
- returns to Stage 3 if it realises it missed a whole category
- commits and moves on

Hard ceiling: 3 rounds. Without this bound the agent can churn forever
on tangential uncertainties.
"""
from __future__ import annotations

from ..clients.llm import LLMClient
from ..clients.search import SearchClient
from ..config import CONFIG
from ..models import PlannedQuery
from ..prompts.templates import REFLECTION_SYSTEM, reflection_user
from ..state import PipelineState
from .stage_3_plan import run_stage_3_plan
from .stage_4_5_search_extract import run_stage_4_5_search_and_extract


def _summarise_evidence(state: PipelineState, max_items: int = 30) -> str:
    """Compact evidence summary for the reflection prompt."""
    lines = []
    for e in state.evidence[:max_items]:
        date = e.source_date.isoformat() if e.source_date else "?"
        lines.append(f"- [{e.confidence}] {e.fact} (src: {e.source_name[:60]}, {date})")
    if len(state.evidence) > max_items:
        lines.append(f"... and {len(state.evidence) - max_items} more")
    return "\n".join(lines) or "(none yet)"


def _summarise_conflicts(state: PipelineState) -> str:
    if not state.conflicts:
        return "(none)"
    return "\n".join(
        f"- {c.severity}: '{c.fact_a.fact}' = {c.fact_a.value} vs {c.fact_b.value}"
        for c in state.conflicts[:10]
    )


def _summarise_parsed(state: PipelineState) -> str:
    p = state.parsed
    return (
        f"governorate={p.governorate}, season={p.season}, "
        f"area={p.raw.area_feddan} feddan, goal={p.raw.goal.value}, "
        f"anomalies={[a.field for a in p.anomalies]}"
    )


async def run_stage_6_reflect(
    state: PipelineState,
    llm: LLMClient,
    search: SearchClient,
    *,
    worker: LLMClient | None = None,
) -> PipelineState:
    """
    Reflection loop. `llm` = reasoner (drives reflection + replan).
    `worker` = cheap model for follow-up evidence extraction; falls back to `llm`.
    """
    worker = worker or llm
    while state.reflection_rounds < CONFIG.max_reflection_rounds:
        round_num = state.reflection_rounds + 1
        state.log("stage_6", f"reflection round {round_num}")

        result = await llm.chat_json(
            system=REFLECTION_SYSTEM,
            user=reflection_user(
                _summarise_parsed(state),
                _summarise_evidence(state),
                _summarise_conflicts(state),
                round_num,
            ),
        )

        state.reflection_log.append({
            "round": round_num,
            "uncertainties": result.get("uncertainties", []),
            "follow_up_count": len(result.get("follow_up_queries", [])),
            "should_replan": result.get("should_replan", False),
        })

        # Case A: model wants to replan from scratch — go back to Stage 3
        if result.get("should_replan"):
            state.log("stage_6", "model requested replan — returning to stage 3")
            state.reflection_rounds += 1
            await run_stage_3_plan(state, llm)
            await run_stage_4_5_search_and_extract(state, search, worker, queries=state.queries[-CONFIG.max_initial_queries:])
            continue

        # Case B: targeted follow-up queries
        follow_ups_raw = result.get("follow_up_queries", [])[: CONFIG.max_searches_per_reflection]
        if not follow_ups_raw:
            state.log("stage_6", "no uncertainties — committing")
            break

        follow_ups: list[PlannedQuery] = []
        for q in follow_ups_raw:
            try:
                follow_ups.append(PlannedQuery(**q))
            except Exception as e:
                state.log("stage_6", f"dropped malformed follow-up: {e}")

        state.queries.extend(follow_ups)
        await run_stage_4_5_search_and_extract(state, search, worker, queries=follow_ups)
        state.reflection_rounds += 1

    state.log("stage_6", f"reflection finished after {state.reflection_rounds} rounds")
    return state
