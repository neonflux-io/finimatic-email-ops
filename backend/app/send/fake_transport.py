from __future__ import annotations

import uuid


class FakeTransport:
    """Automated-test transport. It never calls smtp.gmail.com."""

    def __init__(self):
        self.sent: list[dict] = []

    def verify(self, user: str, password: str) -> bool:
        return bool(user and password and password != "wrong-password")

    def send(self, *, sender: str, password: str, to: str, subject: str, body: str) -> dict:
        if not self.verify(sender, password):
            raise RuntimeError("SMTP authentication failed")
        message = {
            "message_id": f"fake-{uuid.uuid4().hex}",
            "sender": sender,
            "to": to,
            "subject": subject,
            "body": body,
            "smtp_response": "250 OK fake",
        }
        self.sent.append(message)
        return message
