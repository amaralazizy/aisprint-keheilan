import json
from ..clients.llm import LLMClient
from ..models import SingleCropEvaluation
from .models import FarmerReport, AdjustmentResult, UpdatedPrediction
from .prompts import ANALYZE_FARMER_REPORT_PROMPT

class MonitoringAnalyzer:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def analyze_report(self, report: FarmerReport, baseline: SingleCropEvaluation) -> UpdatedPrediction:
        prompt = ANALYZE_FARMER_REPORT_PROMPT.format(
            crop=report.crop,
            report_text=report.text
        )
        
        try:
            data = await self.llm.chat_json(
                system="You are an agricultural yield forecaster.",
                user=prompt,
                temperature=0.1
            )
            adjustment = AdjustmentResult(**data)
        except Exception as e:
            # Fallback if parsing fails
            adjustment = AdjustmentResult(
                issues_identified=["Error parsing LLM response"],
                severity_score=0.0,
                yield_reduction_pct=0.0,
                rationale=f"Fallback due to error: {e}"
            )
            
        # Calculate updated yield
        reduction_factor = 1.0 - (adjustment.yield_reduction_pct / 100.0)
        
        orig_yield = baseline.yield_range_t_per_feddan
        upd_yield = (orig_yield[0] * reduction_factor, orig_yield[1] * reduction_factor)
        
        orig_rev = baseline.revenue_egp_per_feddan
        upd_rev = (
            orig_rev[0] * reduction_factor,
            orig_rev[1] * reduction_factor,
            orig_rev[2] * reduction_factor
        )
        
        return UpdatedPrediction(
            crop=report.crop,
            original_yield_range_t_per_feddan=orig_yield,
            updated_yield_range_t_per_feddan=upd_yield,
            original_revenue_egp_per_feddan=orig_rev,
            updated_revenue_egp_per_feddan=upd_rev,
            adjustment_reasoning=adjustment.rationale
        )
