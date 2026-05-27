from __future__ import annotations

from app.agent.catalog import get_capability, validate_capability
from app.agent.schemas import GoalFrame, IntentDecision


class IntentAgent:
    def decide(self, message: str, session_summary: str | None, goal_frame: GoalFrame) -> IntentDecision:
        capability = validate_capability(goal_frame.proposed_capability)
        spec = get_capability(capability) or {}
        return IntentDecision(
            intent=capability,
            capability=capability,
            dialogue_act="cancel" if message.strip().lower() in {"cancel", "stop", "do not send", "don't send"} else "new_intent",
            confidence=goal_frame.confidence,
            requires_confirmation=bool(spec.get("confirmation_required")),
            rationale=goal_frame.reason,
        )
