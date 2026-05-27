from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.audit.service import emit_event
from app.ai.gateway import GROQ_MODEL_DEFAULT
from app.ai.groq_pool import GroqKeyPool
from app.contacts.utils import contact_tags, resolve_tokens
from app.db.models import CampaignPlan, Contact, Draft
from app.db.session import get_db
from app.settings.service import get_key_list, get_value

router = APIRouter(prefix="/api/campaigns", tags=["campaigns"])


class CampaignCreate(BaseModel):
    name: str
    goal: str
    target_tags: str | None = None
    sender_name: str | None = None
    sender_role: str | None = None
    sender_offer: str | None = None


class CampaignPatch(BaseModel):
    name: str | None = None
    goal: str | None = None
    target_tags: str | None = None
    step_1_draft: dict[str, Any] | str | None = None
    step_2_draft: dict[str, Any] | str | None = None
    step_3_draft: dict[str, Any] | str | None = None
    status: str | None = None


def campaign_to_dict(row: CampaignPlan) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "goal": row.goal,
        "target_tags": row.target_tags,
        "step_1_draft": _decode_step(row.step_1_draft),
        "step_2_draft": _decode_step(row.step_2_draft),
        "step_3_draft": _decode_step(row.step_3_draft),
        "status": row.status,
        "contacts_count": row.contacts_count,
        "sent_count": row.sent_count,
        "stopped_count": row.stopped_count,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


@router.get("")
def list_campaigns(db: Session = Depends(get_db)):
    rows = db.query(CampaignPlan).order_by(CampaignPlan.created_at.desc()).all()
    return {"items": [campaign_to_dict(row) for row in rows], "total": len(rows)}


@router.post("")
def create_campaign(payload: CampaignCreate, db: Session = Depends(get_db)):
    steps = suggest_campaign_steps(db, payload)
    row = CampaignPlan(
        name=payload.name,
        goal=payload.goal,
        target_tags=payload.target_tags or "",
        step_1_draft=json.dumps(steps["step_1"]),
        step_2_draft=json.dumps(steps["step_2"]),
        step_3_draft=json.dumps(steps["step_3"]),
        status="draft",
    )
    db.add(row)
    db.flush()
    emit_event(db, "campaign.created", entity_type="campaign_plan", entity_id=row.id, payload={"name": row.name})
    db.commit()
    return campaign_to_dict(row)


@router.get("/{campaign_id}")
def get_campaign(campaign_id: str, db: Session = Depends(get_db)):
    row = db.get(CampaignPlan, campaign_id)
    if not row:
        raise HTTPException(status_code=404, detail="campaign not found")
    return campaign_to_dict(row)


@router.patch("/{campaign_id}")
def patch_campaign(campaign_id: str, payload: CampaignPatch, db: Session = Depends(get_db)):
    row = db.get(CampaignPlan, campaign_id)
    if not row:
        raise HTTPException(status_code=404, detail="campaign not found")
    for field in ("name", "goal", "target_tags", "status"):
        value = getattr(payload, field)
        if value is not None:
            setattr(row, field, value)
    for field in ("step_1_draft", "step_2_draft", "step_3_draft"):
        value = getattr(payload, field)
        if value is not None:
            setattr(row, field, _encode_step(value))
    db.commit()
    return campaign_to_dict(row)


@router.post("/{campaign_id}/activate")
def activate_campaign(campaign_id: str, db: Session = Depends(get_db)):
    row = db.get(CampaignPlan, campaign_id)
    if not row:
        raise HTTPException(status_code=404, detail="campaign not found")
    step = _decode_step(row.step_1_draft)
    contacts = _matching_contacts(db, row.target_tags or "")
    created = 0
    for contact in contacts:
        draft = Draft(
            contact_id=contact.id,
            subject=resolve_tokens(str(step.get("subject") or ""), contact),
            body=resolve_tokens(str(step.get("body") or ""), contact),
            ai_provider="campaign_plan",
            ai_model=None,
            warnings=json.dumps([]),
            notes=f"campaign:{row.id}:step1",
            approved=False,
        )
        db.add(draft)
        created += 1
    row.status = "active"
    row.contacts_count = len(contacts)
    emit_event(db, "campaign.activated", entity_type="campaign_plan", entity_id=row.id, payload={"id": row.id, "contacts_count": len(contacts)})
    db.commit()
    return {"status": "active", "contacts_count": len(contacts), "drafts_created": created}


