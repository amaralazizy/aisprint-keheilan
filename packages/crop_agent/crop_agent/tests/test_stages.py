"""
Stage-by-stage unit tests. These run WITHOUT API keys by using stub
clients and hand-built state.

Run with: pytest crop_agent/tests/test_stages.py -v
"""
from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock

import pytest

from ..models import (
    Evidence,
    ParsedInput,
    PlannedQuery,
    RawInput,
)
from ..stages.stage_2_parse import (
    detect_anomalies,
    feddan_to_hectare,
    infer_season,
    resolve_governorate,
    run_stage_2_parse,
)
from ..stages.stage_4_5_search_extract import detect_and_record_conflicts
from ..stages.stages_7_8_score import (
    CROPS,
    score_soil_fit,
    score_water_feasibility,
)
from ..stages.stages_9_10_score_scenarios import (
    run_stage_10_scenarios,
    run_stage_9_overall_score,
)
from ..state import PipelineState
from .fixtures import (
    sample_minya_water_stress,
    sample_salinity_blocked,
    sample_sharqia_winter,
)


# ---------- Stage 2 unit tests ----------

class TestStage2:
    def test_governorate_sharqia(self):
        assert resolve_governorate(30.71, 31.74) == "Sharqia"

    def test_governorate_minya(self):
        assert resolve_governorate(28.10, 30.75) == "Minya"

    def test_season_winter(self):
        assert infer_season(date(2026, 11, 15)) == "shitawi"

    def test_season_nili(self):
        assert infer_season(date(2026, 8, 1)) == "nili"

    def test_feddan_conversion(self):
        assert abs(feddan_to_hectare(10) - 4.2) < 0.01

    def test_anomaly_detect_high_salinity(self):
        soil = {"salinity_ds_m": {"value": 5.5, "source": "user", "confidence": "high"}}
        anomalies = detect_anomalies(soil, 2.0)
        salinity_anomaly = next((a for a in anomalies if a.field == "salinity"), None)
        assert salinity_anomaly is not None
        assert salinity_anomaly.severity == "block"

    def test_anomaly_detect_high_ph(self):
        soil = {"ph": {"value": 8.7, "source": "user", "confidence": "high"}}
        anomalies = detect_anomalies(soil, 2.0)
        ph_anomaly = next((a for a in anomalies if a.field == "ph"), None)
        assert ph_anomaly is not None
        assert ph_anomaly.severity == "warn"

    @pytest.mark.asyncio
    async def test_stage_2_no_soilgrids(self):
        """Run with soilgrids=None — should work using only user values."""
        raw = sample_minya_water_stress()
        state = PipelineState(raw=raw)
        await run_stage_2_parse(state, soilgrids=None)
        assert state.parsed is not None
        assert state.parsed.governorate == "Minya"
        assert state.parsed.season == "shitawi"
        assert state.parsed.soil_profile["ph"]["source"] == "user"


# ---------- Stage 7 (soil scoring) unit tests ----------

class TestStage7Soil:
    def _full_soil(self, ph=7.0, salinity=1.0, cec=15.0) -> dict:
        # Full triple — pH, salinity, CEC — so completeness=1.0 and tests
        # isolate the band logic from the Fix 2 uncertainty multiplier.
        return {
            "ph": {"value": ph, "source": "user", "confidence": "high"},
            "salinity_ds_m": {"value": salinity, "source": "user", "confidence": "high"},
            "cec": {"value": cec, "source": "user", "confidence": "high"},
        }

    def test_wheat_optimal_ph(self):
        score, amendments, _ = score_soil_fit(CROPS["wheat"], self._full_soil(ph=7.0))
        assert score == 1.0
        assert amendments == []

    def test_wheat_high_ph_amendment(self):
        score, amendments, _ = score_soil_fit(CROPS["wheat"], self._full_soil(ph=8.2))
        assert 0.5 < score < 1.0
        assert any("sulphur" in a.action for a in amendments)

    def test_potato_saline_failure(self):
        # potato salinity tolerance = 1.7 dS/m; we give it 3.5
        soil = self._full_soil(ph=6.0, salinity=3.5, cec=15.0)
        score, amendments, _ = score_soil_fit(CROPS["potato"], soil)
        assert score < 0.5
        assert any("gypsum" in a.action for a in amendments)

    # ---- Fix 2: no soil data must NOT score 1.0 ----
    def test_empty_soil_below_0_7(self):
        score, _, rat = score_soil_fit(CROPS["wheat"], {})
        assert score < 0.7, f"empty soil should not score 1.0, got {score}"
        assert "uncertainty" in rat or "limited soil data" in rat

    # ---- Fix 2: regional_default sources still contribute but less ----
    def test_regional_default_lower_than_user(self):
        soil_user = {
            "ph": {"value": 7.5, "source": "user", "confidence": "high"},
            "salinity_ds_m": {"value": 1.0, "source": "user", "confidence": "high"},
            "cec": {"value": 20.0, "source": "user", "confidence": "high"},
        }
        soil_default = {
            "ph": {"value": 7.5, "source": "regional_default", "confidence": "low"},
            "salinity_ds_m": {"value": 1.0, "source": "regional_default", "confidence": "low"},
            "cec": {"value": 20.0, "source": "regional_default", "confidence": "low"},
        }
        s_user, _, _ = score_soil_fit(CROPS["wheat"], soil_user)
        s_def, _, _ = score_soil_fit(CROPS["wheat"], soil_default)
        assert s_def < s_user


