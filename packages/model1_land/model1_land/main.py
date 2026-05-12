import asyncio
import json
from pathlib import Path
from datetime import date
from fastapi import FastAPI, Depends, Form, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from .db import init_db, get_session
from .models import Parcel, LeaseRecord, Investor, Share, Payout, CropAdvice
from .config import CONFIG
from .auth import current_investor, make_session_cookie, COOKIE_NAME
from .governorates import centroid
from .ai import undervaluation, risk_model, matcher

app = FastAPI(title="Keheilan — Fractional Agriculture")
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


@app.on_event("startup")
def on_startup() -> None:
    init_db()


def base_ctx(request: Request, inv: Investor | None) -> dict:
    return {"current_investor": inv, "request": request}


# ---------- landing + about ----------

@app.get("/")
def landing(request: Request,
            session: Session = Depends(get_session),
            inv: Investor | None = Depends(current_investor)):
    parcels = session.exec(select(Parcel)).all()
    investors = session.exec(select(Investor)).all()
    total_aum = sum(s.share_count * s.price_per_share_egp
                    for p in parcels for s in p.shares)
    high_count = sum(1 for p in parcels if p.risk_tier == "High")
    low_count = sum(1 for p in parcels if p.risk_tier == "Low")
    return templates.TemplateResponse(request, "landing.html", {
        **base_ctx(request, inv),
        "parcels_count": len(parcels),
        "investors_count": len(investors),
        "total_aum": total_aum,
        "high_count": high_count,
        "low_count": low_count,
        "featured": parcels[:3],
    })


@app.get("/about")
def about(request: Request, inv: Investor | None = Depends(current_investor)):
    return templates.TemplateResponse(request, "about.html", base_ctx(request, inv))


# ---------- login ----------

@app.get("/login")
def login_page(request: Request,
               session: Session = Depends(get_session),
               inv: Investor | None = Depends(current_investor)):
    investors = session.exec(select(Investor)).all()
    return templates.TemplateResponse(request, "login.html",
        {**base_ctx(request, inv), "investors": investors})


@app.post("/login")
def login_submit(response: Response,
                 investor_id: int = Form(...),
                 session: Session = Depends(get_session)):
    inv = session.get(Investor, investor_id)
    if not inv:
        raise HTTPException(404, "Investor not found")
    resp = RedirectResponse(f"/investors/{inv.id}", status_code=303)
    resp.set_cookie(COOKIE_NAME, make_session_cookie(inv.id),
                    httponly=True, samesite="lax", max_age=60*60*24*7)
    return resp


@app.post("/logout")
def logout():
    resp = RedirectResponse("/", status_code=303)
    resp.delete_cookie(COOKIE_NAME)
    return resp


# ---------- parcels ----------

@app.get("/parcels")
def parcels_list(request: Request, tier: str | None = None,
                 session: Session = Depends(get_session),
                 inv: Investor | None = Depends(current_investor)):
    q = select(Parcel)
    if tier in {"High", "Medium", "Low"}:
        q = q.where(Parcel.risk_tier == tier)
    parcels = session.exec(q).all()
    return templates.TemplateResponse(request, "parcels.html", {
        **base_ctx(request, inv),
        "parcels": parcels, "tier": tier,
        "shares_per_parcel": CONFIG.shares_per_parcel,
    })


@app.get("/parcels/{parcel_id}")
def parcel_detail(parcel_id: int, request: Request,
                  session: Session = Depends(get_session),
                  inv: Investor | None = Depends(current_investor)):
    p = session.get(Parcel, parcel_id)
    if not p:
        raise HTTPException(404)
    sold_shares = sum(s.share_count for s in p.shares)
    factors = json.loads(p.risk_factors_json) if p.risk_factors_json else []
    total_payouts = sum(po.amount_egp for po in p.payouts)
    advice = session.exec(
        select(CropAdvice).where(CropAdvice.parcel_id == parcel_id)
        .order_by(CropAdvice.created_at.desc())
    ).first()
    return templates.TemplateResponse(request, "parcel.html", {
        **base_ctx(request, inv),
        "p": p,
        "sold_shares": sold_shares,
        "remaining_shares": CONFIG.shares_per_parcel - sold_shares,
        "shares_per_parcel": CONFIG.shares_per_parcel,
        "price_per_share": p.price_egp / CONFIG.shares_per_parcel,
        "risk_factors": factors,
        "total_payouts": total_payouts,
        "advice": advice,
    })


@app.post("/parcels/{parcel_id}/lease")
def add_lease(parcel_id: int, farmer_name: str = Form(...), season: str = Form(...),
              start_date: date = Form(...), end_date: date = Form(...),
              session: Session = Depends(get_session)):
    p = session.get(Parcel, parcel_id)
    if not p:
        raise HTTPException(404)
    if p.lease_price_egp_per_season <= 0:
        raise HTTPException(400, "Lease price not set by the company.")
    lease = LeaseRecord(parcel_id=parcel_id, farmer_name=farmer_name, season=season,
                        rent_egp=p.lease_price_egp_per_season,
                        start_date=start_date, end_date=end_date)
    session.add(lease); session.commit(); session.refresh(lease)
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
    session.add(p); session.commit()
    return RedirectResponse(f"/parcels/{parcel_id}", status_code=303)


