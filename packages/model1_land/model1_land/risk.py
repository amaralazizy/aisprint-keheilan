"""Fallback rule-based risk score used only when AI is unavailable.

Composite score = road access weight + price trend bonus + undervaluation bonus.
AI tiering (ai/risk_model.py) is the primary path.
"""
from .models import Parcel


def score_parcel(p: Parcel) -> float:
    base = p.road_access * 0.6
    trend_bonus = max(min(p.price_trend_pct / 5.0, 2.0), -2.0)
    undervaluation_bonus = max(min((p.undervaluation_pct or 0) / 10.0, 2.0), -2.0)
    return base + trend_bonus + undervaluation_bonus


def assign_tier(p: Parcel) -> str:
    s = score_parcel(p)
    if s < 4.0:
        return "High"
    if s < 7.0:
        return "Medium"
    return "Low"
