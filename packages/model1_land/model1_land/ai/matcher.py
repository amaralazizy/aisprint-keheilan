"""AI #5: Investor-parcel matcher.

LLM call per investor. Ranks candidate parcels by fit with investor profile.
"""
from __future__ import annotations

from typing import TypedDict
from sqlmodel import Session, select

from ..models import Parcel, Investor
from ..clients.llm import get_llm
from ..config import CONFIG


class Match(TypedDict):
    parcel_id: int
    fit_score: float
    reasoning: str


SYSTEM = (
    "You are an investment concierge for a fractional-land platform. Given "
    "an investor profile and a list of available parcels, return a ranked "
    "list of best-fit parcels with a 0..1 fit score and a short reasoning."
)


def _candidates(session: Session) -> list[Parcel]:
    return list(session.exec(select(Parcel)))


def rank(session: Session, investor: Investor, top_k: int = 5) -> list[Match]:
    parcels = _candidates(session)
    if not parcels:
        return []

    parcels_lines = "\n".join(
        f"- id={p.id} | {p.governorate} | {p.area_feddan}f | "
        f"share={p.price_egp / CONFIG.shares_per_parcel:,.0f} EGP | "
        f"tier={p.risk_tier} | undervaluation={p.undervaluation_pct or 0:.1f}% | "
        f"trend={p.price_trend_pct}%"
        for p in parcels
    )

    user = (
        f"Investor profile:\n"
        f"- name: {investor.name}\n"
        f"- budget: {investor.budget_egp:,.0f} EGP\n"
        f"- horizon: {investor.horizon_years} years\n"
        f"- risk appetite: {investor.risk_appetite}\n\n"
        f"Available parcels:\n{parcels_lines}\n\n"
        f"Return JSON with the top {top_k} matches, ordered best to worst: "
        '{"matches": [{"parcel_id": <int>, "fit_score": <0..1>, '
        '"reasoning": "<one sentence>"}, ...]}'
    )
    out = get_llm().chat_json(SYSTEM, user)
    items = out.get("matches", []) if isinstance(out, dict) else out
    if not isinstance(items, list):
        return []
    return [
        {
            "parcel_id": int(m["parcel_id"]),
            "fit_score": float(m["fit_score"]),
            "reasoning": str(m["reasoning"]),
        }
        for m in items[:top_k]
    ]
