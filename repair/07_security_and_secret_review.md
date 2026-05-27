# repair/07_security_and_secret_review.md — Security Audit

---

## 1. Secret Exposure Checks

### API responses (PASS — no raw secrets returned)
- `GET /api/settings` returns `groq_keys_count`, `groq_keys_fingerprints`, never raw keys.
- Provider health returns status/error_code, not credentials.
- Audit events have redaction via `audit/service.py:redact_payload()`.
- Image 15 confirms Groq/Gemini textareas are empty after save (cleared from React state).

### Runtime safe GET scan result (from architecture_test.md)
- No `gsk_`, `AIza`, or plaintext password patterns in API responses.
- Tests contain intentionally fake key-shaped strings for redaction testing — these are NOT live secrets.

### CONCERN: Startup `crypto.py` auto-generates `.env` file
`backend/app/core/crypto.py` writes `FERNET_KEY` to `backend/.env` if absent.
Risk: on a CI/CD system or Docker build, the key is generated and written to disk in the container image, which could be leaked in container layers.
**Fix**: Log a warning and FAIL startup if `FERNET_KEY` is not set in production. Auto-generation is acceptable for local-only dev.

---

## 2. Send Confirmation Gate Audit

### Queue cold send — PASS
Has 11 canonical gates. Requires `canary_verified=true`, `draft.approved=true`.

### Conversation direct send — PARTIAL PASS
Has engaged gates but MISSING:
- `contact.deleted_at IS NULL` check
- `send_window` check

### Auto-reply autonomous send — PARTIAL PASS
Has `_can_auto_reply()` guard which checks readiness and safety class.
MISSING:
- `contact.deleted_at IS NULL` check  
- `send_window` check
- CONFIRMS: sends without operator approval in autonomous mode (Image 11, Image 14)

