"""
Stage 4 — parallel categorised web search.
Stage 5 — evidence parsing with confidence tagging and conflict detection.

These are bundled because Stage 5 immediately consumes Stage 4 output
and benefits from running per-query (i.e. extract evidence as each
search returns, not after all searches finish).
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime
from itertools import combinations

from ..clients.llm import LLMClient
from ..clients.search import SearchClient, SearchResult
from ..models import Conflict, Evidence, PlannedQuery
from ..prompts.templates import EVIDENCE_EXTRACTION_SYSTEM, evidence_extraction_user
from ..state import PipelineState

logger = logging.getLogger(__name__)


async def _search_and_extract(
    query: PlannedQuery,
    search: SearchClient,
    llm: LLMClient,
    sem: asyncio.Semaphore,
) -> tuple[str, list[Evidence]]:
    """Run one search + extract evidence. Returns (query_id, evidence list)."""
    query_id = str(uuid.uuid4())[:8]

    async with sem:
        results: list[SearchResult] = await search.search(
            query.text, language=query.language, max_results=5
        )

    if not results:
        return query_id, []

    # Pack results into one prompt for the extractor
    results_text = "\n\n".join(
        f"[{i+1}] {r.title}\nURL: {r.url}\nDate: {r.published_date or 'unknown'}\n{r.snippet}"
        for i, r in enumerate(results)
    )

    try:
        extracted = await llm.chat_json(
            system=EVIDENCE_EXTRACTION_SYSTEM,
            user=evidence_extraction_user(query.text, results_text),
        )
    except Exception as e:
        logger.warning("Evidence extraction failed for query '%s': %s", query.text, e)
        return query_id, []

    # The LLM returns a list of dicts; we attach source URLs from the search results.
    # Match by snippet keyword if possible, otherwise default to the top result.
    evidence: list[Evidence] = []
    for item in extracted if isinstance(extracted, list) else []:
        # Source URL — best effort match, fall back to top result
        url = results[0].url
        name = results[0].title
        date = results[0].published_date
        for r in results:
            if any(word in r.snippet.lower() for word in str(item.get("fact", "")).lower().split()[:3]):
                url, name, date = r.url, r.title, r.published_date
                break

        try:
            source_date = None
            if item.get("source_date"):
                source_date = datetime.fromisoformat(item["source_date"]).date()
            elif date:
                source_date = datetime.fromisoformat(date).date()
        except (ValueError, TypeError):
            source_date = None

        evidence.append(Evidence(
            fact=item.get("fact", "")[:500],
            value=item.get("value"),
            source_url=url,
            source_name=name[:200],
            source_date=source_date,
            confidence=item.get("confidence", "low"),
            query_id=query_id,
            language=query.language,
        ))

    return query_id, evidence


async def run_stage_4_5_search_and_extract(
    state: PipelineState,
    search: SearchClient,
    llm: LLMClient,
    queries: list[PlannedQuery] | None = None,
    parallel_limit: int = 6,
) -> PipelineState:
    """
    Runs Stage 4 + 5. Queries default to all unprocessed queries in state.
    The reflection loop passes a subset (its follow-up queries) instead.
    """
    state.log("stage_4_5", "starting parallel search + extraction")
    queries = queries or state.queries

    sem = asyncio.Semaphore(parallel_limit)
    tasks = [_search_and_extract(q, search, llm, sem) for q in queries]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    new_evidence: list[Evidence] = []
    for r in results:
        if isinstance(r, Exception):
            state.log("stage_4_5", f"task raised: {r}")
            continue
        _query_id, evs = r
        new_evidence.extend(evs)

    state.evidence.extend(new_evidence)
    state.log("stage_4_5", f"extracted {len(new_evidence)} new evidence items")

    # Detect conflicts among new + existing evidence
    detect_and_record_conflicts(state)
    return state


def detect_and_record_conflicts(state: PipelineState) -> None:
    """
    Naive conflict detector: same fact keyword, different values.
    A real system would use embeddings or LLM-based fact alignment;
    this is good enough as a first pass and can be debugged easily.
    """
    new_conflicts: list[Conflict] = []
    by_keyword: dict[str, list[Evidence]] = {}

    for e in state.evidence:
        # Group by the first 4 non-trivial words of the fact
        key = " ".join(w.lower() for w in e.fact.split() if len(w) > 3)[:50]
        by_keyword.setdefault(key, []).append(e)

    for group in by_keyword.values():
        if len(group) < 2:
            continue
        for a, b in combinations(group, 2):
            # Conflict only if values exist and differ materially
            if a.value is None or b.value is None or a.value == b.value:
                continue
            try:
                va, vb = float(a.value), float(b.value)
                rel_diff = abs(va - vb) / max(abs(va), abs(vb), 1e-9)
                if rel_diff < 0.1:
                    continue  # within 10% — tolerable
                severity = "hard" if rel_diff > 0.3 else "soft"
            except (ValueError, TypeError):
                if str(a.value).strip().lower() == str(b.value).strip().lower():
                    continue
                severity = "soft"

            new_conflicts.append(Conflict(fact_a=a, fact_b=b, severity=severity))

    state.conflicts.extend(new_conflicts)
    if new_conflicts:
        state.log("stage_5", f"detected {len(new_conflicts)} conflicts")
