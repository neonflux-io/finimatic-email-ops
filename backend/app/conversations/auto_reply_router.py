from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.audit.service import audit_to_dict
from app.conversations.auto_reply_service import AutoReplyService
from app.db.models import AuditEvent, Draft
from app.db.session import get_db
from app.drafts.router import draft_to_dict

router = APIRouter(prefix="/api/auto-reply", tags=["auto-reply"])

AUTO_REPLY_EVENTS = {
    "auto_reply.sent",
    "auto_reply.proposed",
    "auto_reply.failed",
    "auto_reply.approved_and_sent",
    "auto_reply.rejected",
    "auto_reply.skipped",
    "auto_reply.quality_failed",
}


@router.post("/approve/{draft_id}")
async def approve_auto_reply(draft_id: str, db: Session = Depends(get_db)):
    try:
        result = await AutoReplyService().approve_pending_draft(draft_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return {"status": "sent", "message_id": result.message_id}


@router.post("/reject/{draft_id}")
def reject_auto_reply(draft_id: str, db: Session = Depends(get_db)):
    try:
        draft = AutoReplyService().reject_pending_draft(draft_id, db)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    db.commit()
    return {"status": "rejected", "draft": draft_to_dict(draft)}


@router.get("/pending")
def pending_auto_replies(db: Session = Depends(get_db)):
    items = AutoReplyService().pending_drafts(db)
    return {"items": items, "total": len(items)}


@router.get("/log")
def auto_reply_log(db: Session = Depends(get_db)):
    rows = (
        db.query(AuditEvent)
        .filter(AuditEvent.event_type.in_(AUTO_REPLY_EVENTS))
        .order_by(AuditEvent.created_at.desc())
        .limit(100)
        .all()
    )
    return {"items": [audit_to_dict(row) for row in rows], "total": len(rows)}
