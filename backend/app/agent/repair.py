from __future__ import annotations

from app.agent.schemas import StrictModel


class RepairAction(StrictModel):
    action: str
    message: str


class RepairRouter:
    def handle(self, error_type: str, context: dict) -> RepairAction:
        if error_type == "missing_slots":
            return RepairAction(action="clarify", message="I need one more detail before I can continue.")
        if error_type == "tool_fail":
            return RepairAction(action="fail_closed", message="I could not complete that safely.")
        return RepairAction(action="fail_closed", message="I could not complete that request safely.")
