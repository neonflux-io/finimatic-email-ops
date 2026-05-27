from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.db.models import Contact


STOP_WORDS = {
    "the",
    "a",
    "an",
    "to",
    "for",
    "of",
    "and",
    "or",
    "with",
    "send",
    "reply",
    "email",
    "contact",
    "person",
    "him",
    "her",
    "them",
    "it",
    "this",
    "that",
    "who",
    "find",
    "me",
    "my",
    "his",
    "hers",
    "their",
    "those",
    "these",
    "that",
    "guy",
    "gal",
    "from",
    "about",
    "regarding",
    "re",
    "at",
    "on",
}


@dataclass
class FuzzyResolveResult:
    match: Optional[Contact] = None
    candidates: list = field(default_factory=list)
    confidence: float = 0.0
    method: str = ""
    needs_clarification: bool = False
    clarification_question: Optional[str] = None


def fuzzy_resolve_contact(query: str, db: Session) -> FuzzyResolveResult:
    query_clean = str(query or "").strip()
    query_lower = query_clean.lower()

    exact_email = db.query(Contact).filter(Contact.deleted_at.is_(None), Contact.email == query_lower).first()
    if exact_email:
        return FuzzyResolveResult(match=exact_email, confidence=1.0, method="exact_email")

    if "@" in query_lower or "." in query_lower:
        partial_email = db.query(Contact).filter(Contact.deleted_at.is_(None), Contact.email.ilike(f"%{query_lower}%")).limit(3).all()
        if len(partial_email) == 1:
            return FuzzyResolveResult(match=partial_email[0], confidence=0.9, method="partial_email")
        if 2 <= len(partial_email) <= 3:
            return _build_clarification(partial_email, query_clean)

    exact_name = (
        db.query(Contact)
        .filter(
            Contact.deleted_at.is_(None),
            or_(
                Contact.creator_name.ilike(query_lower),
                Contact.business_name.ilike(query_lower),
            )
        )
        .first()
    )
    if exact_name:
        return FuzzyResolveResult(match=exact_name, confidence=0.95, method="exact_name")

    tokens = [token for token in query_lower.split() if len(token) > 2 and token not in STOP_WORDS]
    if not tokens:
        return FuzzyResolveResult(
            needs_clarification=True,
            clarification_question=(
                f"I couldn't find a contact matching '{query_clean}'. "
                "Could you give me their name or email address?"
            ),
        )

    score_map: dict[str, tuple[Contact, int]] = {}
    for token in tokens:
        hits = (
            db.query(Contact)
            .filter(
                Contact.deleted_at.is_(None),
                or_(
                    Contact.email.ilike(f"%{token}%"),
                    Contact.creator_name.ilike(f"%{token}%"),
                    Contact.business_name.ilike(f"%{token}%"),
                    Contact.notes.ilike(f"%{token}%"),
                    Contact.lead_category.ilike(f"%{token}%"),
                    Contact.personalization.ilike(f"%{token}%"),
                )
            )
            .limit(10)
            .all()
        )
        for contact in hits:
            current = score_map.get(contact.id)
            score_map[contact.id] = (contact, (current[1] if current else 0) + 1)

    ranked = sorted(score_map.values(), key=lambda item: (-item[1], _display_name(item[0]).lower(), item[0].email))
    if not ranked:
        return FuzzyResolveResult(
            needs_clarification=True,
            clarification_question=(
                f"I couldn't find a contact matching '{query_clean}'. "
                "Could you give me their name or email address?"
            ),
        )

    if len(ranked) == 1:
        contact, score = ranked[0]
        return FuzzyResolveResult(
            match=contact,
            confidence=min(0.5 + score * 0.15, 0.92),
            method="fuzzy_single",
        )

    return _build_clarification([contact for contact, _score in ranked[:5]], query_clean)


def _build_clarification(candidates: list[Contact], query: str) -> FuzzyResolveResult:
    options = []
    for index, contact in enumerate(candidates[:4], 1):
        category = f" [{contact.lead_category}]" if contact.lead_category else ""
        options.append(f"{index}. {_display_name(contact)} ({contact.email}){category}")

    more = f"\n+{len(candidates) - 4} more" if len(candidates) > 4 else ""
    return FuzzyResolveResult(
        candidates=candidates,
        needs_clarification=True,
        clarification_question=(
            f"I found a few contacts matching '{query}'. Which one did you mean?\n"
            f"{chr(10).join(options)}{more}"
        ),
    )


def _display_name(contact: Contact) -> str:
    return contact.creator_name or contact.business_name or contact.email
