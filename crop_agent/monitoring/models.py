from __future__ import annotations
from datetime import date
from pydantic import BaseModel, Field

class FarmerReport(BaseModel):
    report_date: date
    crop: str
    text: str  # The free-text report from the farmer

class AdjustmentResult(BaseModel):
    issues_identified: list[str] = Field(description="List of issues the farmer reported (e.g. pests, drought)")
    severity_score: float = Field(description="Score from 0.0 (perfect) to 1.0 (total failure) representing how bad the progress is")
    yield_reduction_pct: float = Field(description="Percentage to reduce the yield by (e.g. 15.0 for 15%)")
    rationale: str = Field(description="Explanation of why this reduction was applied based on the farmer's text")

class UpdatedPrediction(BaseModel):
    crop: str
    original_yield_range_t_per_feddan: tuple[float, float]
    updated_yield_range_t_per_feddan: tuple[float, float]
    original_revenue_egp_per_feddan: tuple[float, float, float]
    updated_revenue_egp_per_feddan: tuple[float, float, float]
    adjustment_reasoning: str
