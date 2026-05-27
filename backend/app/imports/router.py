from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.imports.service import PreviewExpiredError, commit_import, enrich_imported_contacts, preview_import

router = APIRouter(prefix="/api/import", tags=["import"])


class ImportPreviewRequest(BaseModel):
    format: str = "manual"
    rows: list[dict] | None = None
    content: str | None = None
    filename: str | None = None


class ImportCommitRequest(BaseModel):
    batch_id_temp: str | None = None
    rows: list[dict] | None = None
    format: str = "manual"
    filename: str | None = None


@router.post("/preview")
def preview(payload: ImportPreviewRequest, db: Session = Depends(get_db)):
    return preview_import(db, payload.format, payload.rows, payload.content, payload.filename)


@router.post("/commit")
def commit(payload: ImportCommitRequest, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    if payload.batch_id_temp:
        try:
            result = commit_import(db, payload.batch_id_temp)
        except PreviewExpiredError as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "reason": "preview_expired",
                    "message": "Import preview expired. Preview the file again before committing.",
                },
            ) from exc
        background_tasks.add_task(enrich_imported_contacts, result.get("contact_ids", []))
        return result
    preview = preview_import(db, payload.format, payload.rows, None, payload.filename)
    result = commit_import(db, preview["batch_id_temp"])
    background_tasks.add_task(enrich_imported_contacts, result.get("contact_ids", []))
    return result
