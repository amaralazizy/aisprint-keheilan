import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    llm_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    llm_base_url: str = os.getenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    reasoner_model: str = os.getenv("REASONER_MODEL", "openai/gpt-4o-mini")
    worker_model: str = os.getenv("WORKER_MODEL", "meta-llama/llama-3.1-8b-instruct")
    llm_max_tokens: int = 1024
    llm_temperature: float = 0.2
    shares_per_parcel: int = 1000


CONFIG = Config()
