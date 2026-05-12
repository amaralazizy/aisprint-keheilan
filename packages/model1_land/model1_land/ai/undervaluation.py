"""AI #1: Undervaluation classifier.

LLM call per parcel. Compares ask price to fair market estimate inferred
from comps in the same governorate.
"""
from __future__ import annotations

from typing import TypedDict
from sqlmodel import Session, select

from ..models import Parcel
from ..clients.llm import get_llm


class UndervaluationResult(TypedDict):
    fair_price_egp: float
    undervaluation_pct: float
    confidence: float
    reasoning: str


SYSTEM = (
    "You are a land-valuation analyst specialised in Egyptian agricultural "
    "parcels. Given a candidate parcel and recent comparable parcels in the "
    "same governorate, estimate the fair market total price (EGP) of the "
    "candidate. Compare to its ask price and judge whether it is undervalued."
)


def _comps(session: Session, parcel: Parcel, limit: int = 8) -> list[Parcel]:
    q = (
        select(Parcel)
        .where(Parcel.governorate == parcel.governorate)
        .where(Parcel.id != parcel.id)
        .limit(limit)
    )
    return list(session.exec(q))


def classify(session: Session, parcel: Parcel) -> UndervaluationResult:
    comps = _comps(session, parcel)
    comps_lines = "\n".join(
        f"- {c.area_feddan} feddan, ask {c.price_egp:,.0f} EGP "
        f"({c.price_egp / c.area_feddan:,.0f} EGP/feddan), "
        f"road {c.road_access}/10, trend {c.price_trend_pct}%"
        for c in comps
    ) or "(no comps available)"

    user = (
        f"Candidate parcel:\n"
        f"- governorate: {parcel.governorate}\n"
        f"- area: {parcel.area_feddan} feddan\n"
        f"- ask price: {parcel.price_egp:,.0f} EGP "
        f"({parcel.price_egp / parcel.area_feddan:,.0f} EGP/feddan)\n"
        f"- road access: {parcel.road_access}/10\n"
        f"- 3-year price trend: {parcel.price_trend_pct}%\n\n"
        f"Comparable parcels in {parcel.governorate}:\n{comps_lines}\n\n"
        "Return JSON: "
        '{"fair_price_egp": <number>, "undervaluation_pct": <number, '
        'positive if ask < fair>, "confidence": <0..1>, '
        '"reasoning": "<one or two sentences>"}'
    )
    out = get_llm().chat_json(SYSTEM, user)
    return {
        "fair_price_egp": float(out["fair_price_egp"]),
        "undervaluation_pct": float(out["undervaluation_pct"]),
        "confidence": float(out["confidence"]),
        "reasoning": str(out["reasoning"]),
    }


def apply(session: Session, parcel: Parcel) -> None:
    r = classify(session, parcel)
    parcel.fair_price_egp = r["fair_price_egp"]
    parcel.undervaluation_pct = r["undervaluation_pct"]
    parcel.undervaluation_confidence = r["confidence"]
    parcel.undervaluation_reasoning = r["reasoning"]
    session.add(parcel)
    session.commit()
