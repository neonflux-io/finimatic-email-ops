# repair/09_test_plan.md — Test Suite Extensions

---

## Current Baseline

```
python -m pytest  → 182 passed, 108 warnings
npm run build     → passed
```

All new tests must preserve this baseline. Total after repairs: target 200+.

---

## New Tests Required by Phase

### Phase 1 — Safety

#### Test: Queue Worker TOCTOU Fix (`test_queue_processing_race.py`)

```python
import asyncio
import pytest

async def test_queue_worker_no_double_send(client, db):
    """Two concurrent queue workers must not double-send the same entry."""
    # Setup: create contact, draft, queue entry
    contact = await create_test_contact(db, email="test@example.com")
    draft = await create_approved_draft(db, contact_id=contact.id)
    entry = await create_queue_entry(db, contact_id=contact.id, draft_id=draft.id)
    
    # Run two workers concurrently
    results = await asyncio.gather(
        process_single_queue_entry(entry.id, db),
        process_single_queue_entry(entry.id, db),
    )
    
    # Only one should succeed
    sent_count = sum(1 for r in results if r == "sent")
    assert sent_count == 1, f"Expected 1 send, got {sent_count}"
    
    # send_attempts should have exactly 1 record
    attempts = await get_send_attempts_for_entry(entry.id, db)
    assert len(attempts) == 1

async def test_processing_status_cleanup(client, db):
    """Entries stuck in 'processing' for >5min are reset to 'pending'."""
    entry = await create_queue_entry(db, status='processing', 
                                      claimed_at=utcnow() - timedelta(minutes=10))
    await run_cleanup_job(db)
    refreshed = await db.get(SendQueue, entry.id)
    assert refreshed.status == 'pending'
```

#### Test: Engaged Send Policy (`test_engaged_policy.py`)

```python
async def test_engaged_send_blocks_deleted_contact(client, db):
    contact = await create_test_contact(db)
    await soft_delete_contact(db, contact.id)
    
    result = await evaluate_engaged_send(
        contact=await db.get(Contact, contact.id),
        db=db, settings=mock_settings(), sender_readiness="canary_verified"
    )
    
    assert not result.all_passed
    assert "CONTACT_DELETED" in result.block_reason_codes

async def test_engaged_send_blocks_suppressed(client, db):
    contact = await create_test_contact(db, email="suppressed@example.com")
    await create_suppression(db, email="suppressed@example.com")
    
    result = await evaluate_engaged_send(
        contact=contact, db=db, settings=mock_settings(),
        sender_readiness="canary_verified"
    )
    assert "RECIPIENT_SUPPRESSED" in result.block_reason_codes

async def test_engaged_send_respects_send_window(client, db):
    """If current time is outside send window, engaged send is blocked."""
    contact = await create_test_contact(db)
    settings = mock_settings(send_window_start="09:00", send_window_end="17:00")
    
    # Simulate 3am
    with mock_utcnow(hour=3):
        result = await evaluate_engaged_send(
            contact=contact, db=db, settings=settings,
            sender_readiness="canary_verified", check_send_window=True
        )
    assert "SEND_WINDOW_CLOSED" in result.block_reason_codes

async def test_engaged_send_passes_all_gates(client, db):
    """Clean contact in window passes all engaged gates."""
    contact = await create_test_contact(db, status="replied")
    settings = mock_settings()  # 00:00-23:59 window
    
    result = await evaluate_engaged_send(
        contact=contact, db=db, settings=settings,
        sender_readiness="canary_verified"
    )
    assert result.all_passed
```

#### Test: Auto-Reply Autonomous Safety (`test_auto_reply.py` additions)

```python
async def test_autonomous_send_blocked_on_objection(client, db):
    """Autonomous mode must NOT send when reply is classified as OBJECTION."""
    contact = await create_test_contact(db, status="replied")
    reply = await create_reply(db, contact_id=contact.id, 
                                classified_as="reply", intent="objection")
    settings = await set_autonomous_mode(db)
    
    result = await try_auto_reply(db, contact, reply, settings)
    
    assert result.sent is False
    assert result.skip_reason == "INTENT_OBJECTION_BLOCKED"

async def test_autonomous_send_blocked_on_complaint(client, db):
    reply = await create_reply(db, classified_as="complaint")
    result = await try_auto_reply(db, contact, reply, settings)
    assert result.sent is False

async def test_autonomous_send_allowed_on_positive_interest(client, db):
    reply = await create_reply(db, classified_as="reply", intent="positive_interest")
    result = await try_auto_reply(db, contact, reply, settings)
    # Should proceed to send (fake transport)
    assert result.sent is True
```

