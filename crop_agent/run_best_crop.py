import asyncio
import os
import sys
import json
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
from crop_agent.models import RawInput, WaterSource, CropComparisonResult
from crop_agent.stages.stage_0_discover import discover_top_crops
from crop_agent.prompts.templates import COMPARE_CROPS_SYSTEM

async def main():
    # 1. Base input without a specific target crop
    base_input = RawInput(
        target_crop="TBD", # Placeholder
        latitude=30.5852, # Menoufia
        longitude=31.0357,
        area_feddan=5.0,
        water_source=WaterSource.NILE_CANAL,
        soil_type="clay",
        budget_egp=50000.0,
        start_date=date(2026, 11, 1),
        harvest_horizon_days=180,
        language="en"
    )

    reasoner = LLMClient(model=CONFIG.reasoner_model)
    worker = LLMClient(model=CONFIG.worker_model)
    search = TavilySearchClient() if os.getenv("SEARCH_API_KEY") else StubSearchClient()

    print("==========================================")
    print("STEP 1: DISCOVERING TOP CROPS FOR SEASON")
    print("==========================================")
    
    top_crops = await discover_top_crops("Winter (Shitawi)", worker)
    print(f"Top 3 crops discovered: {top_crops}")

    evaluations = {}

    print("\n==========================================")
    print("STEP 2: RUNNING PIPELINE FOR EACH CROP")
    print("==========================================")
    
    for crop in top_crops:
        print(f"\n---> Evaluating: {crop.upper()} <---")
        # Create a specific input for this crop
        specific_input = base_input.model_copy(update={"target_crop": crop})
        
        # Run pipeline
        state = await run_pipeline(specific_input, reasoner=reasoner, worker=worker, search=search)
        
        if state.output and state.output.evaluation:
            evaluations[crop] = state.output.evaluation
            print(f"[{crop.upper()}] Done! Confidence: {state.output.evaluation.confidence_pct}%")
        else:
            print(f"[{crop.upper()}] Failed to generate an evaluation.")

    if not evaluations:
        print("All evaluations failed. Exiting.")
        return

    print("\n==========================================")
    print("STEP 3: COMPARING AND SELECTING BEST CROP")
    print("==========================================")
    
    # Prepare data for LLM
    evals_json = json.dumps([e.model_dump() for e in evaluations.values()], default=str)
    
    user_prompt = f"Here are the evaluations for {len(evaluations)} crops:\n{evals_json}\n\nPlease determine the absolute best crop for this farmer."
    
    try:
        comparison_data = await reasoner.chat_json(
            system=COMPARE_CROPS_SYSTEM,
            user=user_prompt,
            temperature=0.2
        )
        result = CropComparisonResult(**comparison_data)
        
        print("\n🏆 THE WINNER IS 🏆")
        print(f"Crop: {result.winning_crop.upper()}")
        print(f"\nSummary: {result.comparison_summary}")
        print(f"\nRationale: {result.rationale}")
        
    except Exception as e:
        print(f"Failed to compare crops: {e}")

if __name__ == "__main__":
    asyncio.run(main())
