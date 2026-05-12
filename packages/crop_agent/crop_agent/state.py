"""
The PipelineState object flows through every stage, accumulating
outputs as attributes. This is the single source of truth for the
running recommendation — pickle it at any point to debug.

Each stage MUST be idempotent over the same state: running it twice
should produce the same result. This matters for the reflection loop,
which re-enters earlier stages.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .models import (
    Conflict,
    CropScore,
    Evidence,
    FinalOutput,
    ParsedInput,
    PlannedQuery,
    RawInput,
    ScenarioOutcome,
)


@dataclass
class PipelineState:
    raw: RawInput
    parsed: Optional[ParsedInput] = None
    queries: list[PlannedQuery] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    conflicts: list[Conflict] = field(default_factory=list)

    # Reflection loop bookkeeping
    reflection_rounds: int = 0
    reflection_log: list[dict] = field(default_factory=list)

    # Scoring + scenarios
    scores: list[CropScore] = field(default_factory=list)
    scenarios: list[ScenarioOutcome] = field(default_factory=list)

    # Critique
    assumptions: list[dict] = field(default_factory=list)
    critique_passed: bool = False

    # Final
    output: Optional[FinalOutput] = None

    # Debug trace — every stage appends a line
    trace: list[str] = field(default_factory=list)

    def log(self, stage: str, msg: str) -> None:
        self.trace.append(f"[{stage}] {msg}")

    def evidence_for(self, query_id: str) -> list[Evidence]:
        return [e for e in self.evidence if e.query_id == query_id]
