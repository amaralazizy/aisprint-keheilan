"""
Web search client. Abstract interface + two implementations:
- StubSearchClient — returns canned results for offline testing
- TavilySearchClient — real web search via Tavily API

To swap in Serper, Brave, or your own scraper, write a new class that
implements the SearchClient protocol.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Protocol

import httpx

from ..config import CONFIG

logger = logging.getLogger(__name__)


@dataclass
class SearchResult:
    title: str
    url: str
    snippet: str
    published_date: str | None = None  # ISO format if known


class SearchClient(Protocol):
    async def search(self, query: str, *, language: str = "en", max_results: int = 5) -> list[SearchResult]:
        ...


# ---------- Stub for offline testing ----------

class StubSearchClient:
    """Returns plausible canned results. Use for tests and local dev."""

    CANNED = {
        "rice cultivation ban 2025": [
            SearchResult(
                title="Egypt Ministerial Decree 26/2025 restricts rice cultivation",
                url="https://example.gov.eg/decree-26",
                snippet="Rice cultivation limited to 9 governorates totalling 1,074,200 feddan...",
                published_date="2025-01-15",
            )
        ],
        "tuta absoluta outbreak": [
            SearchResult(
                title="FAO EMPRES alert: tomato leafminer Egypt Delta",
                url="https://fao.org/empres/example",
                snippet="Tuta absoluta outbreak reported across Delta governorates April 2026...",
                published_date="2026-04-10",
            )
        ],
    }

    async def search(self, query: str, *, language: str = "en", max_results: int = 5) -> list[SearchResult]:
        await asyncio.sleep(0.05)  # simulate latency
        for key, results in self.CANNED.items():
            if any(kw in query.lower() for kw in key.split()):
                return results[:max_results]
        return [SearchResult(
            title=f"(stub) result for: {query}",
            url="https://example.com/stub",
            snippet="Stub snippet — replace StubSearchClient with a real one.",
            published_date=None,
        )]


# ---------- Tavily (real web search) ----------

class TavilySearchClient:
    """Tavily search API. Get a key at tavily.com."""

    BASE = "https://api.tavily.com/search"

    def __init__(self, api_key: str | None = None):
        self.api_key = api_key or CONFIG.search_api_key

    async def search(self, query: str, *, language: str = "en", max_results: int = 5) -> list[SearchResult]:
        payload = {
            "api_key": self.api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": "advanced",
            "include_raw_content": False,
        }
        async with httpx.AsyncClient(timeout=CONFIG.search_timeout_s) as client:
            try:
                resp = await client.post(self.BASE, json=payload)
                resp.raise_for_status()
                data = resp.json()
            except httpx.HTTPError as e:
                logger.warning("Tavily search failed for '%s': %s", query, e)
                return []

        return [
            SearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                snippet=r.get("content", ""),
                published_date=r.get("published_date"),
            )
            for r in data.get("results", [])
        ]
