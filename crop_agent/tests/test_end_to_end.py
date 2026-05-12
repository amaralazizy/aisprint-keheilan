"""
End-to-end smoke test. Mocks the LLM and search so this runs offline.

This is the test that proves the orchestrator wires every stage
together correctly. If you change a stage signature and forget to
update pipeline.py, this fails.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock

import pytest

from ..clients.search import SearchResult, StubSearchClient
from ..pipeline import run_pipeline
from .fixtures import sample_sharqia_winter


class FakeLLM:
    """Returns canned JSON for each prompt type, identified by system content."""

    async def chat_json(self, system: str, user: str, max_tokens=None, temperature=None):
        if "query planner" in system:
            return [
                {"text": "Egypt wheat support price 2026", "language": "en",
                 "category": "local_news_and_market", "rationale": "current price for revenue calc"},
                {"text": "wheat varieties Sharqia clay soil", "language": "en",
                 "category": "agronomic_research", "rationale": "match cultivar to soil"},
                {"text": "نشرة وزارة الزراعة الشرقية القمح", "language": "ar",
                 "category": "local_news_and_market", "rationale": "MALR Arabic bulletin"},
            ]
        elif "extract atomic facts" in system:
            return [
                {"fact": "Wheat support price Egypt 2026 is 12000 EGP/ton",
                 "value": 12000, "confidence": "high", "source_date": "2026-02-10"},
            ]
        elif "auditing the evidence" in system:
            return {"uncertainties": [], "follow_up_queries": [], "should_replan": False}
        elif "final auditor" in system:
            return {"passed": True, "issues": [], "confidence_adjustment": 0}
        return {}

    async def chat(self, system, user, max_tokens=None, temperature=None):
        return ""


class FakeSoilGrids:
    async def query_profile(self, lat, lon):
        return {"phh2o": 7.3, "nitrogen": 1.2, "cec": 22.0, "clay": 45, "sand": 25, "silt": 30}


class FakePower:
    async def query_daily(self, lat, lon, start, end, parameters=None):
        # Fake 180 days of warm winter
        return {
            "T2M_MAX": {f"2026{m:02d}{d:02d}": 22 for m in [11, 12, 1, 2, 3, 4, 5] for d in range(1, 31)},
            "T2M_MIN": {f"2026{m:02d}{d:02d}": 10 for m in [11, 12, 1, 2, 3, 4, 5] for d in range(1, 31)},
        }

    @staticmethod
    def calculate_gdd(tmax, tmin, base=10.0):
        return sum(max(0, (a + b) / 2 - base) for a, b in zip(tmax, tmin))


@pytest.mark.asyncio
async def test_end_to_end_smoke():
    """Run the full pipeline with all fakes and assert we get a recommendation."""
    raw = sample_sharqia_winter()
    state = await run_pipeline(
        raw,
        llm=FakeLLM(),
        search=StubSearchClient(),
        soilgrids=FakeSoilGrids(),
        power=FakePower(),
    )

    # Pipeline produced an output
    assert state.output is not None
    assert state.output.top is not None
    assert state.output.top.crop in {"wheat", "barley", "onion", "potato", "sugar_beet", "tomato", "alfalfa"}

    # Stages ran in order — trace should have entries from each
    trace_text = " ".join(state.trace)
    for stage in ["stage_2", "stage_3", "stage_4_5", "stage_6", "stage_7_8", "stage_9", "stage_10", "stage_11", "stage_12"]:
        assert stage in trace_text, f"missing {stage} in trace"

    # Soil profile got filled from SoilGrids
    assert "ph" in state.parsed.soil_profile
    assert state.parsed.soil_profile["ph"]["source"] == "SoilGrids 250m"

    # Confidence is plausible
    assert 20 <= state.output.overall_confidence_pct <= 95

    # Print the output for visual inspection when running -s
    print("\n--- final output ---")
    print(json.dumps(state.output.model_dump(mode="json"), indent=2, default=str))
    print("\n--- trace ---")
    print("\n".join(state.trace))


if __name__ == "__main__":
    import asyncio
    asyncio.run(test_end_to_end_smoke())
