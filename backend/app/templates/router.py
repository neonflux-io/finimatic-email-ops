from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.audit.service import emit_event
from app.core.time import iso
from app.db.models import Draft, Template
from app.db.session import get_db

router = APIRouter(prefix="/api/templates", tags=["templates"])


class TemplateCreate(BaseModel):
    name: str
    subject_template: str | None = None
    body_template: str | None = None
    draft_id: str | None = None


def template_to_dict(row: Template) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "subject_template": row.subject_template,
        "body_template": row.body_template,
        "created_at": iso(row.created_at),
    }


@router.get("")
def list_templates(db: Session = Depends(get_db)):
    rows = db.query(Template).order_by(Template.created_at.asc()).all()
    return {"items": [template_to_dict(row) for row in rows], "total": len(rows)}


@router.post("")
def create_template(payload: TemplateCreate, db: Session = Depends(get_db)):
    subject = payload.subject_template
    body = payload.body_template
    if payload.draft_id:
        draft = db.get(Draft, payload.draft_id)
        if not draft:
            raise HTTPException(status_code=404, detail="draft not found")
        if not draft.approved:
            raise HTTPException(status_code=400, detail="draft must be approved")
        subject = draft.subject
        body = draft.body
    if not subject or not body:
        raise HTTPException(status_code=400, detail="subject_template and body_template are required")
    row = Template(
        name=payload.name.strip(),
        subject_template=subject,
        body_template=body,
    )
    db.add(row)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="template name already exists") from exc
    emit_event(db, "template.created", entity_type="template", entity_id=row.id, payload={"name": row.name})
    db.commit()
    return template_to_dict(row)
