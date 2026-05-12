"""
Stage 2 — parse raw inputs, normalise units, resolve governorate,
infer season, fill missing soil fields from SoilGrids, flag anomalies.

The anomaly detector is the under-appreciated piece. It produces input
for the planner, which then asks targeted questions.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date

from ..clients.soil_weather import SoilGridsClient
from ..models import Anomaly, ParsedInput
from ..state import PipelineState

logger = logging.getLogger(__name__)

# Regional soil defaults — only used when neither user nor SoilGrids supply data.
# Values are typical (not authoritative): FAO regional averages.
# Keyed by (governorate or region tag, soil_type).
REGIONAL_SOIL_DEFAULTS: dict[tuple[str, str], dict[str, float]] = {
    # Delta clay (Sharqia, Dakahlia, Beheira, Gharbia, Kafr El Sheikh, Damietta, Menoufia, Qalyubia)
    ("Delta", "clay"):       {"ph": 7.8, "cec": 28.0, "salinity_ds_m": 1.5, "clay_pct": 45.0, "sand_pct": 20.0},
    ("Delta", "sandy loam"): {"ph": 7.6, "cec": 14.0, "salinity_ds_m": 1.2, "clay_pct": 18.0, "sand_pct": 55.0},
    # Upper Egypt (Minya, Asyut, Sohag, Qena, Luxor, Aswan, Beni Suef, Fayoum)
    ("Upper", "clay"):       {"ph": 7.9, "cec": 22.0, "salinity_ds_m": 1.8, "clay_pct": 40.0, "sand_pct": 25.0},
    ("Upper", "sandy loam"): {"ph": 7.7, "cec": 10.0, "salinity_ds_m": 2.0, "clay_pct": 15.0, "sand_pct": 60.0},
    ("Upper", "sandy"):      {"ph": 7.8, "cec":  7.0, "salinity_ds_m": 2.5, "clay_pct":  8.0, "sand_pct": 75.0},
    # Reclaimed desert land (low CEC, low organic matter, often slightly saline)
    ("Reclaimed", "sandy"):  {"ph": 8.1, "cec":  5.0, "salinity_ds_m": 3.0, "clay_pct":  5.0, "sand_pct": 85.0},
}

DELTA_GOVERNORATES = {
    "Cairo", "Giza", "Alexandria", "Beheira", "Kafr El Sheikh", "Dakahlia",
    "Sharqia", "Gharbia", "Menoufia", "Qalyubia", "Damietta", "Ismailia",
    "Port Said", "Suez",
}
UPPER_GOVERNORATES = {
    "Fayoum", "Beni Suef", "Minya", "Asyut", "Sohag", "Qena", "Luxor", "Aswan",
}


def _region_tag(governorate: str) -> str:
    if governorate in DELTA_GOVERNORATES:
        return "Delta"
    if governorate in UPPER_GOVERNORATES:
        return "Upper"
    return "Reclaimed"


def _regional_default_for(governorate: str, soil_type: str) -> dict[str, float] | None:
    region = _region_tag(governorate)
    return (
        REGIONAL_SOIL_DEFAULTS.get((region, soil_type.lower()))
        or REGIONAL_SOIL_DEFAULTS.get((region, "clay" if region == "Delta" else "sandy"))
    )

# Egyptian seasons (rough — agent will refine with NASA POWER data)
def infer_season(start: date) -> str:
    m = start.month
    if m in (11, 12, 1, 2, 3, 4, 5):
        return "shitawi"  # winter
    if m in (7, 8, 9, 10):
        return "nili"     # late summer
    return "seifi"        # summer (April–October overlaps; nili wins for July+)


# Bounding boxes by governorate — coarse but good enough for routing
GOVERNORATE_BBOX = {
    "Cairo":       (29.95, 30.20, 31.20, 31.45),
    "Giza":        (29.85, 30.15, 31.05, 31.30),
    "Alexandria":  (31.10, 31.40, 29.80, 30.10),
    "Beheira":     (30.30, 31.20, 30.10, 30.80),
    "Kafr El Sheikh": (31.00, 31.50, 30.70, 31.30),
    "Dakahlia":    (30.80, 31.40, 31.10, 31.90),
    "Sharqia":     (30.20, 31.00, 31.40, 32.10),
    "Gharbia":     (30.50, 31.05, 30.80, 31.30),
    "Menoufia":    (30.30, 30.80, 30.80, 31.30),
    "Qalyubia":    (30.10, 30.55, 31.00, 31.50),
    "Damietta":    (31.20, 31.55, 31.60, 32.00),
    "Ismailia":    (30.30, 30.80, 32.10, 32.70),
    "Port Said":   (30.95, 31.35, 32.20, 32.50),
    "Suez":        (29.70, 30.20, 32.40, 32.85),
    "Fayoum":      (29.10, 29.65, 30.50, 31.20),
    "Beni Suef":   (28.50, 29.15, 30.70, 31.30),
    "Minya":       (27.60, 28.50, 30.30, 31.10),
    "Asyut":       (26.80, 27.60, 30.70, 31.40),
    "Sohag":       (26.10, 27.00, 31.30, 32.00),
    "Qena":        (25.80, 26.60, 32.40, 33.00),
    "Luxor":       (25.40, 25.90, 32.40, 32.90),
    "Aswan":       (22.80, 24.40, 32.40, 33.10),
}


def resolve_governorate(lat: float, lon: float) -> str:
    for name, (lat_min, lat_max, lon_min, lon_max) in GOVERNORATE_BBOX.items():
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return name
    return "Unknown"


def detect_anomalies(soil_profile: dict, raw_area: float) -> list[Anomaly]:
    """Flag values that should change downstream reasoning."""
    out: list[Anomaly] = []

    ph_entry = soil_profile.get("ph")
    if ph_entry and ph_entry["value"] is not None:
        ph = ph_entry["value"]
        if ph < 5.5:
            out.append(Anomaly(field="ph", value=ph, reason="strongly acidic — needs liming", severity="warn"))
        elif ph > 8.5:
            out.append(Anomaly(field="ph", value=ph, reason="alkaline/sodic risk — sulphur or gypsum", severity="warn"))

    salinity_entry = soil_profile.get("salinity_ds_m")
    if salinity_entry and salinity_entry["value"] is not None:
        s = salinity_entry["value"]
        if s > 4.0:
            out.append(Anomaly(field="salinity", value=s, reason="saline — limits crop choice to halophytes or needs leaching", severity="block"))
        elif s > 2.0:
            out.append(Anomaly(field="salinity", value=s, reason="moderately saline — narrows crop choice", severity="warn"))

    if raw_area < 0.1:
        out.append(Anomaly(field="area", value=raw_area, reason="unusually small — check units", severity="info"))
    elif raw_area > 1000:
        out.append(Anomaly(field="area", value=raw_area, reason="very large — verify this is one plot", severity="info"))

    return out


def feddan_to_hectare(feddan: float) -> float:
    return feddan * 0.42  # 1 feddan ≈ 0.42 ha


async def run_stage_2_parse(state: PipelineState, soilgrids: SoilGridsClient | None = None) -> PipelineState:
    state.log("stage_2", "starting parse + anomaly detect")
    raw = state.raw

    governorate = resolve_governorate(raw.latitude, raw.longitude)
    season = infer_season(raw.start_date)

    # Build soil profile with provenance — what the user gave vs. what we fetched
    soil_profile: dict = {}

    def add(key: str, value, source: str, confidence: str):
        soil_profile[key] = {"value": value, "source": source, "confidence": confidence}

    # User-provided values get high confidence
    if raw.ph is not None:
        add("ph", raw.ph, "user", "high")
    if raw.nitrogen_ppm is not None:
        add("nitrogen", raw.nitrogen_ppm, "user", "high")
    if raw.phosphorus_ppm is not None:
        add("phosphorus", raw.phosphorus_ppm, "user", "high")
    if raw.potassium_ppm is not None:
        add("potassium", raw.potassium_ppm, "user", "high")
    if raw.salinity_ds_m is not None:
        add("salinity_ds_m", raw.salinity_ds_m, "user", "high")
    if raw.cec is not None:
        add("cec", raw.cec, "user", "high")

    # Fill gaps from SoilGrids — retry once with backoff if the first call is empty
    if soilgrids and any(k not in soil_profile for k in ("ph", "nitrogen", "cec")):
        sg: dict = {}
        for attempt in (1, 2):
            try:
                sg = await soilgrids.query_profile(raw.latitude, raw.longitude)
            except Exception as e:  # network/parse failures are non-fatal
                state.log("stage_2", f"SoilGrids attempt {attempt} failed: {e}")
                sg = {}
            if sg:
                break
            if attempt == 1:
                state.log("stage_2", "SoilGrids returned empty — retrying once after backoff")
                await asyncio.sleep(1.0)
        if "phh2o" in sg and "ph" not in soil_profile:
            add("ph", sg["phh2o"], "SoilGrids 250m", "medium")
        if "nitrogen" in sg and "nitrogen" not in soil_profile:
            add("nitrogen", sg["nitrogen"], "SoilGrids 250m", "medium")
        if "cec" in sg and "cec" not in soil_profile:
            add("cec", sg["cec"], "SoilGrids 250m", "medium")
        if "clay" in sg:
            add("clay_pct", sg["clay"], "SoilGrids 250m", "medium")
        if "sand" in sg:
            add("sand_pct", sg["sand"], "SoilGrids 250m", "medium")

    # If still no usable soil signal anywhere, populate regional defaults so
    # downstream scoring has something to discriminate on. Every imputed
    # value is tagged low/regional_default so the critique stage can surface it.
    used_regional_default = False
    if not soil_profile:
        defaults = _regional_default_for(governorate, raw.soil_type or "clay")
        if defaults:
            state.log("stage_2", f"no soil data — imputing regional defaults for {_region_tag(governorate)}/{raw.soil_type}")
            for key, value in defaults.items():
                add(key, value, "regional_default", "low")
            used_regional_default = True

    anomalies = detect_anomalies(soil_profile, raw.area_feddan)
    if used_regional_default:
        anomalies.append(Anomaly(
            field="soil_data",
            value="missing",
            reason="no measured or fetched soil data — using regional defaults",
            severity="warn",
        ))

    parsed = ParsedInput(
        raw=raw,
        governorate=governorate,
        season=season,
        area_hectare=feddan_to_hectare(raw.area_feddan),
        soil_profile=soil_profile,
        anomalies=anomalies,
    )
    state.parsed = parsed
    state.log("stage_2", f"governorate={governorate}, season={season}, anomalies={len(anomalies)}")
    return state