@app.post("/parcels/{parcel_id}/invest")
def add_share(parcel_id: int, share_count: int = Form(...),
              session: Session = Depends(get_session),
              inv: Investor | None = Depends(current_investor)):
    if not inv:
        raise HTTPException(401, "Log in to invest.")
    p = session.get(Parcel, parcel_id)
    if not p:
        raise HTTPException(404)
    sold = sum(s.share_count for s in p.shares)
    if sold + share_count > CONFIG.shares_per_parcel:
        raise HTTPException(400, f"Only {CONFIG.shares_per_parcel - sold} shares remaining")
    session.add(Share(parcel_id=parcel_id, investor_id=inv.id,
                      share_count=share_count,
                      price_per_share_egp=p.price_egp / CONFIG.shares_per_parcel))
    session.commit()
    return RedirectResponse(f"/parcels/{parcel_id}", status_code=303)


# ---------- AI triggers (#1, #2) ----------

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


# ---------- Crop Advisor (full crop_agent pipeline) ----------

@app.post("/parcels/{parcel_id}/advisor")
async def run_crop_advisor(parcel_id: int,
                           target_crop: str = Form(...),
                           water_source: str = Form(...),
                           soil_type: str = Form(...),
                           budget_egp: float = Form(...),
                           start_date: date = Form(...),
                           harvest_horizon_days: int = Form(180),
                           language: str = Form("en"),
                           session: Session = Depends(get_session)):
    p = session.get(Parcel, parcel_id)
    if not p:
        raise HTTPException(404)

    from crop_agent.pipeline import run_pipeline
    from crop_agent.clients.llm import LLMClient
    from crop_agent.clients.search import StubSearchClient
    from crop_agent.config import CONFIG as CA_CONFIG
    from crop_agent.models import RawInput, WaterSource

    lat, lon = centroid(p.governorate)
    raw = RawInput(
        target_crop=target_crop,
        latitude=lat, longitude=lon,
        area_feddan=p.area_feddan,
        water_source=WaterSource(water_source),
        soil_type=soil_type,
        budget_egp=budget_egp,
        start_date=start_date,
        harvest_horizon_days=harvest_horizon_days,
        language=language,
    )
    reasoner = LLMClient(model=CA_CONFIG.reasoner_model)
    worker = LLMClient(model=CA_CONFIG.worker_model)
    state = await run_pipeline(raw, reasoner=reasoner, worker=worker, search=StubSearchClient())

    out = state.output
    rec = out.evaluation.recommendation_text if out and out.evaluation else "No recommendation."
    narrative = rec  # crop_agent's run.py writes a separate narrative; for demo, use rec text
    confidence = out.overall_confidence_pct if out else 0

    advice = CropAdvice(parcel_id=parcel_id, target_crop=target_crop,
                        recommendation_text=rec, narrative=narrative,
                        raw_input_json=raw.model_dump_json(),
                        overall_confidence_pct=confidence)
    session.add(advice); session.commit()
    return RedirectResponse(f"/parcels/{parcel_id}", status_code=303)


# ---------- investors + matcher ----------

@app.get("/investors")
def investors_list(request: Request,
                   session: Session = Depends(get_session),
                   inv: Investor | None = Depends(current_investor)):
    investors = session.exec(select(Investor)).all()
    return templates.TemplateResponse(request, "investors.html",
        {**base_ctx(request, inv), "investors": investors})


@app.post("/investors")
def investors_create(name: str = Form(...), email: str = Form(""),
                     budget_egp: float = Form(...), horizon_years: int = Form(...),
                     risk_appetite: str = Form(...),
                     session: Session = Depends(get_session)):
    inv = Investor(name=name, email=email or None, budget_egp=budget_egp,
                   horizon_years=horizon_years, risk_appetite=risk_appetite)
    session.add(inv); session.commit(); session.refresh(inv)
    return RedirectResponse(f"/investors/{inv.id}", status_code=303)


@app.get("/investors/{investor_id}")
def investor_detail(investor_id: int, request: Request,
                    session: Session = Depends(get_session),
                    inv: Investor | None = Depends(current_investor)):
    target = session.get(Investor, investor_id)
    if not target:
        raise HTTPException(404)
    return templates.TemplateResponse(request, "investor.html",
        {**base_ctx(request, inv), "inv": target})


@app.post("/investors/{investor_id}/match")
def investor_match(investor_id: int, request: Request,
                   session: Session = Depends(get_session),
                   inv: Investor | None = Depends(current_investor)):
    target = session.get(Investor, investor_id)
    if not target:
        raise HTTPException(404)
    matches = matcher.rank(session, target)
    parcels_by_id = {p.id: p for p in session.exec(select(Parcel))}
    enriched = [{"parcel": parcels_by_id.get(m["parcel_id"]),
                 "fit_score": m["fit_score"],
                 "reasoning": m["reasoning"]}
                for m in matches if m["parcel_id"] in parcels_by_id]
    return templates.TemplateResponse(request, "matches.html",
        {**base_ctx(request, inv), "inv": target, "matches": enriched})


# ---------- API ----------

@app.get("/api/parcels")
def api_parcels(session: Session = Depends(get_session)):
    return session.exec(select(Parcel)).all()
