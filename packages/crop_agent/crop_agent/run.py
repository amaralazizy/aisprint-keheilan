"""
Local runner. Loads .env, runs the pipeline on a sample farmer, prints output.

Usage (from the repo root, i.e. the parent of the inner crop_agent/ package):
    python -m crop_agent.run                  # sample_sharqia_winter
    python -m crop_agent.run minya            # sample_minya_water_stress
    python -m crop_agent.run salinity         # sample_salinity_blocked
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import os

from crop_agent.clients.llm import LLMClient
from crop_agent.clients.search import StubSearchClient, TavilySearchClient
from crop_agent.config import CONFIG
from crop_agent.pipeline import run_pipeline
from crop_agent.tests.fixtures import (
    sample_minya_water_stress,
    sample_salinity_blocked,
    sample_sharqia_winter,
)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler("full_execution.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout)
    ]
)

SAMPLES = {
    "sharqia": sample_sharqia_winter,
    "minya": sample_minya_water_stress,
    "salinity": sample_salinity_blocked,
}


async def main() -> None:
    key = sys.argv[1] if len(sys.argv) > 1 else "sharqia"
    raw = SAMPLES[key]()
    reasoner = LLMClient(model=CONFIG.reasoner_model)
    worker = LLMClient(model=CONFIG.worker_model)
    print(f"Reasoner: {reasoner.model}\nWorker:   {worker.model}")

    if os.getenv("SEARCH_API_KEY"):
        search = TavilySearchClient()
        print("Search:   Tavily (real web search)\n")
    else:
        search = StubSearchClient()
        print(
            "Search:   StubSearchClient (offline canned data) — "
            "set SEARCH_API_KEY=tvly-... in .env for real search.\n"
        )

    state = await run_pipeline(raw, reasoner=reasoner, worker=worker, search=search)

    narrative = await _write_narrative(reasoner, state)

    def _dump(obj):
        if hasattr(obj, "model_dump"):
            return obj.model_dump(mode="json")
        return obj

    payload = state.output.model_dump(mode="json")
    justification = {
        "narrative": narrative,
        "parsed_input": _dump(state.parsed) if state.parsed else None,
        "planned_queries": [_dump(q) for q in state.queries],
        "evidence": [_dump(e) for e in state.evidence],
        "conflicts": [_dump(c) for c in state.conflicts],
        "scores": [_dump(s) for s in state.scores],
        "scenarios": [_dump(s) for s in state.scenarios],
        "assumptions": state.assumptions,
        "reflection_rounds": state.reflection_rounds,
        "reflection_log": state.reflection_log,
        "critique_passed": state.critique_passed,
        "trace": state.trace,
    }
    full = {"output": payload, "justification": justification}
    rendered = json.dumps(full, indent=2, ensure_ascii=False, default=str)

    out_dir = Path(__file__).parent / "outputs"
    out_dir.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = out_dir / f"{key}_{stamp}.json"
    out_path.write_text(rendered, encoding="utf-8")

    print("\n===== FINAL OUTPUT =====")
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    print("\n===== JUSTIFICATION =====")
    print(narrative)
    print(f"\nSaved (output + justification): {out_path}")

    # Generate the user-friendly narrative log
    uf_path = Path(__file__).parent.parent / "user_friendly_flow.md"
    _generate_user_friendly_log("full_execution.log", uf_path)
    print(f"Saved user-friendly flow: {uf_path}")


def _generate_user_friendly_log(log_file: str, out_file: Path) -> None:
    try:
        with open(log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Could not read log file for user-friendly format: {e}")
        return

    log_pattern = re.compile(r'^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) (DEBUG|INFO|WARNING|ERROR) ([a-zA-Z0-9_\.]+): (.*)')

    steps = []
    current_step = None

    for line in lines:
        match = log_pattern.match(line)
        if match:
            timestamp, level, module, message = match.groups()
            if 'LLM Chat Request:' in message:
                current_step = {'type': 'LLM Request', 'content': []}
                steps.append(current_step)
            elif 'LLM Chat Response:' in message:
                current_step = {'type': 'LLM Response', 'content': []}
                steps.append(current_step)
            elif 'Tavily search request:' in message:
                steps.append({'type': 'Web Search Request', 'content': [message.replace('Tavily search request: ', '')]})
                current_step = None
            elif 'Tavily search response:' in message:
                steps.append({'type': 'Web Search Response', 'content': [message.replace('Tavily search response: ', '')]})
                current_step = None
            elif 'SoilGrids query request:' in message:
                steps.append({'type': 'Soil API Request', 'content': [message.replace('SoilGrids query request: ', '')]})
                current_step = None
            elif 'SoilGrids query response:' in message:
                steps.append({'type': 'Soil API Response', 'content': [message.replace('SoilGrids query response: ', '')]})
                current_step = None
            elif 'NASA POWER query request:' in message:
                steps.append({'type': 'Weather API Request', 'content': [message.replace('NASA POWER query request: ', '')]})
                current_step = None
            elif 'NASA POWER query response:' in message:
                steps.append({'type': 'Weather API Response', 'content': [message.replace('NASA POWER query response: ', '')]})
                current_step = None
            else:
                current_step = None
        else:
            if current_step is not None:
                current_step['content'].append(line)

    with open(out_file, 'w', encoding='utf-8') as f:
        f.write('# Crop Recommendation Execution Flow\n\n')
        f.write('This document outlines the step-by-step process the system took to generate your crop recommendation.\n\n')
        
        step_num = 1
        for i, step in enumerate(steps):
            content_str = ''.join(step['content']).strip()
            
            if step['type'] == 'Soil API Request':
                try:
                    parsed = eval(content_str)
                    f.write(f"### Step {step_num}: Checking Soil Conditions\n")
                    f.write(f"**Action:** The system queried the SoilGrids database for the farm's location (Latitude: {parsed.get('lat')}, Longitude: {parsed.get('lon')}).\n")
                    f.write(f"**Reason:** To understand the physical and chemical properties of the soil at your specific farm.\n\n")
                    step_num += 1
                except:
                    pass
            elif step['type'] == 'Soil API Response':
                f.write(f"### Step {step_num}: Receiving Soil Data\n")
                f.write(f"**Result:** The system received detailed soil information including pH, nitrogen, and clay percentage levels to base its recommendations on.\n\n")
                step_num += 1
            elif step['type'] == 'LLM Request' and 'query planner' in content_str:
                f.write(f"### Step {step_num}: Planning the Research Strategy\n")
                f.write(f"**Action:** The AI Query Planner analyzed your inputs (season, budget, water source) and the soil data to figure out what external information it needed to search for.\n")
                f.write(f"**Reason:** To find live, localized data that might affect your farm (like ministerial decrees, fertilizer prices, and pest alerts).\n\n")
                step_num += 1
            elif step['type'] == 'LLM Response' and i > 0 and steps[i-1]['type'] == 'LLM Request' and 'query planner' in ''.join(steps[i-1]['content']):
                try:
                    parsed = json.loads(content_str)
                    f.write(f"### Step {step_num}: Formulating Search Queries\n")
                    f.write(f"**Result:** The AI decided to search the web for the following topics:\n")
                    for q in parsed:
                        f.write(f"- {q.get('text')} *(Why? {q.get('rationale')})*\n")
                    f.write('\n')
                    step_num += 1
                except:
                    pass
            elif step['type'] == 'Web Search Request':
                try:
                    parsed = eval(content_str)
                    f.write(f"### Step {step_num}: Searching the Web\n")
                    f.write(f"**Action:** The system searched the internet for: `\"{parsed.get('query')}\"`\n\n")
                    step_num += 1
                except:
                    pass
            elif step['type'] == 'Web Search Response':
                try:
                    parsed = eval(content_str)
                    f.write(f"### Step {step_num}: Search Results\n")
                    f.write(f"**Result:** Found several articles and resources for `\"{parsed.get('query', 'the search')}\"`. Top results included:\n")
                    for r in parsed.get('results', [])[:3]:
                        f.write(f"- [{r.get('title')}]({r.get('url')})\n")
                    f.write('\n')
                    step_num += 1
                except:
                    pass
            elif step['type'] == 'LLM Request' and 'extract atomic facts' in content_str:
                query_match = re.search(r'Query that produced these results:\s*"(.*?)"', content_str)
                query_text = query_match.group(1) if query_match else "the search"
                f.write(f"### Step {step_num}: Extracting Facts from Search Results\n")
                f.write(f"**Action:** The AI read through the search results for `\"{query_text}\"` to pull out concrete, factual information relevant to your farm in Egypt.\n\n")
                step_num += 1
            elif step['type'] == 'LLM Response' and i > 0 and steps[i-1]['type'] == 'LLM Request' and 'extract atomic facts' in ''.join(steps[i-1]['content']):
                try:
                    parsed = json.loads(content_str)
                    if parsed:
                        f.write(f"### Step {step_num}: Facts Discovered\n")
                        f.write(f"**Result:** The AI extracted the following key facts:\n")
                        for f_item in parsed:
                            f.write(f"- {f_item.get('fact')} *(Confidence: {f_item.get('confidence')})*\n")
                        f.write('\n')
                    step_num += 1
                except:
                    pass
            elif step['type'] == 'Weather API Request':
                f.write(f"### Step {step_num}: Checking Climate and Weather Data\n")
                f.write(f"**Action:** The system queried the NASA POWER climate database.\n")
                f.write(f"**Reason:** To calculate Growing Degree Days (GDD) and understand temperature trends for your farm.\n\n")
                step_num += 1
            elif step['type'] == 'Weather API Response':
                f.write(f"### Step {step_num}: Receiving Climate Data\n")
                f.write(f"**Result:** The system received historical climate data to ensure the recommended crops can survive the typical temperatures during your growing season.\n\n")
                step_num += 1
            elif step['type'] == 'LLM Request' and 'audit' in content_str.lower():
                f.write(f"### Step {step_num}: Auditing Evidence\n")
                f.write(f"**Action:** The AI reviewed all the gathered evidence to identify any missing information, contradictions, or low-confidence data.\n\n")
                step_num += 1
            elif step['type'] == 'LLM Request' and 'score' in content_str.lower():
                f.write(f"### Step {step_num}: Scoring Crop Candidates\n")
                f.write(f"**Action:** The AI evaluated multiple crop options against your soil, climate, water source, and market factors to calculate a suitability score for each.\n\n")
                step_num += 1
            elif step['type'] == 'LLM Request' and 'scenario' in content_str.lower():
                f.write(f"### Step {step_num}: Stress-Testing Recommendations\n")
                f.write(f"**Action:** The AI tested the top crop candidates against potential negative scenarios like drought, pest outbreaks, or currency devaluation to see how resilient they are.\n\n")
                step_num += 1
            elif step['type'] == 'LLM Request' and 'final recommendation' in content_str.lower():
                f.write(f"### Step {step_num}: Formatting the Final Report\n")
                f.write(f"**Action:** The AI compiled the top recommended crops, expected revenues, and risks into a clear, farmer-friendly report.\n\n")
                step_num += 1
            elif step['type'] == 'LLM Response' and i > 0 and steps[i-1]['type'] == 'LLM Request' and 'final recommendation' in ''.join(steps[i-1]['content']).lower():
                try:
                    # just to check valid json format if it exists, though it might not be perfect json
                    f.write(f"### Step {step_num}: Final Crop Recommendation Output\n")
                    f.write(f"**Result:** The system produced the final plain-language recommendation text you see as the output.\n\n")
                    step_num += 1
                except:
                    pass


async def _write_narrative(llm: LLMClient, state) -> str:
    """One LLM call: write plain-language reasoning for the crop evaluation."""
    out = state.output
    if not out or not hasattr(out, 'evaluation') or not out.evaluation:
        return "No evaluation could be generated."
        
    eval_obj = out.evaluation
    overall_conf = out.overall_confidence_pct
    raw_top = getattr(state, "_raw_top_confidence_pct", overall_conf)
    reduction = max(0, raw_top - overall_conf)

    crop_block = (
        f"Target Crop Evaluated: {eval_obj.crop}\n"
        f"  Score breakdown: {eval_obj.score_breakdown}\n"
        f"  Pros: {eval_obj.pros}\n"
        f"  Cons: {eval_obj.cons}\n"
        f"  Yield t/feddan: {eval_obj.yield_range_t_per_feddan}\n"
        f"  Revenue EGP/feddan: {eval_obj.revenue_egp_per_feddan}"
    )

    evidence_lines = [
        f"- {e.fact} (source: {e.source_name}, confidence: {e.confidence})"
        for e in state.evidence[:25]
    ]

    confidence_block = f"Overall evaluation confidence: {overall_conf}%."
    if reduction > 10:
        confidence_block += (
            f" The self-critique reduced confidence from {raw_top}% to {overall_conf}%"
            f" ({reduction} points). Explain to the farmer in one sentence why"
            " the model is less sure (e.g. missing soil data, weak market evidence,"
            " unresolved conflicts, regional defaults used)."
        )

    user_prompt = (
        f"Farmer context:\n"
        f"  location: lat={state.raw.latitude}, lon={state.raw.longitude}\n"
        f"  area: {state.raw.area_feddan} feddan\n"
        f"  water: {state.raw.water_source}\n"
        f"  soil: {state.raw.soil_type}\n"
        f"  budget: {state.raw.budget_egp} EGP\n"
        f"  start: {state.raw.start_date}, horizon: {state.raw.harvest_horizon_days} days\n\n"
        f"{confidence_block}\n\n"
        f"Crop Evaluation:\n"
        f"{crop_block}\n"
        f"\n\nEvidence gathered during research:\n"
        + ("\n".join(evidence_lines) if evidence_lines else "(no external evidence collected)")
        + "\n\nWrite a clear, plain-language evaluation for the farmer. "
        "Give 3-5 sentences explaining whether the target crop is suitable and WHY — reference soil fit, timing, water, market, "
        "and risk where relevant. Use the overall confidence number. Clearly state the main pros and cons."
    )

    response = await llm.chat(
        system="You are an agronomist explaining an evaluation of a specific crop to a smallholder farmer in Egypt. Be concrete, avoid jargon, cite specific numbers from the score breakdown when useful.",
        user=user_prompt,
    )
    
    eval_obj.recommendation_text = response
    return response


if __name__ == "__main__":
    asyncio.run(main())
