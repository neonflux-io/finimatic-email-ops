from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from app.core.idempotency import sha256_key
from app.core.time import utcnow
from app.db.models import AgentSession, PendingEmailActionRow

SESSION_TTL_MINUTES = 30


def hash_session_token(session_token: str) -> str:
    return sha256_key(session_token)


def _as_aware(value: datetime):
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def load_session(session_token_hash: str, db: Session) -> AgentSession | None:
    row = db.query(AgentSession).filter_by(session_token_hash=session_token_hash).first()
    if row and row.expires_at and _as_aware(row.expires_at) < utcnow():
        expire_session(row.id, db)
        row.current_goal = None
        row.slots = None
        row.active_contact_id = None
        row.pending_action_id = None
        row.context_summary = "Previous agent session expired; a fresh session was started for the same browser tab."
        return row
    return row


def create_session(session_token_hash: str, db: Session) -> AgentSession:
    now = utcnow()
    row = AgentSession(session_token_hash=session_token_hash, expires_at=now + timedelta(minutes=SESSION_TTL_MINUTES))
    db.add(row)
    db.flush()
    return row


def get_or_create_session(session_token: str, db: Session) -> AgentSession:
    cleanup_expired_sessions(db)
    token_hash = hash_session_token(session_token)
    row = load_session(token_hash, db)
    if row is None:
        row = create_session(token_hash, db)
    touch_session(row, db)
    return row


def touch_session(row: AgentSession, db: Session) -> AgentSession:
    now = utcnow()
    row.updated_at = now
    row.expires_at = now + timedelta(minutes=SESSION_TTL_MINUTES)
    db.flush()
    return row


def update_session(session_id: str, updates: dict[str, Any], db: Session) -> AgentSession:
    row = db.get(AgentSession, session_id)
    if row is None:
        raise ValueError("agent session not found")
    for key, value in updates.items():
        if key == "slots" and not isinstance(value, str):
            value = json.dumps(value, sort_keys=True)
        setattr(row, key, value)
    touch_session(row, db)
    return row


def expire_session(session_id: str, db: Session) -> None:
    row = db.get(AgentSession, session_id)
    if row is None:
        return
    row.expires_at = utcnow()
    for action in db.query(PendingEmailActionRow).filter_by(session_id=session_id, consumed=False).all():
        action.consumed = True
        action.consumed_at = utcnow()
    db.flush()


def cleanup_expired_sessions(db: Session) -> int:
    now = utcnow()
    rows = [row for row in db.query(AgentSession).all() if row.expires_at and _as_aware(row.expires_at) < now]
    for row in rows:
        for action in db.query(PendingEmailActionRow).filter_by(session_id=row.id, consumed=False).all():
            action.consumed = True
            action.consumed_at = now
    return len(rows)
