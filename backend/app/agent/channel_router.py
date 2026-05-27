from __future__ import annotations

import asyncio
import json
from typing import Literal

from groq import Groq
from pydantic import BaseModel, ConfigDict, Field

from app.db.session import SessionLocal
from app.settings.service import get_key_list


class ChannelDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: Literal["awareness", "task", "action"]
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    routing_reason: str = ""


CHANNEL_ROUTER_SYSTEM = """You classify user messages into exactly one routing channel.
Return ONLY valid JSON: {"channel": "...", "confidence": 0.0, "routing_reason": "..."}

Classification rules:
* awareness = ANY question about campaign state, contacts, replies, stats,
  history, progress. Default to this when uncertain.
* task = find/generate/draft/search/look up something specific
* action = send/confirm/approve/suppress/cancel/activate/delete
* When uncertain between awareness and task → return awareness
* NEVER return action unless user explicitly wants to change state

Do not include markdown, explanations, or any text outside the JSON."""


def _strip_markdown_fences(raw: str) -> str:
    text = raw.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    if lines and lines[0].strip().startswith("```"):
        lines = lines[1:]
    if lines and lines[-1].strip() == "```":
        lines = lines[:-1]
    if lines and lines[0].strip().lower() == "json":
        lines = lines[1:]
    return "\n".join(lines).strip()


async def classify_channel(message: str, context_hint: str = "") -> ChannelDecision:
    """
    Classify the user turn into awareness, task, or action. This function
    never raises; failures default to the no-side-effect awareness channel.
    """
    try:
        with SessionLocal() as db:
            groq_keys = get_key_list(db, "groq_keys")
        if not groq_keys:
            return ChannelDecision(
                channel="awareness",
                confidence=0.4,
                routing_reason="no_groq_keys_available_defaulting_to_awareness",
            )

        client = Groq(api_key=groq_keys[0])
        prompt_parts = [f"USER MESSAGE: {message[:300]}"]
        if context_hint:
            prompt_parts.append(f"RECENT SESSION CONTEXT: {context_hint[:150]}")

        def _call():
            return client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": CHANNEL_ROUTER_SYSTEM},
                    {"role": "user", "content": "\n".join(prompt_parts)},
                ],
                max_tokens=80,
                temperature=0.1,
            )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _call)
        raw = _strip_markdown_fences(response.choices[0].message.content or "")
        data = json.loads(raw)
        channel = data.get("channel")
        if channel not in {"awareness", "task", "action"}:
            data["channel"] = "awareness"
            data["routing_reason"] = "invalid_channel_corrected_to_awareness"
        return ChannelDecision(**data)
    except Exception as exc:
        return ChannelDecision(
            channel="awareness",
            confidence=0.3,
            routing_reason=f"error_defaulting_to_awareness:{type(exc).__name__}",
        )
