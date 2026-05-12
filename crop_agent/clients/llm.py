"""
LLM client. Wraps OpenRouter (OpenAI-compatible API) with JSON-mode helpers.

Stages stay provider-agnostic — only this file knows the SDK.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from openai import AsyncOpenAI

from ..config import CONFIG

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.client = AsyncOpenAI(
            api_key=api_key or CONFIG.llm_api_key,
            base_url=CONFIG.llm_base_url,
            max_retries=8,  # ride out free-tier RPM windows (~30s each)
            timeout=120.0,
        )
        self.model = model or CONFIG.llm_model

    async def chat(
        self,
        system: str,
        user: str,
        max_tokens: int = None,
        temperature: float = None,
    ) -> str:
        """Plain text completion."""
        resp = await self.client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens or CONFIG.llm_max_tokens,
            temperature=temperature if temperature is not None else CONFIG.llm_temperature,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        return resp.choices[0].message.content

    async def chat_json(
        self,
        system: str,
        user: str,
        max_tokens: int = None,
        temperature: float = None,
    ) -> Any:
        """JSON-mode completion. Strips ```json fences if model added them."""
        system_with_json = (
            f"{system}\n\n"
            "You MUST respond with valid JSON only. No prose, no markdown fences, "
            "no explanation before or after. Just the JSON object or array."
        )
        text = await self.chat(system_with_json, user, max_tokens, temperature)
        text = text.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error("LLM returned non-JSON: %s", text[:500])
            raise RuntimeError(f"LLM JSON parse failed: {e}") from e
