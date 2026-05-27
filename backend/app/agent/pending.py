from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Literal

from sqlalchemy.orm import Session

from app.agent.memory import hash_session_token
from app.core.idempotency import sha256_key
from app.core.time import utcnow
from app.db.models import AgentSession, Contact, Draft, PendingEmailActionRow

CONFIRMATION_TTL_SECONDS = 180
PendingStatus = Literal["valid", "not_found", "expired", "consumed", "session_mismatch", "draft_mismatch", "hash_mismatch"]


def params_hash(draft_id: str, contact_id: str, subject: str, body: str) -> str:
    return sha256_key(draft_id, contact_id, subject, body)


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _session_id_from_token_or_id(value: str, db: Session) -> str | None:
    if db.get(AgentSession, value):
        return value
    row = db.query(AgentSession).filter_by(session_token_hash=hash_session_token(value)).first()
    return row.id if row else None


def create_pending_action(session_id: str, draft_id: str, contact_id: str, subject: str, body: str, db: Session) -> PendingEmailActionRow:
    now = utcnow()
    session = db.get(AgentSession, session_id)
    if session:
        cancel_pending_action(session_id, db)
    contact = db.get(Contact, contact_id)
    to_email = contact.email if contact else "recipient"
    action = PendingEmailActionRow(
        session_id=session_id,
        draft_id=draft_id,
        contact_id=contact_id,
        params_hash=params_hash(draft_id, contact_id, subject, body),
        source_label="Email Provider",
        confirmation_prompt=f"Send this draft to {to_email} with subject \"{subject}\"?",
        expires_at=now + timedelta(seconds=CONFIRMATION_TTL_SECONDS),
    )
    db.add(action)
    db.flush()
    if session:
        session.pending_action_id = action.id
    return action


def validate_pending_action(action_id: str, session_token_or_id: str, draft_id: str, db: Session) -> PendingStatus:
    action = db.get(PendingEmailActionRow, action_id)
    if action is None:
        return "not_found"
    if action.consumed:
        return "consumed"
    if _as_aware(action.expires_at) < utcnow():
        return "expired"
    session_id = _session_id_from_token_or_id(session_token_or_id, db)
    if not session_id or action.session_id != session_id:
        return "session_mismatch"
    if action.draft_id != draft_id:
        return "draft_mismatch"
    draft = db.get(Draft, draft_id)
    if not draft or draft.contact_id != action.contact_id:
        return "draft_mismatch"
    current_hash = params_hash(draft.id, draft.contact_id, draft.subject, draft.body)
    if action.params_hash != current_hash:
        return "hash_mismatch"
    return "valid"


def consume_pending_action(action_id: str, db: Session) -> None:
    action = db.get(PendingEmailActionRow, action_id)
    if action is None:
        return
    action.consumed = True
    action.consumed_at = utcnow()
    session = db.get(AgentSession, action.session_id)
    if session and session.pending_action_id == action.id:
        session.pending_action_id = None
    db.flush()


def claim_pending_action(action_id: str, session_token_or_id: str, draft_id: str, db: Session) -> PendingStatus:
    status = validate_pending_action(action_id, session_token_or_id, draft_id, db)
    if status != "valid":
        return status
    now = utcnow()
    claimed = (
        db.query(PendingEmailActionRow)
        .filter(
            PendingEmailActionRow.id == action_id,
            PendingEmailActionRow.consumed.is_(False),
            PendingEmailActionRow.expires_at >= now,
        )
        .update({"consumed": True, "consumed_at": now}, synchronize_session=False)
    )
    db.flush()
    if claimed != 1:
        return validate_pending_action(action_id, session_token_or_id, draft_id, db)
    action = db.get(PendingEmailActionRow, action_id)
    session = db.get(AgentSession, action.session_id) if action else None
    if session and session.pending_action_id == action_id:
        session.pending_action_id = None
    return "valid"


def cancel_pending_action(session_id: str, db: Session) -> None:
    session = db.get(AgentSession, session_id)
    for action in db.query(PendingEmailActionRow).filter_by(session_id=session_id, consumed=False).all():
        action.consumed = True
        action.consumed_at = utcnow()
    if session:
        session.pending_action_id = None
    db.flush()
