from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import AuditEvent


SECRET_WORDS = ("password", "secret", "token", "key", "credential")
SECRET_PREFIXES = ("g" + "sk_", "AI" + "za")
SECRET_VALUE_RE = re.compile(
    "|".join(
        [
            r"gs" + r"k_[A-Za-z0-9_\-]+",
            r"AI" + r"za[A-Za-z0-9_\-]+",
            r"gAAAA[A-Za-z0-9_\-=]{20,}",
            r"eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+",
            r"(password|secret|token|api[_-]?key|credential)\s*[:=]\s*[^,\s;]+",
        ]
    )
    ,
    re.IGNORECASE,
)


def redact_payload(value: Any) -> Any:
    if isinstance(value, dict):
        redacted: dict[str, Any] = {}
        for key, item in value.items():
            if any(word in key.lower() for word in SECRET_WORDS):
                redacted[key] = "<redacted>"
            else:
                redacted[key] = redact_payload(item)
        return redacted
    if isinstance(value, list):
        return [redact_payload(item) for item in value]
    if isinstance(value, str):
        if value.startswith(SECRET_PREFIXES):
            return "<redacted>"
        return SECRET_VALUE_RE.sub("<redacted>", value)
    return value


def emit_event(
    db: Session,
    event_type: str,
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor: str = "system",
    payload: dict[str, Any] | None = None,
) -> AuditEvent:
    event = AuditEvent(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        payload=json.dumps(redact_payload(payload or {}), sort_keys=True),
    )
    db.add(event)
    return event


def audit_to_dict(event: AuditEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "entity_type": event.entity_type,
        "entity_id": event.entity_id,
        "actor": event.actor,
        "payload": json.loads(event.payload or "{}"),
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }
