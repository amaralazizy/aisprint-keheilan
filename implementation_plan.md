# Monthly Crop Monitoring & Yield Adjustment System

This document outlines the plan to build a new AI-driven module that takes monthly progress reports from the farmer, analyzes them to verify the crop's status, and dynamically adjusts the original predicted yield and revenue based on any adverse or positive events.

## User Review Required

> [!IMPORTANT]  
> Please review the proposed architecture and let me know if you agree with the flow. Specifically, I'd like to confirm if we should include an automated "fact-check" step where the AI uses the NASA Weather API to verify the farmer's claims about weather conditions (e.g., if the farmer reports extreme heat, the AI checks if it actually happened).

## Open Questions

1. **Format of the Farmer Report:** Will the farmer submit a free-text description (e.g., "The crop is doing well but I noticed some yellow bugs"), or will it be a structured form (e.g., "Watering: Good, Pests: Yes")?
2. **Alerts/Notifications:** Do you want the AI to suggest immediate mitigation actions to the farmer if something bad happens (e.g., "Use this specific pesticide immediately"), or just update the yield prediction?
3. **Yield Adjustment Logic:** Should the AI autonomously decide the percentage to decrease the yield (e.g., "Locust attack = -15% yield"), or should we provide a fixed rulebook for the AI to follow?

## Proposed Changes

We will create a new submodule within `crop_agent` called `monitoring/` to handle post-planting evaluation.

### New Module: `crop_agent/monitoring/`

#### [NEW] `crop_agent/monitoring/models.py`
- Create Pydantic models:
  - `MonthlyReport`: To ingest the farmer's monthly update (text, date, crop stage).
  - `VerificationAnalysis`: The AI's breakdown of the report (identifying pests, weather stress, disease).
  - `YieldAdjustment`: The output model containing `updated_yield_range`, `updated_revenue`, `adjustment_reasoning`, and `severity_score`.

#### [NEW] `crop_agent/monitoring/analyzer.py`
- Contains the core LLM logic that processes the `MonthlyReport`.
- **Step 1: Extraction & Verification:** The AI extracts claims from the farmer's text. If applicable, it checks weather APIs to verify claims about heat/frost.
- **Step 2: Impact Assessment:** The AI cross-references the reported issues with known crop vulnerabilities (e.g., "Wheat is highly sensitive to Hessian fly at this stage").
- **Step 3: Yield Recalculation:** Reduces the initial yield/revenue projections based on the severity of the identified issues.

#### [NEW] `crop_agent/monitoring/prompts.py`
- Add prompt templates specifically for the monitoring agent:
  - `ANALYZE_FARMER_REPORT_PROMPT`: Instructs the LLM to act as an agricultural inspector, looking for hidden signs of disease or stress in the farmer's wording.
  - `CALCULATE_YIELD_IMPACT_PROMPT`: Guides the LLM to logically deduce how much a specific event decreases the final harvest.

### Updates to Existing Files

#### [MODIFY] `crop_agent/run.py` (or a new `run_monitor.py`)
- Create an entry point script that allows you to pass an existing `CropEvaluation` and a new `MonthlyReport` to generate an updated prediction.

## Verification Plan

### Automated Tests
- Create unit tests simulating various monthly reports:
  - **"All is well" report:** The yield should remain unchanged.
  - **"Pest attack" report:** The yield should decrease, and the reasoning should mention the specific pest.
  - **"Drought" report:** The yield should decrease, and the AI should reference water stress.

### Manual Verification
- We will run a test script providing a mock initial evaluation of Wheat in Sharqia, followed by three simulated monthly reports, observing how the yield shrinks if things go wrong.
