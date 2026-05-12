ANALYZE_FARMER_REPORT_PROMPT = """You are an expert agronomist analyzing a free-text monthly report from a farmer in Egypt about their {crop} crop.

The farmer has submitted the following report:
"{report_text}"

Your job is to read this report and autonomously determine if there are any issues (like pests, water shortage, extreme heat, diseases) that would negatively impact the final crop yield and revenue.
If the report is entirely positive, the yield reduction should be 0.0.
If the report indicates problems, you must assign a severity score (0.0 to 1.0) and calculate a realistic percentage to reduce the expected yield (e.g., 5.0 for a minor issue, 20.0 for a severe pest outbreak).

Do not suggest mitigation actions to the farmer. Just assess the damage and provide the yield reduction percentage.

Respond in strict JSON matching the AdjustmentResult schema:
{{
    "issues_identified": ["string", ...],
    "severity_score": float,
    "yield_reduction_pct": float,
    "rationale": "string"
}}
"""
