"""
Stages 7 + 8 — deep soil reasoning, climate/timing fit, and live signal
integration. These compute the per-crop dimension scores that Stage 9
combines.

We hardcode crop knowledge (pH bands, GDD requirements, water needs)
because these are slow-changing reference facts. The live signals and
agronomic adjustments come from evidence gathered in earlier stages.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from ..clients.soil_weather import NASAPowerClient
from ..config import VETO_RULES
from ..models import AmendmentStep, CropScore
from ..state import PipelineState


# Reference crop profiles — slow-changing agronomic knowledge.
# Values are illustrative; replace with FAO/USDA crop water/agronomy tables.
@dataclass(frozen=True)
class CropProfile:
    name: str
    ph_optimal: tuple[float, float]
    ph_tolerable: tuple[float, float]
    gdd_required: float
    gdd_base_c: float
    water_need_mm: int
    salinity_tolerance_ds_m: float
    seasons: tuple[str, ...]
    typical_yield_t_per_feddan: tuple[float, float]
    market_price_egp_per_ton: float  # baseline — adjusted by live signals


CROPS = {
    "wheat":      CropProfile("wheat", (6.0, 7.5), (5.5, 8.5), 1800, 5.0, 450, 6.0, ("shitawi",),                (2.5, 3.8), 11000),
    "maize":      CropProfile("maize", (5.8, 7.0), (5.5, 8.0), 2400, 10.0, 600, 1.8, ("seifi", "nili"),          (3.0, 4.5), 8500),
    "rice":       CropProfile("rice",  (5.5, 7.0), (4.5, 8.0), 2900, 10.0, 1500, 3.0, ("seifi",),                (3.5, 4.5), 9000),
    "cotton":     CropProfile("cotton", (6.0, 7.5), (5.8, 8.0), 2200, 15.0, 800, 7.7, ("seifi",),                (1.0, 1.5), 28000),
    "tomato":     CropProfile("tomato", (6.0, 7.0), (5.5, 7.8), 1500, 10.0, 550, 2.5, ("shitawi", "seifi"),      (15.0, 25.0), 6000),
    "onion":      CropProfile("onion", (6.0, 7.0), (5.5, 7.8), 1600, 7.0, 450, 4.0, ("shitawi",),                (10.0, 16.0), 5500),
    "potato":     CropProfile("potato", (5.0, 6.5), (4.8, 7.2), 1500, 7.0, 500, 1.7, ("shitawi", "nili"),        (8.0, 14.0), 7000),
    "sugar_beet": CropProfile("sugar_beet", (6.5, 7.5), (6.0, 8.5), 2200, 5.0, 600, 7.0, ("shitawi",),           (20.0, 28.0), 1400),
    "alfalfa":    CropProfile("alfalfa", (6.5, 7.5), (6.0, 8.5), 2000, 5.0, 1200, 5.0, ("shitawi", "seifi"),     (8.0, 12.0), 4500),
    "barley":     CropProfile("barley", (6.0, 7.8), (5.5, 8.5), 1700, 5.0, 380, 8.0, ("shitawi",),               (2.0, 3.0), 6500),
}


# ---------- Stage 7a: soil suitability ----------

def score_soil_fit(profile: CropProfile, soil: dict) -> tuple[float, list[AmendmentStep], str]:
    """Returns (score 0-1, amendment plan, rationale).

    Data-completeness rules (Fix 2):
    - A relevant field absent entirely → multiply score by 0.5 (we don't know).
    - A field sourced from regional_default counts as half-present.
    - Final score is scaled by max(0.6, present_weight / M_relevant_fields).
    """
    amendments: list[AmendmentStep] = []
    score = 1.0
    rationale_bits = []

    # Track data completeness across the three soil dimensions the scoring uses.
    relevant_fields = ("ph", "salinity_ds_m", "cec")
    present_weight = 0.0
    for f in relevant_fields:
        entry = soil.get(f) or {}
        src = entry.get("source")
        if src in ("user", "SoilGrids 250m"):
            present_weight += 1.0
        elif src == "regional_default":
            present_weight += 0.5

    ph = soil.get("ph", {}).get("value")
    ph_source = soil.get("ph", {}).get("source")
    if ph is None:
        score *= 0.5
        rationale_bits.append("pH unknown — score reduced for uncertainty")
    elif ph_source == "regional_default":
        rationale_bits.append(f"pH {ph:.1f} from regional default (low confidence)")
    if ph is not None:
        opt_lo, opt_hi = profile.ph_optimal
        tol_lo, tol_hi = profile.ph_tolerable
        if opt_lo <= ph <= opt_hi:
            rationale_bits.append(f"pH {ph:.1f} in optimal band")
        elif tol_lo <= ph <= tol_hi:
            score *= 0.75
            rationale_bits.append(f"pH {ph:.1f} tolerable but not optimal")
            if ph < opt_lo:
                amendments.append(AmendmentStep(
                    action="apply agricultural lime 500 kg/feddan",
                    cost_egp=1500,
                    reason=f"raise pH from {ph:.1f} toward {opt_lo}",
                ))
            else:
                amendments.append(AmendmentStep(
                    action="apply elemental sulphur 200 kg/feddan",
                    cost_egp=2200,
                    reason=f"lower pH from {ph:.1f} toward {opt_hi}",
                ))
        else:
            score *= 0.3
            rationale_bits.append(f"pH {ph:.1f} outside tolerable range")

    salinity = soil.get("salinity_ds_m", {}).get("value")
    if salinity is None:
        score *= 0.5
        rationale_bits.append("salinity unknown — score reduced for uncertainty")
    if salinity is not None:
        if salinity > profile.salinity_tolerance_ds_m:
            score *= 0.4
            rationale_bits.append(f"salinity {salinity:.1f} dS/m exceeds tolerance {profile.salinity_tolerance_ds_m}")
            amendments.append(AmendmentStep(
                action="apply gypsum 2 t/feddan + leaching irrigation",
                cost_egp=3500,
                reason=f"reduce salinity from {salinity:.1f} dS/m",
            ))

    cec = soil.get("cec", {}).get("value")
    if cec is not None and cec < 10:
        score *= 0.85
        rationale_bits.append(f"low CEC {cec:.1f} — fertiliser leaches easily")
        amendments.append(AmendmentStep(
            action="apply compost 5 t/feddan",
            cost_egp=4000,
            reason="raise CEC and water-holding capacity",
        ))

    # Data-completeness scaling — penalise uncertain scores without zeroing
    completeness = max(0.6, present_weight / len(relevant_fields))
    if completeness < 1.0:
        rationale_bits.append(f"limited soil data — completeness {completeness:.2f}")
    score *= completeness

    if not rationale_bits:
        rationale_bits.append("scored on defaults only; no penalising factors detected")
    return max(0.0, min(1.0, score)), amendments, "; ".join(rationale_bits)


# ---------- Stage 7b: climate + timing ----------

async def score_timing(profile: CropProfile, state: PipelineState, power: NASAPowerClient | None) -> tuple[float, str]:
    """Returns (score 0-1, rationale)."""
    parsed = state.parsed
    score = 1.0
    rationale_bits = []

    # Season fit
    if parsed.season not in profile.seasons:
        score *= 0.3
        rationale_bits.append(f"season {parsed.season} not preferred ({profile.seasons})")
    else:
        rationale_bits.append(f"season {parsed.season} matches")

    # GDD check via NASA POWER (if available)
    if power:
        start = parsed.raw.start_date
        end = start + timedelta(days=parsed.raw.harvest_horizon_days)
        data = await power.query_daily(
            parsed.raw.latitude,
            parsed.raw.longitude,
            start.strftime("%Y%m%d"),
            end.strftime("%Y%m%d"),
            parameters=["T2M_MAX", "T2M_MIN"],
        )
        tmax = list((data.get("T2M_MAX") or {}).values())
        tmin = list((data.get("T2M_MIN") or {}).values())
        if tmax and tmin:
            gdd = power.calculate_gdd(tmax, tmin, base=profile.gdd_base_c)
            ratio = gdd / profile.gdd_required
            if ratio < 0.85:
                score *= 0.5
                rationale_bits.append(f"insufficient GDD: {gdd:.0f} vs {profile.gdd_required} required")
            elif ratio > 1.3:
                score *= 0.8
                rationale_bits.append(f"excess heat risk: GDD ratio {ratio:.2f}")
            else:
                rationale_bits.append(f"GDD adequate ({gdd:.0f})")

    return score, "; ".join(rationale_bits)


# ---------- Pest keyword mapping (Fix 3) ----------
# Crop → pest/disease names that appear in real evidence text. The bare
# crop name (e.g. "tomato") rarely appears in outbreak alerts; the pest
# name does. We co-locate an alert keyword within a window of the pest
# keyword so unrelated mentions don't trigger a penalty.
CROP_PEST_KEYWORDS: dict[str, list[str]] = {
    "tomato":  ["tuta absoluta", "tomato leafminer", "whitefly", "tylcv"],
    "wheat":   ["wheat rust", "yellow rust", "stripe rust", "hessian fly", "wheat aphid"],
    "maize":   ["fall armyworm", "spodoptera frugiperda", "stem borer"],
    "cotton":  ["bollworm", "spodoptera littoralis", "pink bollworm"],
    "potato":  ["late blight", "phytophthora", "potato tuber moth"],
    "onion":   ["downy mildew", "thrips tabaci", "onion fly"],
    "rice":    ["blast", "stem borer rice", "brown planthopper"],
}
PEST_ALERT_TOKENS = ("outbreak", "alert", "warning", "infestation")
PEST_PROXIMITY_CHARS = 100


def pest_alert_for(crop: str, ev_text: str) -> str | None:
    """Return the matching pest keyword if an outbreak/alert is co-located within
    PEST_PROXIMITY_CHARS of any crop-associated pest keyword. None otherwise.
    """
    pests = CROP_PEST_KEYWORDS.get(crop, [])
    for pest in pests:
        idx = ev_text.find(pest)
        while idx != -1:
            window = ev_text[max(0, idx - PEST_PROXIMITY_CHARS): idx + len(pest) + PEST_PROXIMITY_CHARS]
            if any(tok in window for tok in PEST_ALERT_TOKENS):
                return pest
            idx = ev_text.find(pest, idx + 1)
    return None


# ---------- Stage 8: live signal integration ----------

def score_market_and_risk(profile: CropProfile, state: PipelineState) -> tuple[float, float, list[str], str, str]:
    """
    Returns (market_score, risk_score, vetoes, market_rationale, risk_rationale).
    Reads from accumulated evidence — keyword-based for now, can be upgraded
    to LLM-based fact alignment later.
    """
    market = 0.7  # baseline
    risk = 0.7
    vetoes: list[str] = []
    market_bits = ["baseline price assumed"]
    risk_bits = []

    crop = profile.name
    gov = state.parsed.governorate
    ev_text = " ".join(e.fact.lower() for e in state.evidence)

    # Hard vetoes from config
    if crop == "rice" and gov not in VETO_RULES["rice_decree_26_2025_governorates"]:
        vetoes.append("Ministerial Decree 26/2025 prohibits rice cultivation in this governorate")
        market = 0.0
        risk = 0.0

    # Subsidy / export ban signals
    if f"{crop} subsidy" in ev_text or f"{crop} support price" in ev_text:
        market += 0.15
        market_bits.append("subsidy signal detected")
    if f"export ban {crop}" in ev_text or f"{crop} export quota" in ev_text:
        market -= 0.25
        market_bits.append("export restriction detected")

    # Pest / disease alerts — match crop-specific pest names co-located with an
    # alert token (see CROP_PEST_KEYWORDS). Replaces the old bare-crop substring
    # match, which missed real alerts like "Tuta absoluta outbreak".
    matched_pest = pest_alert_for(crop, ev_text)
    if matched_pest:
        risk -= 0.30
        risk_bits.append(f"active pest alert: {matched_pest}")

    # EGP devaluation — helps export crops, hurts import-dependent inputs
    if "devaluation" in ev_text or "egp depreciation" in ev_text:
        if crop in ("cotton", "potato", "onion"):  # exporters
            market += 0.05
            market_bits.append("devaluation aids export-oriented crop")
        else:
            risk -= 0.05
            risk_bits.append("devaluation raises fertiliser import cost")

    if not risk_bits:
        risk_bits.append("no penalising risk factors detected")
    return (
        max(0.0, min(1.0, market)),
        max(0.0, min(1.0, risk)),
        vetoes,
        "; ".join(market_bits),
        "; ".join(risk_bits),
    )


def score_water_feasibility(profile: CropProfile, state: PipelineState) -> tuple[float, str]:
    """Crude water feasibility score based on water source and crop need."""
    source = state.parsed.raw.water_source.value
    bits = [f"need {profile.water_need_mm} mm; source {source}"]
    score = 1.0

    if source == "rainfed" and profile.water_need_mm > 400:
        score *= 0.2
        bits.append("rainfed cannot meet need")
    elif source == "groundwater" and profile.water_need_mm > 1000:
        score *= 0.5
        bits.append("groundwater under stress for high-water crop")

    # Nile signal
    ev_text = " ".join(e.fact.lower() for e in state.evidence)
    if "low nile" in ev_text or "gerd" in ev_text or "water shortage" in ev_text:
        if profile.water_need_mm > 700:
            score *= 0.6
            bits.append("Nile flow signal — high-water crop discounted")

    return score, "; ".join(bits)


def _ensure_rationale(text: str, default: str = "scored on defaults only") -> str:
    return text if text else default


# ---------- Orchestrator for stages 7+8 ----------

async def run_stages_7_8_score_dimensions(
    state: PipelineState,
    power: NASAPowerClient | None = None,
) -> PipelineState:
    state.log("stage_7_8", "scoring all crops across dimensions")
    soil = state.parsed.soil_profile
    season = state.parsed.season

    scores: list[CropScore] = []
    for profile in CROPS.values():
        # Quick filter: skip crops totally wrong for the season
        if season not in profile.seasons:
            continue

        soil_score, amendments, soil_rationale = score_soil_fit(profile, soil)
        timing_score, timing_rationale = await score_timing(profile, state, power)
        market_score, risk_score, vetoes, market_rat, risk_rat = score_market_and_risk(profile, state)
        water_score, water_rat = score_water_feasibility(profile, state)

        scores.append(CropScore(
            crop=profile.name,
            soil_fit=soil_score,
            timing=timing_score,
            market=market_score,
            water=water_score,
            risk=risk_score,
            overall=0.0,  # filled in stage 9
            rationale={
                "soil_fit": _ensure_rationale(soil_rationale),
                "timing": _ensure_rationale(timing_rationale),
                "market": _ensure_rationale(market_rat),
                "water": _ensure_rationale(water_rat),
                "risk": _ensure_rationale(risk_rat),
            },
            vetoes=vetoes,
        ))

        # Stash amendments on the state keyed by crop for stage 12 to pick up
        if not hasattr(state, "_amendments"):
            state._amendments = {}
        state._amendments[profile.name] = amendments

    state.scores = scores
    state.log("stage_7_8", f"scored {len(scores)} candidate crops")
    return state
