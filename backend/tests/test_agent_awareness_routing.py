from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest

from app.agent.campaign_intelligence import answer_awareness_query
from app.agent.context_loader import build_context_card, generate_proactive_opening, is_context_stale
from app.core.time import utcnow
from app.db.models import Contact, ConversationMessage, Reply
from app.db.session import SessionLocal


@pytest.mark.asyncio
async def test_channel_router_awareness_who_replied(client, monkeypatch):
    from app.agent import channel_router

    class FakeCompletions:
        def create(self, **kwargs):
            assert kwargs["model"] == "llama-3.1-8b-instant"
            assert kwargs["max_tokens"] == 80
            assert kwargs["temperature"] == 0.1
            return SimpleNamespace(
                choices=[
                    SimpleNamespace(
                        message=SimpleNamespace(
                            content='```json\n{"channel":"awareness","confidence":0.97,"routing_reason":"reply question"}\n```'
                        )
                    )
                ]
            )

    class FakeGroq:
        def __init__(self, api_key):
            assert api_key == "groq-test"
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(channel_router, "get_key_list", lambda db, key: ["groq-test"])
    monkeypatch.setattr(channel_router, "Groq", FakeGroq)

    decision = await channel_router.classify_channel("who all replied")

    assert decision.channel == "awareness"
    assert decision.confidence == 0.97


@pytest.mark.asyncio
async def test_campaign_intelligence_replied(client, monkeypatch):
    with SessionLocal() as db:
        contacts = [
            Contact(email="arjun@example.com", creator_name="Arjun", source="manual", status="replied"),
            Contact(email="priya@example.com", creator_name="Priya", source="manual", status="sent"),
            Contact(email="rahul@example.com", creator_name="Rahul", source="manual", status="sent"),
        ]
        db.add_all(contacts)
        db.flush()
        for contact in contacts:
            db.add(
                Reply(
                    contact_id=contact.id,
                    received_at=utcnow(),
                    classified_as="reply",
                    raw_summary=f"{contact.creator_name} replied with interest.",
                )
            )
        db.commit()

    async def fake_llm(**kwargs):
        return "3 people replied: Arjun (arjun@example.com), Priya (priya@example.com), and Rahul (rahul@example.com)."

    monkeypatch.setattr("app.agent.campaign_intelligence._call_with_fallback", fake_llm)
    with SessionLocal() as db:
        response = await answer_awareness_query("who all replied", db)

    assert "Arjun" in response
    assert "Priya" in response
    assert "Rahul" in response
    assert "arjun@example.com" in response
    assert "contact_id" not in response


@pytest.mark.asyncio
async def test_campaign_intelligence_empty_db(client, monkeypatch):
    async def fail_llm(**kwargs):
        raise ValueError("no provider")

    monkeypatch.setattr("app.agent.campaign_intelligence._call_with_fallback", fail_llm)
    with SessionLocal() as db:
        response = await answer_awareness_query("who all replied", db)

    assert response
    assert "TOTAL CONTACTS" in response or "campaign" in response.lower() or "know" in response.lower()


@pytest.mark.asyncio
async def test_campaign_intelligence_outbound_replies_distinguishes_user_replied(client, monkeypatch):
    async def fail_llm(**kwargs):
        raise AssertionError("outbound awareness question should not call the LLM")

    monkeypatch.setattr("app.agent.campaign_intelligence._call_with_fallback", fail_llm)
    with SessionLocal() as db:
        contact = Contact(email="sachi@example.com", creator_name="Sachi Khan", source="manual", status="conversation_active")
        db.add(contact)
        db.flush()
        db.add(
            ConversationMessage(
                contact_id=contact.id,
                direction="outbound",
                subject="Re: AI automation",
                body="Yes, I can show you how it works.",
                source="manual_reply",
                occurred_at=utcnow() - timedelta(hours=2),
            )
        )
        db.add(
            Reply(
                contact_id=contact.id,
                received_at=utcnow() - timedelta(hours=3),
                classified_as="reply",
                raw_summary="Interested.",
            )
        )
        db.commit()

    with SessionLocal() as db:
        response = await answer_awareness_query("whom all have I replied in last 10 hours", db)

    assert "1 contact you replied to in the last 10 hours" in response
    assert "Sachi Khan" in response
    assert "You wrote" in response
    assert "They wrote" not in response


@pytest.mark.asyncio
async def test_campaign_intelligence_received_replies_strips_quoted_email(client, monkeypatch):
    async def fail_llm(**kwargs):
        raise AssertionError("inbound awareness question should not call the LLM")

    monkeypatch.setattr("app.agent.campaign_intelligence._call_with_fallback", fail_llm)
    with SessionLocal() as db:
        contact = Contact(email="ross@example.com", creator_name="Ross Demo", source="manual", status="replied")
        db.add(contact)
        db.flush()
        db.add(
            Reply(
                contact_id=contact.id,
                received_at=utcnow() - timedelta(hours=1),
                classified_as="reply",
                raw_summary=(
                    "Yes, that works for me \u2014 thanks \u00e2\u0080\u0094 really. "
                    "On Mon, May 25, 2026 at 11:47 AM <sender@example.com> wrote: > old email content"
                ),
            )
        )
        db.commit()

    with SessionLocal() as db:
        response = await answer_awareness_query("have i received any reply recently", db)

    assert "Ross Demo" in response
    assert "Yes, that works for me - thanks - really." in response
    assert "\u2014" not in response
    assert "\u00e2\u0080\u0094" not in response
    assert "old email content" not in response
    assert "sender@example.com" not in response


def test_context_loader_builds_card(client):
    with SessionLocal() as db:
        contact = Contact(email="arjun@example.com", creator_name="Arjun", source="manual", status="replied")
        db.add(contact)
        db.flush()
        db.add(Reply(contact_id=contact.id, received_at=utcnow(), classified_as="reply", raw_summary="Interested."))
        db.commit()
        card = build_context_card(db)

    assert "TODAY:" in card
    assert "NEEDS RESPONSE:" in card
    assert "Arjun" in card


def test_context_stale():
    assert is_context_stale((utcnow() - timedelta(minutes=31)).replace(tzinfo=None).isoformat()) is True


def test_context_fresh():
    assert is_context_stale((utcnow() - timedelta(minutes=5)).replace(tzinfo=None).isoformat()) is False


def test_proactive_opening_with_replies(client):
    with SessionLocal() as db:
        opening = generate_proactive_opening("TODAY: 0 sent, 1 new replies | NEEDS RESPONSE: Arjun | PENDING APPROVALS: 0 drafts | OPT-OUTS TODAY: 0", db)

    assert "Arjun" in opening
    assert len(opening.split(".")) <= 3
