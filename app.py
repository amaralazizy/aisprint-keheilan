import streamlit as st
import asyncio
import os
import sys
import json
from datetime import date
from dotenv import load_dotenv
load_dotenv()

# Setup paths so we can import both models
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
CROP_DIR = os.path.join(ROOT_DIR, "packages", "crop_agent")
if CROP_DIR not in sys.path:
    sys.path.insert(0, CROP_DIR)
MODEL1_DIR = os.path.join(ROOT_DIR, "packages", "model1_land")
if MODEL1_DIR not in sys.path:
    sys.path.insert(0, MODEL1_DIR)

# Import Crop Agent Models (Our work)
from crop_agent.models import RawInput, WaterSource, CropComparisonResult
from crop_agent.pipeline import run_pipeline
from crop_agent.clients.llm import LLMClient
from crop_agent.clients.search import StubSearchClient, TavilySearchClient
from crop_agent.config import CONFIG as CROP_CONFIG
from crop_agent.stages.stage_0_discover import discover_top_crops
from crop_agent.prompts.templates import COMPARE_CROPS_SYSTEM
from crop_agent.monitoring.analyzer import MonitoringAnalyzer
from crop_agent.monitoring.models import FarmerReport

# Import Model 1 (Friends' work)
from model1_land.db import engine, init_db
from model1_land.models import Parcel, Investor
from model1_land.ai import undervaluation, risk_model, matcher
from sqlmodel import Session, select

st.set_page_config(page_title="Keheilan AI", page_icon="🌾", layout="wide")

st.sidebar.title("Keheilan AI Tools")
page = st.sidebar.radio("Select Tool", ["Crop Advisory (Our Model)", "Crop Monitoring (Our Model)", "Land Investment (Model 1)"])

# Helper function to run async pipeline in Streamlit
def run_async(coro):
    return asyncio.run(coro)

