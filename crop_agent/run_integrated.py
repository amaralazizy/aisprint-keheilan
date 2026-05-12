import asyncio
import os
import sys
from datetime import date
from pathlib import Path

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

# Add parent dir to path so we can import crop_agent
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from crop_agent.clients.llm import LLMClient
from crop_agent.clients.search import StubSearchClient, TavilySearchClient
from crop_agent.config import CONFIG
from crop_agent.pipeline import run_pipeline
from crop_agent.models import RawInput, WaterSource
from crop_agent.monitoring.models import FarmerReport
from crop_agent.monitoring.analyzer import MonitoringAnalyzer

async def main():
    # 1. Setup real initial data (e.g. Mango in Ismailia)
    raw_input = RawInput(
        target_crop="mango",
        latitude=30.6043, # Ismailia
        longitude=32.2723,
        area_feddan=10.0,
        water_source=WaterSource.NILE_CANAL,
        soil_type="sandy",
        budget_egp=100000.0,
        start_date=date(2026, 3, 1),
        harvest_horizon_days=180,
        language="en"
    )

    reasoner = LLMClient(model=CONFIG.reasoner_model)
    worker = LLMClient(model=CONFIG.worker_model)
    
    if os.getenv("SEARCH_API_KEY"):
        search = TavilySearchClient()
    else:
        search = StubSearchClient()

    print("==========================================")
    print("STEP 1: RUNNING FULL CROP EVALUATION PIPELINE")
    print("==========================================")
    print(f"Evaluating {raw_input.target_crop} on {raw_input.area_feddan} feddans...")
    
    # Run the full pipeline
    state = await run_pipeline(raw_input, reasoner=reasoner, worker=worker, search=search)
    
    baseline = state.output.evaluation
    
    if not baseline:
        print("Pipeline failed to generate an evaluation.")
        return

    print("\n--- BASELINE EVALUATION ---")
    print(f"Crop: {baseline.crop}")
    print(f"Confidence: {baseline.confidence_pct}%")
    print(f"Yield Range: {baseline.yield_range_t_per_feddan} t/feddan")
    print(f"Revenue Range: {baseline.revenue_egp_per_feddan} EGP/feddan")
    print(f"Pros: {baseline.pros}")
    print(f"Cons: {baseline.cons}")

    print("\n==========================================")
    print("STEP 2: PROCESSING MONTHLY REPORTS")
    print("==========================================")
    
    analyzer = MonitoringAnalyzer(reasoner)
    
    # Simulated sequential monthly reports
    reports = [
        "Month 1: The mango trees are flowering well. Weather is optimal, and we watered them properly.",
        "Month 2: We had a sudden heatwave that caused many of the flowers to drop prematurely. Some leaves are looking scorched.",
        "Month 3: Found some fruit flies in the eastern part of the orchard. Trying to spray, but it might have caused some damage."
    ]
    
    current_baseline = baseline.model_copy()
    
    for i, text in enumerate(reports):
        report = FarmerReport(
            report_date=date.today(),
            crop=baseline.crop,
            text=text
        )
        
        print(f"\n[REPORT {i+1}] {text}")
        
        # Analyze the report
        result = await analyzer.analyze_report(report, current_baseline)
        
        print(f"Reasoning: {result.adjustment_reasoning}")
        print(f"New Yield: {result.updated_yield_range_t_per_feddan} t/feddan")
        print(f"New Rev:   {result.updated_revenue_egp_per_feddan} EGP/feddan")
        
        # Update current baseline for the next iteration (Cumulative effect)
        current_baseline.yield_range_t_per_feddan = result.updated_yield_range_t_per_feddan
        current_baseline.revenue_egp_per_feddan = result.updated_revenue_egp_per_feddan

if __name__ == "__main__":
    asyncio.run(main())
