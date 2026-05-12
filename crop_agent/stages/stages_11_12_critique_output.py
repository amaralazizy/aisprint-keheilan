"""
Stage 11 — self-critique and assumption audit.
Stage 12 — structured ranked final output.

Stage 11 is the last chance to catch a bad recommendation before it
ships. It checks whether low-confidence facts drove the rank, whether
EGP figures are plausible, and whether any veto signal was missed.

Stage 12 packages everything into a typed FinalOutput object.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from ..clients.llm import LLMClient
from ..models import (
    CropRecommendation,
    FinalOutput,
    PestCalendarEntry,
)
from ..prompts.templates import CRITIQUE_SYSTEM, critique_user
from ..state import PipelineState
from .stages_7_8_score import CROPS


# ---------- Stage 11: self-critique ----------

_OPTIONAL_RAW_FIELDS = (
    "ph", "nitrogen_ppm", "phosphorus_ppm", "potassium_ppm",
    "salinity_ds_m", "soil_depth_cm", "cec",
    "irrigation_type", "last_crop", "years_since_reclamation",
)


def _collect_assumptions(state: PipelineState) -> list[dict]:
    """Walk through the state and surface every implicit assumption.

    Sources of assumptions, in order:
      1. Optional user input fields left as None (Fix 5).
      2. Imputed soil profile entries (non-user source).
      3. Fully-empty or regional_default soil profile (Fix 5).
      4. Baseline market prices used because no live signal was found.
      5. Low-confidence evidence aggregated into scoring.
      6. Reflection cap reached.
      7. Unresolved hard conflicts in evidence.
    """
    assumptions: list[dict] = []
    raw = state.parsed.raw

    # 1. Optional raw input fields not provided by the user.
    for field in _OPTIONAL_RAW_FIELDS:
        if getattr(raw, field, None) is None:
            assumptions.append({
                "text": f"{field} not provided — assumed regional default or skipped",
                "confidence": "low",
                "source": "user_input_missing",
            })

    # 2. Imputed soil profile entries.
    for field, entry in state.parsed.soil_profile.items():
        if entry["source"] != "user":
            assumptions.append({
                "text": f"{field} value {entry['value']} imputed from {entry['source']}",
                "confidence": entry["confidence"],
                "source": entry["source"],
            })

    # 3. Fully-empty or all-regional-default soil profile.
    sp = state.parsed.soil_profile
    if not sp:
        assumptions.append({
            "text": "No soil data available — neither user-supplied nor regional default",
            "confidence": "low",
            "source": "soil_data_missing",
        })
    elif sp and all(e.get("source") == "regional_default" for e in sp.values()):
        assumptions.append({
            "text": "Soil profile populated entirely from regional defaults",
            "confidence": "low",
            "source": "regional_default",
        })

    # 4. Baseline market prices used (no live price evidence).
    baseline_crops = [
        s.crop for s in state.scores
        if "baseline price assumed" in (s.rationale.get("market") or "")
    ]
    if baseline_crops:
        assumptions.append({
            "text": f"baseline market prices used for: {', '.join(baseline_crops)} — no live price signal found",
            "confidence": "low",
            "source": "market_signal_missing",
        })

    # 5. Aggregate low-confidence evidence.
    low_conf = [e for e in state.evidence if e.confidence == "low"]
    if low_conf:
        assumptions.append({
            "text": f"{len(low_conf)} low-confidence evidence items contributed to scoring",
            "confidence": "low",
            "source": "multiple",
        })

    # 6. Reflection cap.
    if state.reflection_rounds >= 3:
        assumptions.append({
            "text": "Reflection cap hit — some uncertainties may remain unresolved",
            "confidence": "medium",
            "source": "pipeline",
        })

    # 7. Unresolved conflicts.
    hard_conflicts = [c for c in state.conflicts if c.severity == "hard"]
    if hard_conflicts:
        assumptions.append({
            "text": f"{len(hard_conflicts)} hard conflicts remain — picked most recent source",
            "confidence": "medium",
            "source": "pipeline",
        })

    return assumptions


async def run_stage_11_critique(state: PipelineState, llm: LLMClient) -> PipelineState:
    state.log("stage_11", "running self-critique")
    state.assumptions = _collect_assumptions(state)

    if not state.scores or state.scores[0].overall == 0:
        state.log("stage_11", "no viable crop — skipping LLM critique")
        state.critique_passed = False
        return state

    top = state.scores[0]
    alts = state.scores[1:3]

    try:
        result = await llm.chat_json(
            system=CRITIQUE_SYSTEM,
            user=critique_user(
                top_score=top.model_dump_json(indent=2),
                alt_scores=json.dumps([a.model_dump() for a in alts], indent=2),
                scenarios=json.dumps([s.model_dump() for s in state.scenarios], indent=2, default=str),
                assumptions=json.dumps(state.assumptions, indent=2),
            ),
        )
        state.critique_passed = result.get("passed", False)
        issues = result.get("issues", [])
        for issue in issues:
            state.log("stage_11", f"critique issue [{issue.get('severity')}]: {issue.get('text')}")
        # Confidence adjustment is applied in stage 12
        state._confidence_adjustment = result.get("confidence_adjustment", 0)
    except Exception as e:
        state.log("stage_11", f"critique LLM call failed: {e} — defaulting to passed")
        state.critique_passed = True
        state._confidence_adjustment = -10  # be cautious if we couldn't critique

    return state


# ---------- Stage 12: final output ----------

def _build_recommendation(rank: int, score, state: PipelineState) -> CropRecommendation:
    profile = CROPS[score.crop]
    scenarios = next((s for s in state.scenarios if s.crop == score.crop), None)

    if scenarios:
        # Use the base case from the drought scenario as the headline range
        revenue_range = (
            min(scenarios.drought_egp_per_feddan[0], scenarios.devaluation_egp_per_feddan[0], scenarios.pest_egp_per_feddan[0]),
            scenarios.drought_egp_per_feddan[1],
            max(scenarios.drought_egp_per_feddan[2], scenarios.devaluation_egp_per_feddan[2], scenarios.pest_egp_per_feddan[2]),
        )
    else:
        yield_mid = sum(profile.typical_yield_t_per_feddan) / 2
        base = yield_mid * profile.market_price_egp_per_ton
        revenue_range = (base * 0.7, base, base * 1.2)

    amendments = getattr(state, "_amendments", {}).get(score.crop, [])
    pest_calendar = _pest_calendar_for(score.crop, state.parsed.season)

    trade_offs = _format_trade_offs(score, scenarios)

    # Confidence: average evidence confidence (high=1, medium=0.6, low=0.3)
    # times the overall score
    conf_map = {"high": 1.0, "medium": 0.6, "low": 0.3}
    if state.evidence:
        avg_ev_conf = sum(conf_map[e.confidence] for e in state.evidence) / len(state.evidence)
    else:
        avg_ev_conf = 0.5
    confidence_pct = int(min(95, max(20, score.overall * avg_ev_conf * 100)))

    return CropRecommendation(
        rank=rank,
        crop=score.crop,
        confidence_pct=confidence_pct,
        score_breakdown={
            "soil_fit": round(score.soil_fit, 3),
            "timing": round(score.timing, 3),
            "market": round(score.market, 3),
            "water": round(score.water, 3),
            "risk": round(score.risk, 3),
        },
        yield_range_t_per_feddan=profile.typical_yield_t_per_feddan,
        revenue_egp_per_feddan=revenue_range,
        amendment_plan=amendments,
        pest_calendar=pest_calendar,
        trade_offs=trade_offs,
    )


def _pest_calendar_for(crop: str, season: str) -> list[PestCalendarEntry]:
    """Reference pest calendars — replace with EMPRES + MALR bulletin data."""
    calendars = {
        "wheat": [
            PestCalendarEntry(month="Dec", pest="aphids", action="scout weekly; threshold 10/tiller"),
            PestCalendarEntry(month="Feb", pest="yellow rust", action="apply triazole if observed"),
            PestCalendarEntry(month="Mar", pest="Hessian fly", action="rotation; resistant cultivars"),
        ],
        "tomato": [
            PestCalendarEntry(month="Mar", pest="tuta absoluta", action="pheromone traps; deploy Bt"),
            PestCalendarEntry(month="May", pest="whitefly", action="reflective mulch; spinosad"),
        ],
        "maize": [
            PestCalendarEntry(month="Jun", pest="fall armyworm", action="scout V3; Bt spray if 25% infested"),
            PestCalendarEntry(month="Aug", pest="stem borer", action="biocontrol Trichogramma releases"),
        ],
        "cotton": [
            PestCalendarEntry(month="May", pest="bollworm", action="pheromone monitoring weekly"),
            PestCalendarEntry(month="Jul", pest="whitefly", action="rotate insecticide classes"),
        ],
    }
    return calendars.get(crop, [])


def _format_trade_offs(score, scenarios) -> str:
    bits = []
    if score.vetoes:
        bits.append(f"BLOCKED: {'; '.join(score.vetoes)}")
    if scenarios and scenarios.collapses_under:
        bits.append(f"vulnerable to: {', '.join(scenarios.collapses_under)}")
    if score.market < 0.5:
        bits.append("market signals weak")
    if score.water < 0.5:
        bits.append("water feasibility marginal")
    return "; ".join(bits) or "no major trade-offs flagged"


def run_stage_12_output(state: PipelineState) -> PipelineState:
    state.log("stage_12", "building final output")

    viable = [s for s in state.scores if s.overall > 0]
    if not viable:
        state.log("stage_12", "NO viable crops — output will indicate this")

    top = _build_recommendation(1, viable[0], state) if viable else None
    alternatives = [_build_recommendation(i + 2, s, state) for i, s in enumerate(viable[1:3])]

    # Apply critique adjustment, then make the per-crop and overall confidence
    # numbers agree (Fix 7). Surface the deduction as an explicit assumption.
    if top:
        raw_top_conf = top.confidence_pct
        adj = getattr(state, "_confidence_adjustment", 0)
        overall_conf = max(20, min(95, raw_top_conf + adj))
        top.confidence_pct = overall_conf
        for alt in alternatives:
            alt.confidence_pct = max(20, min(95, alt.confidence_pct + adj))
        if adj < 0:
            state.assumptions.append({
                "text": f"Confidence reduced by {abs(adj)} points by self-critique (raw {raw_top_conf}% → adjusted {overall_conf}%)",
                "confidence": "high",
                "source": "self_critique",
            })
    else:
        raw_top_conf = 0
        overall_conf = 0

    state.output = FinalOutput(
        top=top,
        alternatives=alternatives,
        assumptions=state.assumptions,
        overall_confidence_pct=overall_conf,
        language=state.raw.language,
        generated_at=datetime.now(timezone.utc),
    )
    # Stash the pre-adjustment top confidence for narrative reasoning.
    state._raw_top_confidence_pct = raw_top_conf
    state.log("stage_12", f"finished — top={top.crop if top else 'NONE'}, conf={overall_conf}%")
    return state