# ---------- Stage 8 (water) unit tests ----------

class TestStage8Water:
    def test_rice_rainfed_fails(self):
        state = PipelineState(raw=sample_minya_water_stress())
        # Manually set water source — sample is canal, override
        state.raw.water_source = state.raw.water_source.__class__.RAINFED
        # Skip stage 2 — just build a minimal parsed
        state.parsed = ParsedInput(
            raw=state.raw,
            governorate="Minya",
            season="shitawi",
            area_hectare=1.26,
            soil_profile={},
            anomalies=[],
        )
        score, rat = score_water_feasibility(CROPS["rice"], state)
        assert score < 0.3


# ---------- Stage 9 + 10 ----------

class TestStages9And10:
    def _build_minimal_state(self, goal="profit"):
        raw = sample_sharqia_winter()
        raw.goal = raw.goal.__class__(goal)
        state = PipelineState(raw=raw)
        state.parsed = ParsedInput(
            raw=raw,
            governorate="Sharqia",
            season="shitawi",
            area_hectare=2.1,
            soil_profile={"ph": {"value": 7.2, "source": "user", "confidence": "high"}},
            anomalies=[],
        )
        # Hand-build a couple of scores
        from ..models import CropScore
        state.scores = [
            CropScore(
                crop="wheat", soil_fit=0.9, timing=0.9, market=0.9, water=0.6, risk=0.5,
                overall=0.0, rationale={}, vetoes=[],
            ),
            CropScore(
                crop="barley", soil_fit=0.8, timing=0.8, market=0.4, water=0.9, risk=0.9,
                overall=0.0, rationale={}, vetoes=[],
            ),
        ]
        return state

    def test_profit_goal_favours_market(self):
        state = self._build_minimal_state(goal="profit")
        run_stage_9_overall_score(state)
        # Wheat has higher market score; with profit weighting it should win
        assert state.scores[0].crop == "wheat"

    def test_low_risk_goal_can_flip(self):
        state = self._build_minimal_state(goal="low_risk")
        run_stage_9_overall_score(state)
        # Barley has higher water + risk scores; low_risk preset weights those
        assert state.scores[0].crop == "barley"

    def test_scenarios_generated(self):
        state = self._build_minimal_state(goal="profit")
        run_stage_9_overall_score(state)
        run_stage_10_scenarios(state)
        assert len(state.scenarios) == 2
        assert all(len(s.drought_egp_per_feddan) == 3 for s in state.scenarios)


# ---------- Conflict detector ----------

class TestConflictDetector:
    def test_no_conflict_when_values_close(self):
        state = PipelineState(raw=sample_sharqia_winter())
        state.evidence = [
            Evidence(fact="wheat yield egypt average", value=6.5, source_url="a", source_name="A",
                     confidence="high", query_id="q1", language="en"),
            Evidence(fact="wheat yield egypt average", value=6.8, source_url="b", source_name="B",
                     confidence="high", query_id="q2", language="en"),
        ]
        detect_and_record_conflicts(state)
        assert len(state.conflicts) == 0

    def test_hard_conflict_when_values_diverge(self):
        state = PipelineState(raw=sample_sharqia_winter())
        state.evidence = [
            Evidence(fact="wheat support price egp ton 2026", value=11000, source_url="a", source_name="A",
                     confidence="high", query_id="q1", language="en"),
            Evidence(fact="wheat support price egp ton 2026", value=18000, source_url="b", source_name="B",
                     confidence="high", query_id="q2", language="en"),
        ]
        detect_and_record_conflicts(state)
        assert any(c.severity == "hard" for c in state.conflicts)


