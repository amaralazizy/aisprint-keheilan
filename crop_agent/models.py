"""
Data models for the Egypt crop recommender pipeline.

Every stage reads from and writes to typed Pydantic models. This makes
debugging easy — you can pickle the state at any stage boundary and
inspect it, and you can run later stages in isolation by hand-building
the upstream state.
"""
from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field


# ---------- Stage 1: raw inputs ----------

class FarmerGoal(str, Enum):
    PROFIT = "profit"
    SUBSISTENCE = "subsistence"
    EXPORT = "export"
    LOW_RISK = "low_risk"


class WaterSource(str, Enum):
    NILE_CANAL = "nile_canal"
    GROUNDWATER = "groundwater"
    RAINFED = "rainfed"
    MIXED = "mixed"


class RawInput(BaseModel):
    """What the farmer (or front-end) hands us. Most optionals can be blank."""
    # Mandatory
    latitude: float
    longitude: float
    area_feddan: float
    water_source: WaterSource
    soil_type: str  # free-text — "clay", "sandy", "loam", or Arabic
    budget_egp: float
    start_date: date
    harvest_horizon_days: int
    goal: FarmerGoal = FarmerGoal.PROFIT
    language: Literal["en", "ar"] = "en"

    # Optional — agent fills from SoilGrids if missing
    ph: Optional[float] = None
    nitrogen_ppm: Optional[float] = None
    phosphorus_ppm: Optional[float] = None
    potassium_ppm: Optional[float] = None
    salinity_ds_m: Optional[float] = None
    soil_depth_cm: Optional[float] = None
    cec: Optional[float] = None
    irrigation_type: Optional[str] = None
    last_crop: Optional[str] = None
    last_harvest_date: Optional[date] = None
    crop_history_success: list[str] = Field(default_factory=list)
    crop_history_failure: list[str] = Field(default_factory=list)
    past_diseases: list[str] = Field(default_factory=list)
    years_since_reclamation: Optional[int] = None


# ---------- Stage 2: parsed + anomalies ----------

class ParsedInput(BaseModel):
    """Normalised, governorate-resolved, season-inferred."""
    raw: RawInput
    governorate: str
    season: Literal["shitawi", "seifi", "nili"]
    area_hectare: float

    # Filled fields with provenance: which came from the user, which imputed
    soil_profile: dict  # {field: {value, source, confidence}}
    anomalies: list["Anomaly"] = Field(default_factory=list)


class Anomaly(BaseModel):
    field: str
    value: float | str
    reason: str
    severity: Literal["info", "warn", "block"]


# ---------- Stage 3: query planner ----------

QueryCategory = Literal["fixed_knowledge", "live_signal", "arabic_ministry"]

class PlannedQuery(BaseModel):
    text: str
    language: Literal["en", "ar"]
    category: QueryCategory
    rationale: str  # why the agent chose this query — useful for debugging


# ---------- Stage 5: evidence ----------

class Evidence(BaseModel):
    fact: str
    value: str | float | None = None
    source_url: str
    source_name: str
    source_date: Optional[date] = None
    confidence: Literal["high", "medium", "low"]
    query_id: str  # which PlannedQuery produced this
    language: Literal["en", "ar"]


class Conflict(BaseModel):
    fact_a: Evidence
    fact_b: Evidence
    severity: Literal["soft", "hard"]
    resolution: Optional[str] = None  # filled after reflection


# ---------- Stage 7–8: dimension scores ----------

class CropScore(BaseModel):
    crop: str
    soil_fit: float  # 0–1
    timing: float
    market: float
    water: float
    risk: float
    overall: float
    rationale: dict[str, str]  # dimension -> one-line explanation
    vetoes: list[str] = Field(default_factory=list)  # e.g. "rice decree 26/2025"


# ---------- Stage 10: scenarios ----------

class ScenarioOutcome(BaseModel):
    crop: str
    drought_egp_per_feddan: tuple[float, float, float]  # pessimistic, base, optimistic
    devaluation_egp_per_feddan: tuple[float, float, float]
    pest_egp_per_feddan: tuple[float, float, float]
    collapses_under: list[str] = Field(default_factory=list)


# ---------- Stage 12: final output ----------

class AmendmentStep(BaseModel):
    action: str  # "apply gypsum 2 t/feddan"
    cost_egp: float
    reason: str


class PestCalendarEntry(BaseModel):
    month: str
    pest: str
    action: str


class CropRecommendation(BaseModel):
    rank: int
    crop: str
    confidence_pct: int
    score_breakdown: dict[str, float]
    yield_range_t_per_feddan: tuple[float, float]
    revenue_egp_per_feddan: tuple[float, float, float]  # pess, base, opt
    amendment_plan: list[AmendmentStep]
    pest_calendar: list[PestCalendarEntry]
    trade_offs: str


class FinalOutput(BaseModel):
    top: CropRecommendation
    alternatives: list[CropRecommendation]
    assumptions: list[dict]  # {text, confidence, source}
    overall_confidence_pct: int
    language: Literal["en", "ar"]
    generated_at: datetime
