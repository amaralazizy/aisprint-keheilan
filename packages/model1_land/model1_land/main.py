import json
from pathlib import Path
from datetime import date
from fastapi import FastAPI, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from .db import init_db, get_session
from .models import Parcel, LeaseRecord, Investor, Share, Payout
from .config import CONFIG
from .ai import undervaluation, risk_model, matcher

app = FastAPI(title="Keheilan Model 1 — Fractional Land")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.on_event("startup")
def on_startup() -> None:
    init_db()


# ---------- parcels ----------

@app.get("/")
def index(request: Request, tier: str | None = None, session: Session = Depends(get_session)):
    q = select(Parcel)
    if tier in {"High", "Medium", "Low"}:
        q = q.where(Parcel.risk_tier == tier)
    parcels = session.exec(q).all()
    return templates.TemplateResponse(request, "parcels.html",
        {"parcels": parcels, "tier": tier, "shares_per_parcel": CONFIG.shares_per_parcel})


@app.get("/parcels/{parcel_id}")
def parcel_detail(parcel_id: int, request: Request, session: Session = Depends(get_session)):
    p = session.get(Parcel, parcel_id)
    if not p:
        raise HTTPException(404)
    sold_shares = sum(s.share_count for s in p.shares)
    factors = json.loads(p.risk_factors_json) if p.risk_factors_json else []
    total_payouts = sum(po.amount_egp for po in p.payouts)
    return templates.TemplateResponse(request, "parcel.html", {
        "p": p,
        "sold_shares": sold_shares,
        "remaining_shares": CONFIG.shares_per_parcel - sold_shares,
        "shares_per_parcel": CONFIG.shares_per_parcel,
        "price_per_share": p.price_egp / CONFIG.shares_per_parcel,
        "risk_factors": factors,
        "total_payouts": total_payouts,
    })


@app.post("/parcels/{parcel_id}/lease")
def add_lease(parcel_id: int, farmer_name: str = Form(...), season: str = Form(...),
              start_date: date = Form(...), end_date: date = Form(...),
              session: Session = Depends(get_session)):
    p = session.get(Parcel, parcel_id)
    if not p:
        raise HTTPException(404)
    if p.lease_price_egp_per_season <= 0:
        raise HTTPException(400, "Lease price not set by the company for this parcel.")

    lease = LeaseRecord(parcel_id=parcel_id, farmer_name=farmer_name, season=season,
                        rent_egp=p.lease_price_egp_per_season,
                        start_date=start_date, end_date=end_date)
    session.add(lease)
    session.commit()
    session.refresh(lease)

    # Distribute rent pro-rata to investors by share holdings.
    for sh in p.shares:
        share_pct = sh.share_count / CONFIG.shares_per_parcel * 100
        amount = p.lease_price_egp_per_season * sh.share_count / CONFIG.shares_per_parcel
        session.add(Payout(lease_id=lease.id, parcel_id=p.id,
                           investor_id=sh.investor_id, share_count=sh.share_count,
                           share_pct=share_pct, amount_egp=amount))
    session.commit()
    return RedirectResponse(f"/parcels/{parcel_id}", status_code=303)


@app.post("/parcels/{parcel_id}/lease_price")
def set_lease_price(parcel_id: int, lease_price_egp_per_season: float = Form(...),
                    session: Session = Depends(get_session)):
    p = session.get(Parcel, parcel_id)
    if not p:
        raise HTTPException(404)
    p.lease_price_egp_per_season = lease_price_egp_per_season
    session.add(p)
    session.commit()
    return RedirectResponse(f"/parcels/{parcel_id}", status_code=303)


@app.post("/parcels/{parcel_id}/invest")
def add_share(parcel_id: int, investor_id: int = Form(...),
              share_count: int = Form(...), session: Session = Depends(get_session)):
    p = session.get(Parcel, parcel_id)
    if not p:
        raise HTTPException(404)
    if not session.get(Investor, investor_id):
        raise HTTPException(400, "Unknown investor")
    sold = sum(s.share_count for s in p.shares)
    if sold + share_count > CONFIG.shares_per_parcel:
        raise HTTPException(400, f"Only {CONFIG.shares_per_parcel - sold} shares remaining")
    session.add(Share(parcel_id=parcel_id, investor_id=investor_id,
                      share_count=share_count,
                      price_per_share_egp=p.price_egp / CONFIG.shares_per_parcel))
    session.commit()
    return RedirectResponse(f"/parcels/{parcel_id}", status_code=303)


# ---------- AI triggers ----------

@app.post("/parcels/{parcel_id}/ai/valuate")
def ai_valuate(parcel_id: int, session: Session = Depends(get_session)):
    p = session.get(Parcel, parcel_id)
    if not p:
        raise HTTPException(404)
    undervaluation.apply(session, p)
    return RedirectResponse(f"/parcels/{parcel_id}", status_code=303)


@app.post("/parcels/{parcel_id}/ai/risk")
def ai_risk(parcel_id: int, session: Session = Depends(get_session)):
    p = session.get(Parcel, parcel_id)
    if not p:
        raise HTTPException(404)
    risk_model.apply(session, p)
    return RedirectResponse(f"/parcels/{parcel_id}", status_code=303)


# ---------- investors + matcher ----------

@app.get("/investors")
def investors_list(request: Request, session: Session = Depends(get_session)):
    investors = session.exec(select(Investor)).all()
    return templates.TemplateResponse(request, "investors.html", {"investors": investors})


@app.post("/investors")
def investors_create(name: str = Form(...), email: str = Form(""),
                     budget_egp: float = Form(...), horizon_years: int = Form(...),
                     risk_appetite: str = Form(...),
                     session: Session = Depends(get_session)):
    inv = Investor(name=name, email=email or None, budget_egp=budget_egp,
                   horizon_years=horizon_years, risk_appetite=risk_appetite)
    session.add(inv)
    session.commit()
    session.refresh(inv)
    return RedirectResponse(f"/investors/{inv.id}", status_code=303)


@app.get("/investors/{investor_id}")
def investor_detail(investor_id: int, request: Request, session: Session = Depends(get_session)):
    inv = session.get(Investor, investor_id)
    if not inv:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "investor.html", {"inv": inv})


@app.post("/investors/{investor_id}/match")
def investor_match(investor_id: int, request: Request, session: Session = Depends(get_session)):
    inv = session.get(Investor, investor_id)
    if not inv:
        raise HTTPException(404)
    matches = matcher.rank(session, inv)
    parcels_by_id = {p.id: p for p in session.exec(select(Parcel))}
    enriched = [{"parcel": parcels_by_id.get(m["parcel_id"]),
                 "fit_score": m["fit_score"],
                 "reasoning": m["reasoning"]} for m in matches if m["parcel_id"] in parcels_by_id]
    return templates.TemplateResponse(request, "matches.html", {"inv": inv, "matches": enriched})


# ---------- API ----------

@app.get("/api/parcels")
def api_parcels(session: Session = Depends(get_session)):
    return session.exec(select(Parcel)).all()