#### Test: IMAP Not Blocking Event Loop (`test_import_policy_ai_followups.py` addition)

```python
async def test_imap_fetch_runs_in_executor(client, db):
    """IMAP fetch should complete without blocking asyncio event loop."""
    import time
    
    start = time.monotonic()
    # Mock a slow IMAP connection
    with mock_slow_imap(delay=2.0):
        task = asyncio.create_task(fetch_replies_async(
            gmail_user="test@gmail.com",
            app_password="xxx",
            db=db
        ))
        # Event loop should remain responsive during IMAP fetch
        await asyncio.sleep(0.1)  # Should not be blocked
        elapsed = time.monotonic() - start
    
    assert elapsed < 0.5, "Event loop was blocked during IMAP fetch"
    await task  # Complete the task

async def test_imap_timeout_updates_provider_health(client, db):
    """IMAP timeout should record provider_health failure, not crash."""
    with mock_imap_timeout():
        await fetch_replies_async("test@gmail.com", "xxx", db)
    
    health = await db.execute(
        select(ProviderHealth).where(ProviderHealth.provider == "imap"))
    assert health.scalar().status == "failed"
    assert health.scalar().error_code == "TimeoutError"
```

#### Test: Conversations GET Read-Only (`test_conversations_get_readonly.py`)

```python
async def test_get_conversations_does_not_write(client, db):
    """GET /api/conversations should not write to DB."""
    contact = await create_test_contact_with_history(db)
    
    # Count rows before
    before_count = await count_conversation_messages(db)
    
    # GET conversations
    response = await client.get("/api/conversations")
    assert response.status_code == 200
    
    # Count rows after — must be same
    after_count = await count_conversation_messages(db)
    assert before_count == after_count, (
        f"GET wrote {after_count - before_count} new conversation_messages rows"
    )

async def test_backfill_post_endpoint_exists(client, db):
    """POST /api/conversations/{id}/backfill should exist and work."""
    contact = await create_test_contact(db)
    response = await client.post(f"/api/conversations/{contact.id}/backfill")
    assert response.status_code in (200, 204)
```

---

### Phase 2 — Reliability

#### Test: Import Preview Survives Restart (`test_import_policy_ai_followups.py` additions)

```python
async def test_import_preview_persists_in_db(client, db):
    """Preview data should survive if the in-memory dict is cleared."""
    response = await client.post("/api/import/preview", json={
        "rows": [{"email": "newcontact@example.com", "creator_name": "Test"}]
    })
    batch_id = response.json()["batch_id"]
    
    # Simulate in-memory loss by clearing PREVIEWS (if still used)
    from backend.app.imports.service import PREVIEWS
    PREVIEWS.clear()
    
    # Commit should still work (data is in DB)
    commit_response = await client.post("/api/import/commit", json={"batch_id": batch_id})
    assert commit_response.status_code == 200
    assert commit_response.json()["accepted"] == 1

async def test_import_commit_returns_per_row_outcomes(client, db):
    """Commit response should include per-row outcome details."""
    await create_suppression(db, email="suppressed@example.com")
    
    response = await client.post("/api/import/preview", json={
        "rows": [
            {"email": "new@example.com", "creator_name": "Good"},
            {"email": "suppressed@example.com", "creator_name": "Suppressed"},
            {"email": "notanemail", "creator_name": "Bad"},
        ]
    })
    batch_id = response.json()["batch_id"]
    
    commit_response = await client.post("/api/import/commit", json={"batch_id": batch_id})
    data = commit_response.json()
    
    assert data["accepted"] == 1
    assert data["suppressed"] == 1
    assert data["invalid_email"] == 1
    assert len(data["rows"]) == 3  # Per-row outcomes returned

async def test_import_rejects_duplicate_email_existing_contact(client, db):
    """CSV row with email matching existing contact is rejected as duplicate."""
    await create_test_contact(db, email="existing@example.com")
    
    response = await client.post("/api/import/preview", json={
        "rows": [{"email": "existing@example.com", "creator_name": "Dup"}]
    })
    rows = response.json()["rows"]
    assert rows[0]["status"] == "duplicate"
```

#### Test: Contact Source Field (`test_contacts_delete.py` addition)

```python
async def test_manual_contact_source_not_doubled(client, db):
    """Manual contact creation should have source='manual', not 'manualmanual'."""
    response = await client.post("/api/contacts", json={
        "email": "test@example.com",
        "creator_name": "Test",
        "source": "manual"
    })
    assert response.status_code == 200
    contact = response.json()
    assert contact["source"] == "manual"
    assert "manualmanual" not in contact["source"]
```

