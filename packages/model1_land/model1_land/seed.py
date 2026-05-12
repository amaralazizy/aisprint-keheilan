import os
from sqlmodel import Session, select
from .db import engine, init_db
from .models import Parcel, Investor
from .risk import assign_tier

DEMO_PARCELS = [
    dict(name="Sharqia North Plot A", governorate="Sharqia", area_feddan=12.0,
         price_egp=2_400_000, road_access=7, price_trend_pct=6.5,
         lease_price_egp_per_season=180_000),
    dict(name="Minya Desert Edge", governorate="Minya", area_feddan=25.0,
         price_egp=1_500_000, road_access=5, price_trend_pct=-2.0,
         lease_price_egp_per_season=120_000),
    dict(name="Beheira Delta Strip", governorate="Beheira", area_feddan=8.0,
         price_egp=2_000_000, road_access=8, price_trend_pct=4.0,
         lease_price_egp_per_season=160_000),
    dict(name="Fayoum Reclaim Lot", governorate="Fayoum", area_feddan=18.0,
         price_egp=900_000, road_access=4, price_trend_pct=1.0,
         lease_price_egp_per_season=90_000),
    dict(name="Aswan South Patch", governorate="Aswan", area_feddan=30.0,
         price_egp=1_100_000, road_access=3, price_trend_pct=-1.5,
         lease_price_egp_per_season=100_000),
    dict(name="Sharqia East Plot B", governorate="Sharqia", area_feddan=15.0,
         price_egp=2_700_000, road_access=8, price_trend_pct=5.0,
         lease_price_egp_per_season=210_000),
    dict(name="Beheira Coastal Strip", governorate="Beheira", area_feddan=10.0,
         price_egp=2_300_000, road_access=7, price_trend_pct=3.5,
         lease_price_egp_per_season=180_000),
]

DEMO_INVESTORS = [
    dict(name="Karim Hassan", email="karim@example.com",
         budget_egp=500_000, horizon_years=5, risk_appetite="Low"),
    dict(name="Nadia Fahmy", email="nadia@example.com",
         budget_egp=200_000, horizon_years=2, risk_appetite="High"),
]


def seed(run_ai: bool = False) -> None:
    init_db()
    with Session(engine) as s:
        if s.exec(select(Parcel)).first():
            print("Already seeded.")
            return
        for row in DEMO_PARCELS:
            p = Parcel(**row)
            p.risk_tier = assign_tier(p)
            s.add(p)
        for row in DEMO_INVESTORS:
            s.add(Investor(**row))
        s.commit()
        print(f"Seeded {len(DEMO_PARCELS)} parcels, {len(DEMO_INVESTORS)} investors.")

    if run_ai:
        _run_ai_pass()


def _run_ai_pass() -> None:
    """Optional: run AI valuation + tiering on every parcel. Requires OPENROUTER_API_KEY."""
    from .ai import undervaluation, risk_model
    with Session(engine) as s:
        parcels = list(s.exec(select(Parcel)))
        for p in parcels:
            print(f"  AI valuating {p.name}...")
            undervaluation.apply(s, p)
            risk_model.apply(s, p)
    print("AI pass complete.")


if __name__ == "__main__":
    seed(run_ai=os.getenv("SEED_RUN_AI") == "1")
