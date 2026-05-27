from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict
from sqlalchemy.orm import Session

from app.audit.service import emit_event
from app.core.crypto import redacted_error
from app.db.session import get_db
from app.send.smtp_adapter import GmailAdapter
from app.settings.service import get_secret, get_value, set_settings, set_value, settings_read

router = APIRouter(prefix="/api/settings", tags=["settings"])


class SettingsWrite(BaseModel):
    model_config = ConfigDict(extra="allow")


@router.get("")
def read_settings(db: Session = Depends(get_db)):
    return settings_read(db)


@router.post("")
def update_settings(payload: SettingsWrite, db: Session = Depends(get_db)):
    return set_settings(db, payload.model_dump(exclude_unset=True))


@router.post("/verify-smtp")
async def verify_smtp(db: Session = Depends(get_db)):
    user = get_value(db, "gmail_user")
    password = get_secret(db, "gmail_app_password")
    adapter = GmailAdapter()
    try:
        readiness = await adapter.verify(user, password)
    except Exception as exc:
        readiness = "failed"
        emit_event(db, "sender.smtp_failed", payload={"error_detail": redacted_error(exc)})
    if readiness == "smtp_verified":
        set_value(db, "sender_readiness", "smtp_verified")
        emit_event(db, "sender.smtp_verified", payload={"gmail_user": user})
        db.commit()
        return {"readiness": readiness}
    set_value(db, "sender_readiness", "failed")
    emit_event(db, "sender.smtp_failed", payload={"error_detail": "SMTP verification failed"})
    db.commit()
    return {"readiness": "failed", "error_code": "smtp_auth_failed", "error_detail": "SMTP verification failed"}
