from __future__ import annotations

import asyncio
import os
import smtplib
import ssl
import uuid
from dataclasses import dataclass
from datetime import timezone
from email.message import EmailMessage
from email.utils import make_msgid
from functools import partial
from typing import Literal

from app.core.time import utcnow
from app.send.fake_transport import FakeTransport

SenderReadiness = Literal["not_configured", "configured", "smtp_verified", "canary_verified", "failed"]


@dataclass
class SendResult:
    status: str
    provider_msg_id: str | None
    smtp_response: str | None = None
    error_code: str | None = None
    error_detail: str | None = None


@dataclass
class CanaryResult:
    status: str
    nonce: str
    timestamp: str
    idempotency_key: str
    provider_msg_id: str | None
    sender_identity: str


class SMTPTransport:
    def verify(self, user: str, password: str) -> bool:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as server:
            server.login(user, password)
        return True

    def send(self, *, sender: str, password: str, to: str, subject: str, body: str) -> dict:
        message = EmailMessage()
        message["From"] = sender
        message["To"] = to
        message["Subject"] = subject
        message["Message-ID"] = make_msgid(domain=(sender.rsplit("@", 1)[1] if "@" in sender else None))
        message.set_content(body)
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context, timeout=30) as server:
            server.login(sender, password)
            response = server.send_message(message)
        return {
            "message_id": message.get("Message-ID") or f"smtp-{uuid.uuid4().hex}",
            "smtp_response": str(response or "sent"),
            "sender": sender,
            "to": to,
            "subject": subject,
            "body": body,
        }


_global_fake_transport = FakeTransport()


def default_transport():
    if os.getenv("FINIMATIC_TRANSPORT") == "fake":
        return _global_fake_transport
    return SMTPTransport()


class GmailAdapter:
    def __init__(self, transport=None):
        self.transport = transport or default_transport()

    async def verify(self, user: str, password: str) -> SenderReadiness:
        if not user or not password:
            return "not_configured"
        loop = asyncio.get_running_loop()
        return "smtp_verified" if await loop.run_in_executor(None, self.transport.verify, user, password) else "failed"

    async def send_message(self, to: str, subject: str, body: str, sender: str, password: str) -> SendResult:
        try:
            loop = asyncio.get_running_loop()
            send_call = partial(self.transport.send, sender=sender, password=password, to=to, subject=subject, body=body)
            result = await loop.run_in_executor(None, send_call)
        except Exception:
            return SendResult(status="failed", provider_msg_id=None, error_code="smtp_send_failed", error_detail="SMTP send failed")
        return SendResult(
            status="success",
            provider_msg_id=result.get("message_id"),
            smtp_response=result.get("smtp_response"),
        )

    async def canary_send(self, user: str, password: str, report_recipient: str, idempotency_key: str) -> CanaryResult:
        timestamp = utcnow().astimezone(timezone.utc).isoformat()
        nonce = f"{uuid.uuid4().hex}-{timestamp}"
        subject = f"Finimatic Canary {nonce}"
        body = f"Finimatic canary send\nnonce={nonce}\ntimestamp={timestamp}\nsender={user}\n"
        send_result = await self.send_message(report_recipient, subject, body, user, password)
        if send_result.status != "success":
            return CanaryResult("failed", nonce, timestamp, idempotency_key, None, user)
        return CanaryResult("success", nonce, timestamp, idempotency_key, send_result.provider_msg_id, user)
