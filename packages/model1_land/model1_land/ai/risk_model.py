"""AI #2: Risk tier model.

LLM call per parcel. Inputs: parcel attrs + lease history + share-fill velocity.
Outputs: tier, score, top factors, reasoning.
"""
from __future__ import annotations

import json
from typing import TypedDict
from sqlmodel import Session

from ..models import Parcel
from ..clients.llm import get_llm


class RiskResult(TypedDict):
    tier: str
    score: float
    factors: list[str]
    reasoning: str


SYSTEM = (
    "You are a risk analyst for fractional agricultural-land investments in "
    "Egypt. Classify a parcel as High, Medium, or Low risk. High risk = "
    "turnaround opportunity (cheap, weak fundamentals, high upside if "
    "resolved). Medium = balanced. Low = stable, premium, predictable yield."
)


def classify(session: Session, parcel: Parcel) -> RiskResult:
    leases = len(parcel.leases)
    total_shares = sum(s.share_count for s in parcel.shares)
    days_old = max(
        0, (parcel.created_at.replace(tzinfo=None) - parcel.created_at.replace(tzinfo=None)).days
    )

    user = (
        f"Parcel:\n"
        f"- governorate: {parcel.governorate}\n"
        f"- area: {parcel.area_feddan} feddan\n"
        f"- ask price: {parcel.price_egp:,.0f} EGP\n"
        f"- road access: {parcel.road_access}/10\n"
        f"- 3-year price trend: {parcel.price_trend_pct}%\n"
        f"- AI undervaluation estimate: {parcel.undervaluation_pct or 0:.1f}%"
        f" (confidence {parcel.undervaluation_confidence or 0:.2f})\n"
        f"- lease history: {leases} prior leases\n"
        f"- shares filled: {total_shares} of 1000\n"
        f"- listed days: {days_old}\n\n"
        "Return JSON: "
        '{"tier": "High|Medium|Low", "score": <0..10 number>, '
        '"factors": ["<top 3 driving factors>"], '
        '"reasoning": "<one or two sentences>"}'
    )
    out = get_llm().chat_json(SYSTEM, user)
    tier = str(out["tier"]).strip().capitalize()
    if tier not in {"High", "Medium", "Low"}:
        tier = "Medium"
    return {
        "tier": tier,
        "score": float(out["score"]),
        "factors": [str(f) for f in out["factors"]],
        "reasoning": str(out["reasoning"]),
    }


def apply(session: Session, parcel: Parcel) -> None:
    r = classify(session, parcel)
    parcel.risk_tier = r["tier"]
    parcel.risk_score = r["score"]
    parcel.risk_factors_json = json.dumps(r["factors"])
    parcel.risk_reasoning = r["reasoning"]
    session.add(parcel)
    session.commit()