if page == "Crop Advisory (Our Model)":
    st.title("🌱 AI Crop Advisory")
    st.markdown("Evaluate a specific crop or let the AI find the absolute best crop for your farm.")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Farm Details")
        latitude = st.number_input("Latitude", value=30.5852)
        longitude = st.number_input("Longitude", value=31.0357)
        area_feddan = st.number_input("Area (Feddans)", value=5.0)
        soil_type = st.selectbox("Soil Type", ["clay", "sandy", "loamy", "unknown"])
        water_source = st.selectbox("Water Source", ["Nile Canal", "Groundwater well", "Rainfed"])
    
    with col2:
        st.subheader("Planning Details")
        budget = st.number_input("Budget (EGP)", value=50000.0)
        start_date = st.date_input("Start Date", value=date(2026, 11, 1))
        target_crop = st.text_input("Target Crop (Leave blank to let AI choose)", value="")
        
    ws_enum = WaterSource.NILE_CANAL
    if "well" in water_source.lower():
        ws_enum = WaterSource.GROUNDWATER_WELL
    elif "rain" in water_source.lower():
        ws_enum = WaterSource.RAINFED

    if st.button("🚀 Evaluate Farm", type="primary"):
        st.info("Starting AI Research... This will take a few minutes as it scours the web and evaluates conditions.")
        
        reasoner = LLMClient(model=CROP_CONFIG.reasoner_model)
        worker = LLMClient(model=CROP_CONFIG.worker_model)
        search = TavilySearchClient() if os.getenv("SEARCH_API_KEY") else StubSearchClient()
        
        base_input = RawInput(
            target_crop=target_crop if target_crop else "TBD",
            latitude=latitude,
            longitude=longitude,
            area_feddan=area_feddan,
            water_source=ws_enum,
            soil_type=soil_type,
            budget_egp=budget,
            start_date=start_date,
            harvest_horizon_days=180,
            language="en"
        )

        if target_crop.strip():
            # Run single crop evaluation
            st.write(f"Evaluating **{target_crop.upper()}**...")
            state = run_async(run_pipeline(base_input, reasoner=reasoner, worker=worker, search=search))
            
            if state.output and state.output.evaluation:
                eval_data = state.output.evaluation
                st.success("Evaluation Complete!")
                st.metric("Expected Yield (tons/feddan)", f"{eval_data.yield_range_t_per_feddan[0]} - {eval_data.yield_range_t_per_feddan[1]}")
                st.metric("Expected Revenue (EGP/feddan)", f"{eval_data.revenue_egp_per_feddan[0]} - {eval_data.revenue_egp_per_feddan[2]}")
                st.markdown("### Recommendation")
                st.write(eval_data.recommendation_text)
                
                st.markdown("### Pros & Cons")
                col_pros, col_cons = st.columns(2)
                with col_pros:
                    st.success("**Pros:**\n" + "\n".join([f"- {p}" for p in eval_data.pros]))
                with col_cons:
                    st.error("**Cons:**\n" + "\n".join([f"- {c}" for c in eval_data.cons]))
            else:
                st.error("Evaluation failed to generate.")
        else:
            # Run Best Crop Finder
            st.write("No crop specified. Discovering top seasonal crops...")
            top_crops = run_async(discover_top_crops("Winter", worker))
            st.write(f"Top crops discovered: **{', '.join(top_crops)}**")
            
            evaluations = {}
            progress_bar = st.progress(0)
            
            for i, crop in enumerate(top_crops):
                st.write(f"Evaluating {crop}...")
                spec_input = base_input.model_copy(update={"target_crop": crop})
                state = run_async(run_pipeline(spec_input, reasoner=reasoner, worker=worker, search=search))
                if state.output and state.output.evaluation:
                    evaluations[crop] = state.output.evaluation
                progress_bar.progress((i + 1) / len(top_crops))
                
            if evaluations:
                st.write("Comparing crops to find the winner...")
                evals_json = json.dumps([e.model_dump() for e in evaluations.values()], default=str)
                user_prompt = f"Here are the evaluations for {len(evaluations)} crops:\n{evals_json}\n\nPlease determine the absolute best crop for this farmer."
                
                try:
                    comp_data = run_async(reasoner.chat_json(COMPARE_CROPS_SYSTEM, user_prompt, temperature=0.2))
                    res = CropComparisonResult(**comp_data)
                    st.success(f"🏆 The Winner is: {res.winning_crop.upper()}")
                    st.markdown("### Summary")
                    st.write(res.comparison_summary)
                    st.markdown("### AI Rationale")
                    st.write(res.rationale)
                except Exception as e:
                    st.error(f"Failed to compare: {e}")

