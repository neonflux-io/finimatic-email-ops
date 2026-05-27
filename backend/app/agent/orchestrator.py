from __future__ import annotations

from app.agent.catalog import source_label_for_capability
from app.agent.schemas import IntentDecision, ToolPlan


class OrchestratorAgent:
    def plan(self, intent: IntentDecision, slots: dict, session) -> list[ToolPlan]:
        return [
            ToolPlan(
                capability=intent.capability,
                params=dict(slots),
                side_effect=intent.requires_confirmation,
                source_label=source_label_for_capability(intent.capability),
                reason="single approved capability",
            )
        ]
