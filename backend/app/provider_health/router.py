from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.time import iso
from app.db.models import ProviderHealth
from app.db.session import get_db

router = APIRouter(prefix="/api/provider-health", tags=["provider-health"])


def provider_health_to_dict(row: ProviderHealth) -> dict:
    return {
        "id": row.id,
        "provider": row.provider,
        "status": row.status,
        "last_checked": iso(row.last_checked),
        "error_code": row.error_code,
        "details": row.details,
    }


@router.get("")
def list_provider_health(db: Session = Depends(get_db)):
    rows = db.query(ProviderHealth).order_by(ProviderHealth.provider.asc()).all()
    return {"items": [provider_health_to_dict(row) for row in rows], "total": len(rows)}
