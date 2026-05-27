from __future__ import annotations

import asyncio
import logging
from typing import Literal

from app.db.session import SessionLocal
from app.settings.service import get_key_list


logger = logging.getLogger(__name__)

PROVIDER_ROUTING: dict[str, dict] = {
    "channel_router": {"primary": "groq", "model": "llama-3.1-8b-instant"},
    "goal_frame": {"primary": "groq", "model": "llama-3.3-70b-versatile"},
    "intent_agent": {"primary": "groq", "model": "llama-3.3-70b-versatile"},
    "slot_agent": {"primary": "groq", "model": "llama-3.1-8b-instant"},
    "verifier_light": {"primary": "groq", "model": "llama-3.1-8b-instant"},
    "repair_router": {"primary": "groq", "model": "llama-3.1-8b-instant"},
    "campaign_intelligence": {"primary": "gemini", "model": "gemini-2.0-flash"},
    "draft_generation": {"primary": "gemini", "model": "gemini-2.0-flash"},
    "conversation_reply": {"primary": "gemini", "model": "gemini-2.0-flash"},
    "reasoning_agent": {"primary": "gemini", "model": "gemini-2.0-flash"},
    "response_agent": {"primary": "gemini", "model": "gemini-2.0-flash"},
    "verifier_strict": {"primary": "groq", "model": "llama-3.3-70b-versatile"},
}


async def call_provider_with_fallback(
    agent_name: str,
    system: str,
    user: str,
    max_tokens: int = 500,
    temperature: float = 0.3,
) -> str:
    route = PROVIDER_ROUTING.get(agent_name, {"primary": "groq", "model": "llama-3.3-70b-versatile"})
    primary = route["primary"]
    model = route["model"]
    fallback_provider = "gemini" if primary == "groq" else "groq"
    fallback_model = "gemini-2.0-flash" if fallback_provider == "gemini" else "llama-3.3-70b-versatile"

    try:
        return await _call_single_provider(primary, model, system, user, max_tokens, temperature)
    except Exception as exc:
        logger.warning(
            "provider_router primary failed agent=%s provider=%s error=%s",
            agent_name,
            primary,
            type(exc).__name__,
        )

    try:
        return await _call_single_provider(fallback_provider, fallback_model, system, user, max_tokens, temperature)
    except Exception as exc:
        logger.error(
            "provider_router fallback failed agent=%s provider=%s error=%s",
            agent_name,
            fallback_provider,
            type(exc).__name__,
        )
        raise


async def _call_single_provider(
    provider: Literal["groq", "gemini"],
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
) -> str:
    loop = asyncio.get_event_loop()

    if provider == "groq":
        with SessionLocal() as db:
            keys = get_key_list(db, "groq_keys")
        if not keys:
            raise ValueError("missing_groq_keys")

        def _call():
            from groq import Groq

            client = Groq(api_key=keys[0])
            response = client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return response.choices[0].message.content or ""

        return await loop.run_in_executor(None, _call)

    if provider == "gemini":
        with SessionLocal() as db:
            keys = get_key_list(db, "gemini_keys")
        if not keys:
            raise ValueError("missing_gemini_keys")

        def _call():
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=keys[0])
            try:
                response = client.models.generate_content(
                    model=model,
                    contents=user,
                    config=types.GenerateContentConfig(
                        system_instruction=system,
                        max_output_tokens=max_tokens,
                        temperature=temperature,
                    ),
                )
                return response.text or ""
            finally:
                close = getattr(client, "close", None)
                if close:
                    close()

        return await loop.run_in_executor(None, _call)

    raise ValueError(f"unknown_provider:{provider}")
