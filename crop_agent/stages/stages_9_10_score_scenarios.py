"""
Stage 9 — adaptive weighted scoring.
Stage 10 — scenario simulation (drought / EGP devaluation / pest outbreak).

Stage 9 applies farmer-goal-conditioned weights to the dimension scores
from Stages 7+8 and produces an overall ranking.

Stage 10 stress-tests the top candidates against three shocks and flags
crops that collapse under any single one.
"""
from __future__ import annotations

from ..config import WEIGHT_PRESETS
from ..models import ScenarioOutcome
from ..state import PipelineState
from .stages_7_8_score import CROPS


def _adjust_weights_for_context(weights: dict, state: PipelineState) -> dict:
    """
    Context-aware weight shifts on top of the goal preset.
    Worth running explicit examples through this in your tests — these
    shifts are where the recommendation can change without any new data.
    """
    adjusted = dict(weights)
    gov = state.parsed.governorate

    # Water-scarce governorates: water feasibility dominates regardless of goal
    if gov in ("Minya", "Asyut", "Aswan", "Sohag", "Qena", "Luxor"):
        ev_text = " ".join(e.fact.lower() for e in state.evidence)
        if "gerd" in ev_text or "low nile" in ev_text or "drought" in ev_text:
            adjusted["water"] += 0.10
            # Renormalise — keep weights summing to 1
            total = sum(adjusted.values())
            adjusted = {k: v / total for k, v in adjusted.items()}

    # Low budget: amendment cost matters more — already baked into soil_fit
    # through the amendment-cost penalty, but boost soil weight slightly
    if state.parsed.raw.budget_egp < 10000:
        adjusted["soil_fit"] += 0.05
        total = sum(adjusted.values())
        adjusted = {k: v / total for k, v in adjusted.items()}

    return adjusted


def run_stage_9_overall_score(state: PipelineState) -> PipelineState:
    state.log("stage_9", "applying weighted scoring")
    goal = state.parsed.raw.goal.value
    weights = _adjust_weights_for_context(WEIGHT_PRESETS[goal], state)

    state.log("stage_9", f"weights for goal={goal}: {weights}")

    for score in state.scores:
        # If any veto, overall = 0
        if score.vetoes:
            score.overall = 0.0
            continue
        score.overall = (
            weights["soil_fit"] * score.soil_fit
            + weights["timing"] * score.timing
            + weights["market"] * score.market
            + weights["water"] * score.water
            + weights["risk"] * score.risk
        )

    state.scores.sort(key=lambda s: s.overall, reverse=True)
    top_3 = [s.crop for s in state.scores[:3] if s.overall > 0]
    state.log("stage_9", f"top 3: {top_3}")
    return state


def run_stage_10_scenarios(state: PipelineState, top_n: int = 3) -> PipelineState:
    """
    Stress-test top crops against three shocks. Each yields a
    (pessimistic, base, optimistic) revenue range in EGP/feddan.

    The constants here are illustrative — replace with empirical data
    once you have real production stats for your target governorates.
    """
    state.log("stage_10", "running scenario simulations")
    scenarios: list[ScenarioOutcome] = []

    for score in state.scores[:top_n]:
        if score.overall == 0:
            continue
        profile = CROPS[score.crop]
        yield_mid = sum(profile.typical_yield_t_per_feddan) / 2
        base_rev = yield_mid * profile.market_price_egp_per_ton

        # Shock multipliers — (pessimistic, base, optimistic) effect on revenue
        drought_mult = (0.40, 0.65, 0.85) if profile.water_need_mm > 700 else (0.70, 0.85, 0.95)
        # Devaluation: helps export crops, hurts import-cost-heavy
        is_export = profile.name in ("cotton", "potato", "onion")
        deval_mult = (0.95, 1.10, 1.25) if is_export else (0.75, 0.85, 0.95)
        # Pest: same crop-specific keyword logic as score_market_and_risk (Fix 3).
        # Avoids the old bug where "tomato" had to appear literally in alerts
        # that actually said "Tuta absoluta".
        from .stages_7_8_score import pest_alert_for
        ev_text = " ".join(e.fact.lower() for e in state.evidence)
        in_alert = pest_alert_for(profile.name, ev_text) is not None
        pest_mult = (0.30, 0.55, 0.80) if in_alert else (0.70, 0.85, 0.95)

        outcome = ScenarioOutcome(
            crop=profile.name,
            drought_egp_per_feddan=tuple(base_rev * m for m in drought_mult),
            devaluation_egp_per_feddan=tuple(base_rev * m for m in deval_mult),
            pest_egp_per_feddan=tuple(base_rev * m for m in pest_mult),
        )

        collapses = []
        if outcome.drought_egp_per_feddan[1] < 0.5 * base_rev:
            collapses.append("drought")
        if outcome.devaluation_egp_per_feddan[1] < 0.5 * base_rev:
            collapses.append("devaluation")
        if outcome.pest_egp_per_feddan[1] < 0.5 * base_rev:
            collapses.append("pest")
        outcome.collapses_under = collapses

        scenarios.append(outcome)

    state.scenarios = scenarios
    state.log("stage_10", f"simulated {len(scenarios)} crops; collapses: {[(s.crop, s.collapses_under) for s in scenarios]}")
    return state