elif page == "Crop Monitoring (Our Model)":
    st.title("📈 AI Crop Monitoring")
    st.markdown("Enter your farm details and a monthly report. The AI will evaluate the baseline potential of your crop, and then immediately adjust it based on your real-world update.")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Farm Details")
        mon_crop = st.text_input("Target Crop", value="Mango")
        latitude = st.number_input("Latitude", value=30.5852, key="mon_lat")
        longitude = st.number_input("Longitude", value=31.0357, key="mon_lon")
        area_feddan = st.number_input("Area (Feddans)", value=5.0, key="mon_area")
        soil_type = st.selectbox("Soil Type", ["clay", "sandy", "loamy", "unknown"], key="mon_soil")
        water_source = st.selectbox("Water Source", ["Nile Canal", "Groundwater well", "Rainfed"], key="mon_water")
        budget = st.number_input("Budget (EGP)", value=50000.0, key="mon_budget")
    
    with col2:
        st.subheader("Farmer Report")
        report_text = st.text_area("What happened this month?", value="Found some fruit flies in the eastern part of the orchard. Trying to spray.", height=200)

    ws_enum = WaterSource.NILE_CANAL
    if "well" in water_source.lower():
        ws_enum = WaterSource.GROUNDWATER_WELL
    elif "rain" in water_source.lower():
        ws_enum = WaterSource.RAINFED

    if st.button("🔍 Generate Baseline & Analyze Report", type="primary"):
        st.info("1️⃣ Generating AI Baseline (Running full crop advisory pipeline)...")
        
        reasoner = LLMClient(model=CROP_CONFIG.reasoner_model)
        worker = LLMClient(model=CROP_CONFIG.worker_model)
        search = TavilySearchClient() if os.getenv("SEARCH_API_KEY") else StubSearchClient()
        
        base_input = RawInput(
            target_crop=mon_crop,
            latitude=latitude, longitude=longitude, area_feddan=area_feddan,
            water_source=ws_enum, soil_type=soil_type, budget_egp=budget,
            start_date=date(2026, 11, 1), harvest_horizon_days=180, language="en"
        )
        
        state = run_async(run_pipeline(base_input, reasoner=reasoner, worker=worker, search=search))
        
        if state.output and state.output.evaluation:
            baseline_eval = state.output.evaluation
            
            st.info("2️⃣ Analyzing Farmer Report Impact...")
            report_obj = FarmerReport(report_date=date.today(), crop=mon_crop, text=report_text)
            analyzer = MonitoringAnalyzer(reasoner)
            upd = run_async(analyzer.analyze_report(report_obj, baseline_eval))
            
            st.success("✅ Analysis Complete!")
            st.markdown("---")
            
            col_base, col_upd = st.columns(2)
            with col_base:
                st.subheader("📊 Baseline Projections")
                st.write(f"**Expected Yield:** {baseline_eval.yield_range_t_per_feddan[0]:.2f} - {baseline_eval.yield_range_t_per_feddan[1]:.2f} t/feddan")
                st.write(f"**Expected Revenue:** {baseline_eval.revenue_egp_per_feddan[0]:,.0f} - {baseline_eval.revenue_egp_per_feddan[2]:,.0f} EGP")
                
            with col_upd:
                st.subheader("📉 Updated Projections (After Report)")
                st.write(f"**New Yield:** {upd.updated_yield_range_t_per_feddan[0]:.2f} - {upd.updated_yield_range_t_per_feddan[1]:.2f} t/feddan")
                st.write(f"**New Revenue:** {upd.updated_revenue_egp_per_feddan[0]:,.0f} - {upd.updated_revenue_egp_per_feddan[2]:,.0f} EGP")
            
            st.error(f"**AI Rationale for Adjustment:** {upd.adjustment_reasoning}")
        else:
            st.error("Failed to generate baseline evaluation.")

elif page == "Land Investment (Model 1)":
    st.title("💰 AI Land Valuation & Risk (Model 1)")
    st.markdown("Use the original AI modules to evaluate existing parcels for investment.")
    
    init_db()  # Ensure database tables exist
    
    with Session(engine) as session:
        parcels = session.exec(select(Parcel)).all()
        
        if not parcels:
            st.warning("No parcels found in the database. Run `cd packages/model1_land && python -m model1_land.seed` first.")
        else:
            parcel_options = {f"ID: {p.id} - {p.area_feddan} feddan in {p.governorate}": p for p in parcels}
            selected_str = st.selectbox("Select a Parcel to Evaluate", list(parcel_options.keys()))
            selected_parcel = parcel_options[selected_str]
            
            st.markdown(f"**Ask Price:** {selected_parcel.price_egp:,.0f} EGP")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Evaluate Undervaluation"):
                    with st.spinner("Valuating land vs comparable properties..."):
                        undervaluation.apply(session, selected_parcel)
                    st.success("Valuation Complete!")
                    st.metric("Fair Price Estimate", f"{selected_parcel.fair_price_egp:,.0f} EGP")
                    st.metric("Undervaluation %", f"{selected_parcel.undervaluation_pct}%")
                    st.info(f"Reasoning: {selected_parcel.undervaluation_reasoning}")
                    
            with col2:
                if st.button("Assess Risk Level"):
                    with st.spinner("Analyzing risk factors..."):
                        risk_model.apply(session, selected_parcel)
                    st.success("Risk Assessment Complete!")
                    st.metric("Risk Tier", selected_parcel.risk_tier)
                    st.metric("Risk Score", selected_parcel.risk_score)
                    if selected_parcel.risk_factors_json:
                        st.write("Factors:", json.loads(selected_parcel.risk_factors_json))
                    st.info(f"Reasoning: {selected_parcel.risk_reasoning}")
