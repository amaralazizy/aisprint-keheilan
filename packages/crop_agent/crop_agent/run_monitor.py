import asyncio
import json
from datetime import date
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# Add parent dir to path so we can import crop_agent
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from crop_agent.clients.llm import LLMClient
from crop_agent.models import SingleCropEvaluation
from crop_agent.monitoring.models import FarmerReport
from crop_agent.monitoring.analyzer import MonitoringAnalyzer

async def main():
    llm = LLMClient()
    analyzer = MonitoringAnalyzer(llm)
    
    # Mock baseline prediction
    baseline = SingleCropEvaluation(
        crop="wheat",
        confidence_pct=80,
        score_breakdown={"overall": 0.8},
        yield_range_t_per_feddan=(2.5, 3.8),
        revenue_egp_per_feddan=(24000.0, 30000.0, 35000.0),
        amendment_plan=[],
        pest_calendar=[],
        pros=["Good soil"],
        cons=["Heat risk"],
        recommendation_text="Highly recommended."
    )
    
    # Simulated farmer reports
    reports = [
        "The crop is growing perfectly, no issues. The weather has been nice and watering is regular.",
        "The wheat looks okay, but I noticed some yellow bugs spreading in the eastern section.",
        "A severe locust attack has destroyed a huge chunk of my wheat crop, it looks very bad."
    ]

    for i, text in enumerate(reports):
        report = FarmerReport(
            report_date=date.today(),
            crop="wheat",
            text=text
        )
        
        print(f"\n==========================================")
        print(f"REPORT {i+1}: {text}")
        print(f"==========================================")
        
        result = await analyzer.analyze_report(report, baseline)
        
        print(f"Original Yield: {result.original_yield_range_t_per_feddan} tons/feddan")
        print(f"Updated Yield:  {result.updated_yield_range_t_per_feddan} tons/feddan")
        print(f"Original Rev:   {result.original_revenue_egp_per_feddan} EGP")
        print(f"Updated Rev:    {result.updated_revenue_egp_per_feddan} EGP")
        print(f"Reasoning:      {result.adjustment_reasoning}")
        print(f"")

if __name__ == "__main__":
    asyncio.run(main())
