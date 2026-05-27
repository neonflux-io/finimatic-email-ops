from __future__ import annotations

from app.agent.reasoning import ReasoningResult
from app.agent.schemas import IntentDecision, StrictModel


class VerificationDecision(StrictModel):
    sufficient: bool
    confidence_score: float
    what_is_missing: list[str] = []
    retryable: bool = False


class VerifierAgent:
    def verify(self, message: str, intent: IntentDecision, reasoning_result: ReasoningResult) -> VerificationDecision:
        return VerificationDecision(
            sufficient=reasoning_result.sufficient,
            confidence_score=0.85 if reasoning_result.sufficient else 0.35,
            what_is_missing=[] if reasoning_result.sufficient else ["sufficient evidence"],
            retryable=False,
        )
