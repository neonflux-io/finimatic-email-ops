import importlib

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'finimatic.db'}")
    monkeypatch.setenv("FERNET_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("FINIMATIC_TRANSPORT", "fake")
    monkeypatch.setenv("FINIMATIC_DISABLE_SCHEDULER", "1")

    import app.main

    importlib.reload(app.main)
    with TestClient(app.main.create_app()) as test_client:
        yield test_client


def configure_sender(client, *, canary_verified=False, dry_run=True):
    payload = {
        "gmail_user": "sender@example.com",
        "gmail_app_password": "valid-app-password",
        "report_recipient": "report@example.com",
        "groq_keys": "groq-test-one\ngroq-test-two",
        "gemini_keys": "gemini-test-one\ngemini-test-two",
        "daily_send_cap": 50,
        "hourly_send_cap": 10,
        "send_delay_s": 0,
        "followup_interval_days": 1,
        "max_followups_per_lead": 2,
        "campaign_context": "Fake campaign context",
        "send_window_start": "00:00",
        "send_window_end": "23:59",
        "send_timezone": "UTC",
        "imap_fetch_interval_minutes": 10,
        "dry_run": dry_run,
        "canary_verified": canary_verified,
        "sender_name": "Ross Dmello",
        "sender_role": "AI Systems Engineer",
        "sender_offer": "I help course teams automate student Q&A with grounded RAG chatbots",
        "sender_signature": "Best regards\nRoss Dmello\nAI Systems Engineer",
    }
    response = client.post("/api/settings", json=payload)
    assert response.status_code == 200
    return response.json()
