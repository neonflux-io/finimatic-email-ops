from __future__ import annotations

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.agent.schemas import AgentCancelRequest, AgentChatRequest, AgentChatResponse, AgentConfirmRequest
from app.agent.service import AgentService
from app.db.session import get_db

router = APIRouter(tags=["agent"])
service = AgentService()


@router.post("/chat", response_model=AgentChatResponse)
async def chat(payload: AgentChatRequest, db: Session = Depends(get_db)):
    return await service.chat(payload, db)


@router.post("/confirm", response_model=AgentChatResponse)
async def confirm(payload: AgentConfirmRequest, db: Session = Depends(get_db)):
    response = await service.confirm(payload, db)
    if response.error_code:
        return JSONResponse(status_code=409, content=response.model_dump(mode="json"))
    return response


@router.delete("/cancel", response_model=AgentChatResponse)
async def cancel(payload: AgentCancelRequest, db: Session = Depends(get_db)):
    return await service.cancel(payload, db)