def suggest_campaign_steps(db: Session, payload: CampaignCreate) -> dict[str, dict[str, str]]:
    key = GroqKeyPool(get_key_list(db, "groq_keys")).acquire()
    empty = _empty_steps()
    if not key:
        return empty
    sender_name = payload.sender_name or get_value(db, "sender_name", "")
    sender_role = payload.sender_role or get_value(db, "sender_role", "")
    sender_offer = payload.sender_offer or get_value(db, "sender_offer", "")
    prompt = (
        "You are planning a 3-step cold email sequence.\n"
        f"Sender: {sender_name}, {sender_role}. Offer: {sender_offer}.\n"
        f"Campaign goal: {payload.goal}.\n"
        "Return JSON with exactly 3 keys: step_1, step_2, step_3.\n"
        "Each key: {subject: string, body: string, purpose: string}\n"
        "step_1: initial outreach\n"
        "step_2: value-add follow-up (3 days later)\n"
        "step_3: polite breakup email (6 days later)"
    )
    try:
        raw = _call_groq_campaign(db, key, prompt)
        parsed = json.loads(raw or "{}")
    except Exception as exc:
        emit_event(db, "campaign.ai_failed", entity_type="campaign_plan", payload={"error_code": exc.__class__.__name__})
        return empty
    return _validate_steps(parsed)


def _call_groq_campaign(db: Session, api_key: str, prompt: str) -> str:
    from groq import Groq

    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=get_value(db, "groq_model", GROQ_MODEL_DEFAULT),
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.4,
        timeout=30,
    )
    return response.choices[0].message.content or ""


def _validate_steps(parsed: dict) -> dict[str, dict[str, str]]:
    output = _empty_steps()
    for key in ("step_1", "step_2", "step_3"):
        value = parsed.get(key)
        if not isinstance(value, dict):
            return _empty_steps()
        output[key] = {
            "subject": str(value.get("subject") or ""),
            "body": str(value.get("body") or ""),
            "purpose": str(value.get("purpose") or ""),
        }
    return output


def _empty_steps() -> dict[str, dict[str, str]]:
    return {
        "step_1": {"subject": "", "body": "", "purpose": "initial outreach"},
        "step_2": {"subject": "", "body": "", "purpose": "value-add follow-up"},
        "step_3": {"subject": "", "body": "", "purpose": "polite breakup email"},
    }


def _decode_step(raw: str | None) -> dict[str, str]:
    try:
        value = json.loads(raw or "{}")
    except json.JSONDecodeError:
        value = {}
    if not isinstance(value, dict):
        value = {}
    return {
        "subject": str(value.get("subject") or ""),
        "body": str(value.get("body") or ""),
        "purpose": str(value.get("purpose") or ""),
    }


def _encode_step(value: dict[str, Any] | str) -> str:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            parsed = {"subject": "", "body": value, "purpose": ""}
    else:
        parsed = value
    return json.dumps(_decode_step(json.dumps(parsed)))


def _matching_contacts(db: Session, target_tags: str) -> list[Contact]:
    tags = {item.strip().lower() for item in target_tags.split(",") if item.strip()}
    contacts = db.query(Contact).filter(Contact.deleted_at.is_(None)).order_by(Contact.created_at.asc()).all()
    if not tags:
        return contacts
    return [contact for contact in contacts if tags.intersection({tag.lower() for tag in contact_tags(contact)})]
