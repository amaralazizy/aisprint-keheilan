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
    # We removed 'goal' from RawInput, defaulting to balanced 'profit' weights
    weights = _adjust_weights_for_context(WEIGHT_PRESETS["profit"], state)

    state.log("stage_9", f"weights: {weights}")

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

    # We only have one target crop now, but sorting doesn't hurt.
    state.scores.sort(key=lambda s: s.overall, reverse=True)
    return state


def run_stage_10_scenarios(state: PipelineState, top_n: int = 1) -> PipelineState:
    """Stress-test the target crop against three shocks."""
    state.log("stage_10", "running scenario simulations")
    scenarios: list[ScenarioOutcome] = []

    for score in state.scores[:top_n]:
        crop_name = score.crop
        
        # If crop is unknown, use a generic baseline yield and price
        if crop_name in CROPS:
            profile = CROPS[crop_name]
            yield_mid = sum(profile.typical_yield_t_per_feddan) / 2
            base_rev = yield_mid * profile.market_price_egp_per_ton
            water_need = profile.water_need_mm
        else:
            yield_mid = 3.0
            base_rev = 30000.0
            water_need = 600

        # Shock multipliers — (pessimistic, base, optimistic) effect on revenue
        drought_mult = (0.40, 0.65, 0.85) if water_need > 700 else (0.70, 0.85, 0.95)
        
        # Devaluation
        is_export = crop_name in ("cotton", "potato", "onion")
        deval_mult = (0.95, 1.10, 1.25) if is_export else (0.75, 0.85, 0.95)
        
        # Pest
        from .stages_7_8_score import pest_alert_for
        ev_text = " ".join(e.fact.lower() for e in state.evidence)
        in_alert = pest_alert_for(crop_name, ev_text) is not None
        pest_mult = (0.30, 0.55, 0.80) if in_alert else (0.70, 0.85, 0.95)

        outcome = ScenarioOutcome(
            crop=crop_name,
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