# ---------- Fix 1: regional default soil profile ----------

class TestStage2RegionalDefault:
    def test_regional_defaults_populate_when_all_empty(self):
        """Sharqia + clay + no user soil + SoilGrids empty → regional default kicks in."""
        raw = sample_sharqia_winter()
        # Sharqia winter sample already has soil_type="clay" and no measured fields.
        state = PipelineState(raw=raw)

        class _EmptySoilGrids:
            async def query_profile(self, lat, lon):
                return {}  # simulate SoilGrids returning nothing

        asyncio.run(run_stage_2_parse(state, soilgrids=_EmptySoilGrids()))

        assert state.parsed.soil_profile, "soil_profile must not be empty after regional default fill"
        sources = {e["source"] for e in state.parsed.soil_profile.values()}
        assert sources == {"regional_default"}, f"expected only regional_default, got {sources}"
        assert any(
            a.field == "soil_data" and a.severity == "warn"
            for a in state.parsed.anomalies
        ), "missing the soil_data anomaly that flags use of regional defaults"


# ---------- Fix 3: crop-specific pest alert ----------

class TestStage8PestAlert:
    def _state_with_tuta_evidence(self):
        state = PipelineState(raw=sample_sharqia_winter())
        state.parsed = ParsedInput(
            raw=state.raw,
            governorate="Sharqia",
            season="shitawi",
            area_hectare=2.1,
            soil_profile={
                "ph": {"value": 7.5, "source": "user", "confidence": "high"},
                "salinity_ds_m": {"value": 1.0, "source": "user", "confidence": "high"},
                "cec": {"value": 20.0, "source": "user", "confidence": "high"},
            },
            anomalies=[],
        )
        state.evidence = [
            Evidence(
                fact="tuta absoluta outbreak reported across delta governorates april 2026",
                value=None,
                source_url="https://fao.org/empres/example",
                source_name="FAO EMPRES",
                confidence="high",
                query_id="q1",
                language="en",
            ),
        ]
        return state

    def test_tomato_risk_drops_wheat_does_not(self):
        from ..stages.stages_7_8_score import score_market_and_risk
        state = self._state_with_tuta_evidence()
        _, tomato_risk, _, _, tomato_rat = score_market_and_risk(CROPS["tomato"], state)
        _, wheat_risk, _, _, _ = score_market_and_risk(CROPS["wheat"], state)
        assert tomato_risk < 0.5, f"tomato should be penalised by Tuta absoluta, got {tomato_risk}"
        assert wheat_risk >= 0.7, f"wheat should be unaffected, got {wheat_risk}"
        assert "tuta absoluta" in tomato_rat


# ---------- Fix 5: assumption collection ----------

class TestStage11Assumptions:
    def test_smallholder_with_no_optionals_yields_at_least_5(self):
        """Sharqia sample provides none of the optional soil fields → ≥5 assumptions."""
        from ..stages.stages_11_12_critique_output import _collect_assumptions
        raw = sample_sharqia_winter()
        state = PipelineState(raw=raw)
        # Mimic Stage 2 having populated regional defaults.
        state.parsed = ParsedInput(
            raw=raw,
            governorate="Sharqia",
            season="shitawi",
            area_hectare=2.1,
            soil_profile={
                "ph": {"value": 7.8, "source": "regional_default", "confidence": "low"},
                "cec": {"value": 28.0, "source": "regional_default", "confidence": "low"},
            },
            anomalies=[],
        )
        # No scores needed for assumption #4 to fire — just leave empty.
        state.scores = []
        ass = _collect_assumptions(state)
        assert len(ass) >= 5, f"expected ≥5 assumptions, got {len(ass)}: {ass}"
        sources = {a["source"] for a in ass}
        # Must include user_input_missing AND a regional default marker.
        assert "user_input_missing" in sources
        assert any(s in sources for s in ("regional_default", "soil_data_missing"))


if __name__ == "__main__":
    # Quick smoke run without pytest
    asyncio.run(TestStage2().test_stage_2_no_soilgrids())
    print("smoke test passed")