### Agent confirmed send — PARTIAL PASS
Has pending-action harness (180s TTL, session validation, draft hash validation).
MISSING:
- `contact.deleted_at IS NULL` check (agent could have stored a deleted contact's id)
- `send_window` check

### Risk scenario: deleted contact receives email
```
1. Operator imports contact A.
2. Operator approves initial draft → sent.
3. Contact A replies.
4. Operator deletes Contact A.
5. Auto-reply (in autonomous mode) fires on the reply → does NOT check deleted_at → SENDS.
```
This is a P1 safety issue. Fix is documented in repair/03_send_policy_unification.md.

---

## 3. Autonomous Auto-Reply Consent Model

### Current state (Image 11 + Image 14)
- Reply Mode = "Autonomous (send immediately)"
- Min Gap = 0 minutes
- A bold warning is shown in Settings: "In Autonomous mode, replies will be sent without your review."
- The operator has checked the Enable checkbox and selected autonomous mode.

### Conflict with original product contract
Original `PRD.md` / `AI_INTEGRATION.md` state: "AI MUST NOT approve drafts, trigger sends, suppress contacts, override policy gates."
Current autonomous mode allows AI to trigger sends directly.

### Assessment
This is a KNOWN CONFLICT labeled in `relation.md` as conflict #11.
The operator has actively enabled this mode with the warning visible.
However, it creates risk in these edge cases:
1. **OBJECTION-intent reply**: crce.9955.ce@gmail.com sent an objection (Image 09). Autonomous auto-reply may respond to this objection with a generated email, which could be inappropriate.
2. **Quality gate bypass**: If the quality classification fails (e.g., uncertain intent), does autonomous mode still send?

### Recommendation
Add a **safety classification gate**: autonomous send should be blocked for replies classified as:
- `OBJECTION`
- `HOSTILE`  
- `COMPLAINT`
- `UNKNOWN`

Only `POSITIVE_INTEREST`, `QUESTION`, and `NEUTRAL` replies should trigger autonomous send.

---

## 4. Frontend Storage Audit

### localStorage (assistantStore.ts)
```
Stored: conversation history, current conversation id, UI state, model preference
Also stored: pending action metadata:
  - action_id
  - contact_id  
  - draft_id
  - to (email address)
  - subject
  - source_label
  - expiry (timestamp)
```

**Body is stripped** — the draft body is NOT stored in localStorage. ✅

**Concern**: `action_id` + `draft_id` + `contact_id` retained across page reloads.
If a stale pending action shows a "Confirm Send" card after reload but the action has expired (>180s), the UI should show "Expired" not "Confirm". The backend validates expiry at confirm time, so this is a UX issue not a security bypass.

**Fix**: Store only `action_id` + `expiry` in localStorage. Fetch current status from `GET /api/agent/confirm-status/{action_id}` (new endpoint needed) to hydrate the display-only card.

### sessionStorage (assistantApi.ts)
```
Stored: va_session_token (tab-scoped session identifier)
```
This is acceptable — session token is not a secret, it's used as a session key hashed server-side.

### No raw provider keys in any frontend storage — CONFIRMED ✅

---

## 5. IMAP Blocking Vulnerability

### Current behavior (CONFIRMED from relation.md conflict #10 and Image 01)
`backend/app/replies/imap_fetcher.py` uses synchronous `imaplib`.
The IMAP fetch is called from:
1. `POST /api/replies/fetch` — direct request handler
2. APScheduler job `_scheduled_imap_reply_fetch` every N minutes

`AGENTS.md` hard rule: "imaplib and smtplib are synchronous — always wrap in run_in_executor"

### Current IMAP fetch path (inferred)
```python
# WRONG — blocks event loop:
def fetch_replies(gmail_user, app_password):
    imap = imaplib.IMAP4_SSL("imap.gmail.com")
    imap.login(gmail_user, app_password)
    ...
```

The APScheduler job is likely running in the asyncio context without `run_in_executor`.
When IMAP times out (as currently observed), the timeout blocks the scheduler loop,
delaying all other scheduled tasks.

### Fix
```python
# backend/app/replies/imap_fetcher.py
import asyncio

async def fetch_replies_async(gmail_user, app_password, db):
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,  # default thread pool
        lambda: _fetch_replies_sync(gmail_user, app_password)
    )
    await _process_fetched_replies(result, db)

def _fetch_replies_sync(gmail_user, app_password):
    imap = imaplib.IMAP4_SSL("imap.gmail.com", timeout=30)
    try:
        imap.login(gmail_user, app_password)
        # ... fetch logic
    except imaplib.IMAP4.error as e:
        raise
    finally:
        try:
            imap.logout()
        except Exception:
            pass
```

---

## 6. Conversation GET Backfill Writes

### Confirmed (relation.md conflict #7)
`GET /api/conversations` and `GET /api/conversations/{contact_id}` run backfill logic that
COMMITS new `conversation_messages` rows before returning.

### Why this is a P1 issue
- Browser prefetch, React Query background refetch, or monitoring tools hitting these endpoints
  will create DB writes without operator intent.
- If the backfill logic has a bug, every page load of Conversations can corrupt thread data.
- Makes GET endpoints non-idempotent from a DB perspective.

### Fix
```python
# conversations/router.py

# BEFORE: GET backfills and commits
@router.get("/")
async def list_conversations(db=Depends(get_db)):
    await _backfill_messages(db)  # WRITES TO DB
    await db.commit()
    return conversations

# AFTER: GET is read-only; backfill is a separate POST
@router.get("/")
async def list_conversations(db=Depends(get_db)):
    return await _load_conversations_from_db(db)  # READ ONLY

@router.post("/{contact_id}/backfill")
async def backfill_conversation(contact_id: str, db=Depends(get_db)):
    await _backfill_messages_for_contact(contact_id, db)
    await db.commit()
    return {"backfilled": True}
```

Frontend: call the backfill POST explicitly when user navigates to Conversations surface,
not on every GET poll.

---

## 7. SQLite Concurrency Under Multiple Workers

### Risk
SQLite with WAL mode can handle multiple readers but only one writer at a time.
With three background workers (queue, follow-up, IMAP) plus request handlers all
writing simultaneously, SQLite can return `database is locked` errors.

### Observed risk factors
- Background queue loop every 30s — writes send_attempts, queue status, conversation_messages, follow_up_sequences.
- Background follow-up loop every 5min — writes follow_up_sequences, drafts, send_queue.
- IMAP fetch every 2min — writes replies, conversation_messages, contact status.
- Request handlers write on any mutation endpoint.

### Mitigation (without switching to PostgreSQL)
```python
# backend/app/db/session.py — add SQLite connection args
engine = create_engine(
    database_url,
    connect_args={
        "check_same_thread": False,
        "timeout": 30,  # wait up to 30s for lock
    },
    pool_timeout=30,
)
```

For production, migrate to PostgreSQL as the stack doc recommends.

---

## Summary Risk Table

| Issue | Severity | Exploitable? | Fix Location |
|-------|----------|-------------|--------------|
| Deleted contact can receive via non-queue paths | P1 | Yes, silently | `engaged_policy.py` |
| Autonomous auto-reply sends on OBJECTION replies | P1 | Yes, unintended | `auto_reply_service.py` quality gate |
| IMAP blocking event loop on timeout | P1 | Causes service degradation | `imap_fetcher.py` |
| Conversation GET commits writes | P1 | Side effects on load | `conversations/router.py` |
| Queue worker TOCTOU race | P1 | Double send risk | `queue_worker.py` |
| localStorage stores action metadata | P2 | Stale UI, not a secret leak | `assistantStore.ts` |
| Send window not enforced for engaged sends | P2 | Sends at 3am | `engaged_policy.py` |
| Fernet key auto-write to disk in CI/CD | P2 | Container layer leak | `crypto.py` |
