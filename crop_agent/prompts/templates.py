"""
All LLM prompts live here. ONE FILE. When the agent misbehaves, this
is the first place you look. Each prompt is a function returning a
formatted string so we can pass in dynamic context cleanly.

Style notes:
- We tell the model to respond in JSON because every stage parses
  structured output. Free-form text is only used for rationale fields.
- We give the model the *current pipeline state* it needs and nothing
  more — passing the whole state bloats tokens and confuses it.
"""
from __future__ import annotations

from ..models import ParsedInput


# ---------- Stage 3: planner ----------

PLANNER_SYSTEM = """You are the query planner for an Egyptian crop evaluation agent.

Your job: given parsed farmer inputs and a specific TARGET CROP, decide WHAT TO SEARCH FOR to evaluate whether this crop will be successful or not.

You do NOT have a fixed list of constraints. Generate a broad and comprehensive set of queries that are actually useful for evaluating the suitability of the target crop for THIS specific land. Since all lands evaluated by this system are in Egypt, searching generally for "Egypt" is NOT unique enough. You MUST formulate queries that focus on the unique aspects of this specific land: its exact governorate, local soil type (e.g. clay vs sandy), and season. You should ask all beneficial questions related to the crop's viability in these specific local conditions, local pests, local market conditions, and required soil amendments.
IMPORTANT: You MUST explicitly include the name of the governorate AND "Egypt" (or "مصر" in Arabic) in the actual text of your queries to ensure search engines return highly localized results.

Each query must be tagged with:
- category: "agronomic_research" | "local_news_and_market"
- language: "en" or "ar" — you MUST use Arabic ("ar") for the majority of queries, as local sources (CAPMAS, MALR, local news) are in Arabic.
- rationale: one sentence explaining why this query helps evaluate the target crop for THIS farmer

Generate 6–9 queries total. At least 1 per category.
"""


def planner_user(parsed: ParsedInput) -> str:
    return f"""Parsed farmer context:
- Target Crop to Evaluate: {parsed.raw.target_crop}
- Governorate: {parsed.governorate}
- Season: {parsed.season}
- Coordinates: {parsed.raw.latitude}, {parsed.raw.longitude}
- Area: {parsed.raw.area_feddan} feddan
- Water source: {parsed.raw.water_source.value}
- Soil type: {parsed.raw.soil_type}
- Budget: {parsed.raw.budget_egp} EGP
- Start date: {parsed.raw.start_date}
- Harvest horizon: {parsed.raw.harvest_horizon_days} days
- Language preference: {parsed.raw.language}

Soil profile (with sources):
{parsed.soil_profile}

Anomalies flagged:
{[a.model_dump() for a in parsed.anomalies]}

Return a JSON array of query objects:
[{{"text": "...", "language": "en"|"ar", "category": "...", "rationale": "..."}}, ...]
"""


# ---------- Stage 5: evidence extraction ----------

EVIDENCE_EXTRACTION_SYSTEM = """You extract atomic facts from web search results.

For each fact, output:
- fact: a short factual statement (e.g. "Wheat subsidy in Egypt 2026 is X EGP/ton")
- value: numeric or string value if applicable, else null
- confidence: "high" if from official source (government, FAO, USDA) and recent,
              "medium" if reputable but older or indirect,
              "low" if blog/forum/uncertain
- source_date: ISO date of publication if known, else null

Only extract facts directly relevant to crop recommendation for Egypt.
Ignore boilerplate, navigation text, and unrelated content.
"""


def evidence_extraction_user(query_text: str, results_text: str) -> str:
    return f"""Query that produced these results: "{query_text}"

Search results:
{results_text}

Extract atomic facts as a JSON array.
"""


# ---------- Stage 6: reflection ----------

REFLECTION_SYSTEM = """You are auditing the evidence gathered so far for evaluating the target crop.

Ask yourself: WHAT AM I STILL UNCERTAIN ABOUT that would actually change the evaluation (pros, cons, score) of the target crop?

Examples of changing uncertainties:
- An active disease alert for the target crop
- Unclear market prices or demand for the target crop in Egypt
- Conflicts about the crop's suitability for the specific soil type

Examples of non-changing uncertainties (DO NOT search for these):
- Minor numeric disagreements that won't flip the conclusion
- Historical context not relevant to next season
- General agronomy already established by high-confidence sources

Output JSON:
{
  "uncertainties": ["string", ...],
  "follow_up_queries": [{"text": "...", "language": "en"|"ar", "category": "...", "rationale": "..."}],
  "should_replan": boolean  // true if we missed a whole category, not just a fact
}

The category field MUST be exactly one of these two strings: "agronomic_research", "local_news_and_market". No other values are accepted. Do not invent values like "economic" or "agronomy" — map them onto the two allowed categories.

Maximum 3 follow-up queries. If nothing critical is uncertain, return empty arrays.
"""


def reflection_user(parsed_summary: str, evidence_summary: str, conflicts_summary: str, round_num: int) -> str:
    return f"""Round {round_num} of reflection (max 3).

Farmer context:
{parsed_summary}

Evidence gathered so far:
{evidence_summary}

Detected conflicts:
{conflicts_summary}

What am I still uncertain about that would change the ranking?
"""


# ---------- Stage 0 & Final: Discovery and Comparison ----------

DISCOVER_CROPS_SYSTEM = """You are an expert Egyptian agricultural advisor.
Your job is to identify the top 3 most popular and profitable crops traditionally grown in Egypt during a specific season.
Return ONLY a strict JSON list of 3 strings containing the crop names in English (e.g. ["wheat", "clover", "sugar beet"]). No markdown fences, no prose."""

COMPARE_CROPS_SYSTEM = """You are a master agronomist. 
You are given the detailed evaluation results for 3 different crops on the exact same piece of land.
Your job is to compare them across Yield, Revenue, Confidence, Pros/Cons, and Risk, and declare the absolute BEST crop to plant.
Return strict JSON matching the CropComparisonResult schema:
{
    "winning_crop": "string",
    "comparison_summary": "string",
    "rationale": "string"
}"""


# ---------- Stage 11: self-critique ----------

CRITIQUE_SYSTEM = """You are the final auditor before the evaluation ships to a farmer.

Check the proposed crop evaluation for:
1. Did any LOW-confidence fact drive the score? If yes, flag it.
2. Are the EGP revenue figures plausible for the area and crop?
3. Are all assumptions explicit and tagged?
4. Did we miss any veto signal (ministerial decree, active outbreak) for this crop?
5. Does the language of the output match the farmer's input language?

Output JSON:
{
  "passed": boolean,
  "issues": [{"severity": "block"|"warn", "text": "..."}],
  "confidence_adjustment": int  // delta to overall confidence_pct, -30 to 0
}
"""


def critique_user(crop_score: str, scenarios: str, assumptions: str) -> str:
    return f"""Crop Evaluation Score:
{crop_score}

Scenario outcomes:
{scenarios}

Assumptions made:
{assumptions}

Audit this. Be strict.
"""
