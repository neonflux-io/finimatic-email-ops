from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.ai.key_utils import parse_keys


@dataclass
class KeyState:
    key: str
    last_used_at: datetime | None = None
    cooldown_until: datetime | None = None
    quarantined: bool = False


class GroqKeyPool:
    def __init__(self, keys: list[str] | str | None):
        self.states = [KeyState(key) for key in parse_keys(keys)]

    def active_states(self) -> list[KeyState]:
        now = datetime.now(timezone.utc)
        return [
            state
            for state in self.states
            if not state.quarantined and (state.cooldown_until is None or state.cooldown_until <= now)
        ]

    def acquire(self) -> str | None:
        active = self.active_states()
        if not active:
            return None
        chosen = sorted(active, key=lambda item: item.last_used_at or datetime.min.replace(tzinfo=timezone.utc))[0]
        chosen.last_used_at = datetime.now(timezone.utc)
        return chosen.key

    def record_rate_limit(self, key: str, retry_after_s: int = 60) -> None:
        for state in self.states:
            if state.key == key:
                state.cooldown_until = datetime.now(timezone.utc) + timedelta(seconds=retry_after_s)

    def quarantine(self, key: str) -> None:
        for state in self.states:
            if state.key == key:
                state.quarantined = True

    def exhausted_error_code(self) -> str | None:
        return "model_unavailable_rate_limited" if self.states and not self.active_states() else None
