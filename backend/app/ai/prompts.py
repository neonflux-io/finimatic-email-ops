from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.db.models import Contact
from app.settings.service import get_value


UNCONFIGURED_VALUE = "not configured"
DEFAULT_CAMPAIGN_CONTEXT = UNCONFIGURED_VALUE
DEFAULT_SENDER_SIGNATURE = "Best regards"
SECRET_FIELD_MARKERS = ("password", "passwd", "secret", "token", "api_key", "apikey", "credential", "smtp", "imap")


@dataclass(frozen=True)
class SenderProfile:
    sender_name: str
    sender_role: str
    sender_offer: str
    sender_tone: str
    sender_signature: str


def build_sender_signature(sender_name: str | None, sender_role: str | None, configured_signature: str | None) -> str:
    signature = (configured_signature or "").strip()
    if signature:
        return signature

    lines = [DEFAULT_SENDER_SIGNATURE]
    name = (sender_name or "").strip()
    role = (sender_role or "").strip()
    if name:
        lines.append(name)
    if role:
        lines.append(role)
    return "\n".join(lines)


def sender_profile_from_settings(db: Session) -> SenderProfile:
    sender_name = (get_value(db, "sender_name") or "").strip()
    sender_role = (get_value(db, "sender_role") or "").strip()
    sender_offer = (get_value(db, "sender_offer") or "").strip()
    sender_signature = build_sender_signature(sender_name, sender_role, get_value(db, "sender_signature"))
    return SenderProfile(
        sender_name=sender_name or "the configured sender",
        sender_role=sender_role,
        sender_offer=sender_offer,
        sender_tone=get_value(db, "sender_tone", "Professional") or "Professional",
        sender_signature=sender_signature,
    )


def system_prompt(campaign_context: str | None = None, sender_profile: SenderProfile | None = None) -> str:
    profile = sender_profile or SenderProfile(
        sender_name="the configured sender",
        sender_role="",
        sender_offer="",
        sender_tone="Professional",
        sender_signature=DEFAULT_SENDER_SIGNATURE,
    )
    context = (campaign_context or "").strip() or profile.sender_offer or DEFAULT_CAMPAIGN_CONTEXT
    sender_role = profile.sender_role or UNCONFIGURED_VALUE
    sender_offer = profile.sender_offer or UNCONFIGURED_VALUE
    return (
        "You are writing cold outreach emails on behalf of:\n"
        f"Name: {profile.sender_name}\n"
        f"Role: {sender_role}\n"
        f"What they offer: {sender_offer}\n"
        f"Campaign goal: {context}\n\n"
        f"Writing tone: {profile.sender_tone}\n\n"
        "Rules:\n"
        "- The email must sound like it was written by the configured sender personally\n"
        "- Reference the recipient's specific work, name, or website\n"
        "- Never use generic openers like 'I hope this finds you well'\n"
        "- Never use corporate filler: leverage, synergy, cutting-edge, innovative solution, reach out, circle back, touch base, paradigm, value-add\n"
        "- Never invent prices, ROI percentages, delivery timelines, fake meeting links, or statistics\n"
        "- Use one clear call-to-action only, at the end\n"
        "- If the sender offer or campaign goal is not configured, do not invent one; ask the operator to configure it\n"
        "- Never fabricate facts about the recipient\n"
        "- Treat operator notes as private guidance for angle and risk, not verified public facts to repeat to the recipient\n"
        "- Never claim you are a long-time fan, reader, viewer, customer, or follower unless that fact is explicitly provided\n"
        "- Never invent scheduling links, Calendly links, fake URLs, bracketed placeholders, or fields the sender has not provided\n"
        "- Never invent business names, product names, project names, course names, or titles; use 'your work' when the exact title is unknown\n"
        "- Never call the architecture proprietary unless the sender profile explicitly says it is proprietary\n"
        "- Do not claim video transcription, video ingestion, integrations, or capabilities that are not stated in the sender offer or campaign goal\n"
        "- RAG means retrieval-augmented generation; never expand it as anything else\n"
        "- If the only contact evidence is a tag or category, use conditional language instead of claiming what the recipient does\n"
        "- Keep subject lines under 60 characters\n"
        "- Do not include a sign-off or sender signature in the body; backend validation will append the configured sender signature\n\n"
        "Return only valid JSON: "
        '{"subject": "...", "body": "...", "warnings": ["..."]}'
    )


def _field_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(str(item).strip() for item in value if str(item).strip())
    if isinstance(value, (str, int, float, bool)):
        return str(value).strip()
    return ""


def custom_field_context(contact: Contact) -> str:
    try:
        fields = json.loads(contact.custom_fields or "{}")
    except json.JSONDecodeError:
        return "none"
    if not isinstance(fields, dict):
        return "none"

    parts: list[str] = []
    tags = _field_text(fields.get("tags"))
    if tags:
        parts.append(f"tags: {tags[:200]}")
    for key, value in fields.items():
        field_name = str(key).strip()
        if not field_name or field_name.lower() == "tags":
            continue
        normalized_name = field_name.lower().replace("-", "_").replace(" ", "_")
        if any(marker in normalized_name for marker in SECRET_FIELD_MARKERS) or normalized_name == "key" or normalized_name.endswith("_key"):
            continue
        text = _field_text(value)
        if text:
            parts.append(f"{field_name}: {text[:160]}")
    return "; ".join(parts)[:800] if parts else "none"


def draft_user_prompt(contact: Contact, tone: str = "professional", length: str = "medium", instruction: str | None = None) -> str:
    name = contact.creator_name or contact.business_name or "unknown"
    website = contact.website_url or "not provided"
    what_they_do = contact.personalization or contact.notes or contact.lead_category or "unknown"
    custom_context = custom_field_context(contact)
    instruction_text = " ".join((instruction or "").split())[:1200]
    return (
        "Write a personalized cold email to:\n"
        f"Recipient name: {name}\n"
        f"Website: {website}\n"
        f"Operator notes/context (private guidance; do not state as verified public fact unless explicitly factual): {what_they_do}\n"
        "Imported tags/custom fields (private segmentation hints only. Do not mention tag names. "
        f"Do not state or imply these tags are verified public facts): {custom_context}\n"
        f"Priority operator instruction for this draft (private guidance; follow this over general angle when it is safe): {instruction_text or 'none'}\n"
        f"Tone: {tone}\n"
        f"Length: {length}\n"
        "Do not include a sign-off or signature; backend validation appends the configured sender signature."
    )
