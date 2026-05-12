"""Slim sync LLM client for Model 1. OpenRouter (OpenAI-compatible)."""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from openai import OpenAI

_NUM_COMMA_RE = re.compile(r"(?<=\d),(?=\d{3}(?:[\D]|$))")

from ..config import CONFIG

logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, model: str | None = None):
        self.client = OpenAI(
            api_key=CONFIG.llm_api_key,
            base_url=CONFIG.llm_base_url,
            max_retries=4,
            timeout=60.0,
        )
        self.model = model or CONFIG.reasoner_model

    def chat(self, system: str, user: str, *, json_mode: bool = False) -> str:
        sys_prompt = system
        kwargs: dict[str, Any] = {
            "model": self.model,
            "max_tokens": CONFIG.llm_max_tokens,
            "temperature": CONFIG.llm_temperature,
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": user},
            ],
        }
        if json_mode:
            sys_prompt += (
                "\n\nRespond with valid JSON only. No prose, no markdown fences. "
                "Use plain numbers without thousand separators (e.g. 2520000 not 2,520,000)."
            )
            kwargs["messages"][0]["content"] = sys_prompt
            kwargs["response_format"] = {"type": "json_object"}
        resp = self.client.chat.completions.create(**kwargs)
        return resp.choices[0].message.content or ""

    def chat_json(self, system: str, user: str) -> Any:
        text = self.chat(system, user, json_mode=True).strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            cleaned = _NUM_COMMA_RE.sub("", text)
            try:
                return json.loads(cleaned)
            except json.JSONDecodeError as e:
                logger.error("LLM returned non-JSON: %s", text[:500])
                raise RuntimeError(f"LLM JSON parse failed: {e}") from e


def get_llm() -> LLMClient:
    return LLMClient()
