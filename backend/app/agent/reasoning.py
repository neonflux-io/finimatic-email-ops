from __future__ import annotations

from app.agent.schemas import EvidenceEnvelope, IntentDecision, StrictModel


class ReasoningResult(StrictModel):
    summary: str
    sufficient: bool


class ReasoningAgent:
    def reason(self, message: str, intent: IntentDecision, evidence_envelopes: list[EvidenceEnvelope]) -> ReasoningResult:
        sufficient = any(item.status == "success" for item in evidence_envelopes)
        if any(item.status == "denied" for item in evidence_envelopes):
            sufficient = False
        return ReasoningResult(summary=f"Reasoned over {len(evidence_envelopes)} redacted evidence envelope(s).", sufficient=sufficient)
