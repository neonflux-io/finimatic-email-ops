from __future__ import annotations

from pydantic import BaseModel, Field


class DraftSuggestion(BaseModel):
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=10, max_length=5000)
    warnings: list[str] = Field(default_factory=list, max_length=10)


class AIFailure(BaseModel):
    error_code: str
    provider: str
    detail: str = ""


EMPTY_DRAFT = {"subject": "", "body": "", "warnings": []}
