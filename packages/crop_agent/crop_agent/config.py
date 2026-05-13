"""All tunable knobs live here. No magic numbers in stages."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    # LLM (OpenRouter — OpenAI-compatible)
    # Two-model split:
    #   reasoner = decisions/planning/critique  (GPT-4o-mini)
    #   worker   = extraction/normalisation     (Llama 3.1 8B, ~7× cheaper)
    reasoner_model: str = os.getenv("REASONER_MODEL", "openai/gpt-4o-mini")
    worker_model: str = os.getenv("WORKER_MODEL", "meta-llama/llama-3.1-8b-instruct")
    llm_model: str = os.getenv("LLM_MODEL", "openai/gpt-4o-mini")  # default fallback
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.2
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")

    # Reflection loop (lowered for free-tier RPM)
    max_reflection_rounds: int = 0
    max_searches_per_reflection: int = 1

    # Planner (lowered for free-tier RPM)
    max_initial_queries: int = 2
    min_queries_per_category: int = 0

    # Search
    search_timeout_s: int = 20
    parallel_search_limit: int = 3  # capped for Gemini free-tier RPM

    # Scoring weights — defaults, overridden per farmer goal
    default_weights: dict = None  # filled in __post_init__-style below

    # APIs
    soilgrids_base: str = "https://rest.isric.org/soilgrids/v2.0/properties/query"
    nasa_power_base: str = "https://power.larc.nasa.gov/api/temporal/daily/point"

    llm_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    search_api_key: str = os.getenv("SEARCH_API_KEY", "")


# Module-level singleton — import this, not Config()
CONFIG = Config()

# Weight presets per farmer goal — picked up by stage 9
WEIGHT_PRESETS = {
    "profit":      {"soil_fit": 0.20, "timing": 0.15, "market": 0.35, "water": 0.15, "risk": 0.15},
    "subsistence": {"soil_fit": 0.25, "timing": 0.20, "market": 0.10, "water": 0.20, "risk": 0.25},
    "export":      {"soil_fit": 0.15, "timing": 0.15, "market": 0.40, "water": 0.15, "risk": 0.15},
    "low_risk":    {"soil_fit": 0.20, "timing": 0.20, "market": 0.10, "water": 0.20, "risk": 0.30},
}

# Hard veto rules — applied after scoring
VETO_RULES = {
    "rice_decree_26_2025_governorates": [
        "Beheira", "Kafr El Sheikh", "Dakahlia", "Damietta", "Sharqia",
        "Gharbia", "Ismailia", "Port Said", "Fayoum",
    ],
}
