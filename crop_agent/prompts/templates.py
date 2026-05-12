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

PLANNER_SYSTEM = """You are the query planner for an Egyptian crop recommendation agent.

Your job: given parsed farmer inputs and any anomalies, decide WHAT TO SEARCH FOR.

You do NOT have a fixed list. Generate queries that are actually useful for THIS
farmer in THIS governorate at THIS time. Egypt-specific signals matter:
- Ministerial decrees that restrict crops by governorate
- EGP devaluation and fertiliser import costs
- Nile flow bulletins (GERD downstream effects)
- FAO EMPRES outbreak alerts
- MALR Arabic extension bulletins

Each query must be tagged with:
- category: "fixed_knowledge" | "live_signal" | "arabic_ministry"
- language: "en" or "ar" — pick Arabic for MALR/CAPMAS/MWRI sources
- rationale: one sentence explaining why this query, for THIS farmer

Generate 6–9 queries total. At least 1 per category.
"""


def planner_user(parsed: ParsedInput) -> str:
    return f"""Parsed farmer context:
- Governorate: {parsed.governorate}
- Season: {parsed.season}
- Coordinates: {parsed.raw.latitude}, {parsed.raw.longitude}
- Area: {parsed.raw.area_feddan} feddan
- Water source: {parsed.raw.water_source.value}
- Soil type: {parsed.raw.soil_type}
- Goal: {parsed.raw.goal.value}
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

REFLECTION_SYSTEM = """You are auditing the evidence gathered so far for a crop recommendation.

Ask yourself: WHAT AM I STILL UNCERTAIN ABOUT that would actually change the ranking?

Examples of changing uncertainties:
- A ministerial decree we haven't verified for this governorate
- Current EGP/USD rate for revenue calculations
- An active disease alert for a top candidate crop
- Conflicting yield numbers between sources

Examples of non-changing uncertainties (DO NOT search for these):
- Minor numeric disagreements that won't flip ranks
- Historical context not relevant to next season
- General agronomy already established by high-confidence sources

Output JSON:
{
  "uncertainties": ["string", ...],
  "follow_up_queries": [{"text": "...", "language": "en"|"ar", "category": "...", "rationale": "..."}],
  "should_replan": boolean  // true if we missed a whole category, not just a fact
}

The category field MUST be exactly one of these three strings: "fixed_knowledge", "live_signal", "arabic_ministry". No other values are accepted. Do not invent values like "economic" or "agronomy" — map them onto the three allowed categories.

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


# ---------- Stage 11: self-critique ----------

CRITIQUE_SYSTEM = """You are the final auditor before recommendations ship to a farmer.

Check the proposed ranking for:
1. Did any LOW-confidence fact drive the #1 rank? If yes, flag it.
2. Are the EGP revenue figures plausible for the area and crop?
3. Are all assumptions explicit and tagged?
4. Did we miss any veto signal (ministerial decree, active outbreak)?
5. Does the language of the output match the farmer's input language?

Output JSON:
{
  "passed": boolean,
  "issues": [{"severity": "block"|"warn", "text": "..."}],
  "confidence_adjustment": int  // delta to overall confidence_pct, -30 to 0
}
"""


def critique_user(top_score: str, alt_scores: str, scenarios: str, assumptions: str) -> str:
    return f"""Top candidate:
{top_score}

Alternatives:
{alt_scores}

Scenario outcomes:
{scenarios}

Assumptions made:
{assumptions}

Audit this. Be strict.
"""
