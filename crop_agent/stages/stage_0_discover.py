import json
import logging
from ..clients.llm import LLMClient
from ..prompts.templates import DISCOVER_CROPS_SYSTEM

logger = logging.getLogger(__name__)

async def discover_top_crops(season: str, llm: LLMClient) -> list[str]:
    """Asks the LLM to identify the top 3 crops for a given season in Egypt."""
    user_prompt = f"What are the top 3 most popular crops planted in Egypt during the {season} season?"
    
    try:
        response = await llm.chat_json(
            system=DISCOVER_CROPS_SYSTEM,
            user=user_prompt,
            temperature=0.1
        )
        if isinstance(response, list) and len(response) >= 1:
            return [str(c).lower() for c in response[:3]]
    except Exception as e:
        logger.error(f"Discovery failed: {e}")
    
    # Fallback
    if "shitawi" in season.lower() or "winter" in season.lower():
        return ["wheat", "clover", "sugar beet"]
    elif "seifi" in season.lower() or "summer" in season.lower():
        return ["corn", "rice", "cotton"]
    else:
        return ["tomato", "potato", "onion"]