---

### Phase 3 — Hygiene

#### Test: Schema Migration Parity (`test_schema_migration.py` NEW FILE)

```python
def test_alembic_produces_all_17_tables():
    """alembic upgrade head on fresh DB must create all 17 expected tables."""
    import subprocess, os
    from sqlalchemy import create_engine, inspect
    
    test_db = "test_migration_parity.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///./{test_db}"}
    
    try:
        result = subprocess.run(
            ["alembic", "upgrade", "head"],
            capture_output=True, text=True, env=env, cwd="."
        )
        assert result.returncode == 0, f"Alembic failed:\n{result.stderr}"
        
        engine = create_engine(f"sqlite:///./{test_db}")
        tables = inspect(engine).get_table_names()
        
        expected = [
            "agent_sessions", "audit_events", "campaign_plans", "contacts",
            "conversation_messages", "drafts", "follow_up_sequences",
            "import_batches", "import_rows", "pending_email_actions",
            "provider_health", "replies", "send_attempts", "send_queue",
            "settings", "suppressions", "templates"
        ]
        missing = [t for t in expected if t not in tables]
        assert not missing, f"Tables missing from Alembic schema: {missing}"
    finally:
        if os.path.exists(test_db):
            os.unlink(test_db)

def test_agent_sessions_has_all_columns():
    """agent_sessions from Alembic must include extra runtime-added columns."""
    from sqlalchemy import create_engine, inspect
    from sqlalchemy.orm import Session
    
    # Use the live models to create expected schema
    from backend.app.db.models import Base, AgentSession
    engine = create_engine("sqlite:///./test_model_columns.db")
    Base.metadata.create_all(engine)
    
    cols = {c["name"] for c in inspect(engine).get_columns("agent_sessions")}
    expected = {"id", "session_hash", "contact_id", "context_loaded_at", 
                "contact_name_map", "turn_history", "current_channel",
                "created_at", "updated_at"}
    missing = expected - cols
    assert not missing, f"agent_sessions missing columns: {missing}"
    
    import os; os.unlink("test_model_columns.db")
```

---

## Manual / Browser Verification Checklist

After all fixes are applied, verify manually:

1. **Queue BLOCKS column**: Manually block a send (suppress a contact, then approve a draft for them). Navigate to Queue. Verify BLOCKS column shows `RECIPIENT_SUPPRESSED` badge.

2. **Toast distinction**: Approve a brand new draft for a `draft_ready` contact. Verify toast says "Draft approved — email queued". Then approve a follow-up. Verify toast says "Follow-up #2 queued".

3. **Deleted contact block**: Create contact, approve draft, queue entry created. Delete contact. Click Process in Queue. Verify entry moves to `blocked` with `CONTACT_DELETED` reason.

4. **Autonomous mode objection block**: In Auto-Reply settings, confirm mode is "Autonomous". In Replies/Stops, manually create a reply with class=reply and intent=objection. Run auto-reply check. Verify no autonomous send fires.

5. **Import restart**: Preview a CSV, restart the backend (ctrl-C uvicorn and restart). Click Commit with the same batch_id. Verify contacts are created (preview persisted in DB).

6. **IMAP timeout non-blocking**: Set IMAP fetch interval to 1 minute. Disconnect network. Verify app remains responsive; provider health shows imap=failed; no 500 errors on other endpoints.

---

## Regression Test Commands

```powershell
# Full suite (baseline: 182 passed)
cd C:\Users\rossd\OneDrive\Documents\notes\email\backend
python -m pytest -v --tb=short 2>&1 | tail -20

# Specific new test files
python -m pytest tests/test_queue_processing_race.py -v
python -m pytest tests/test_engaged_policy.py -v
python -m pytest tests/test_conversations_get_readonly.py -v
python -m pytest tests/test_schema_migration.py -v

# Auto-reply safety
python -m pytest tests/test_auto_reply.py -v -k "objection"

# Import parity
python -m pytest tests/test_import_policy_ai_followups.py -v -k "preview"

# Confirm no deprecation warnings for utcnow
python -m pytest -W error::DeprecationWarning -k "agent" 2>&1 | grep -E "PASSED|FAILED|ERROR"

# Frontend build
cd C:\Users\rossd\OneDrive\Documents\notes\email\frontend
npm run build 2>&1 | tail -5
```
