# repair/08_coding_agent_prompt.md — Paste-Ready Coding Agent Prompt

---

Paste the following prompt to a coding agent that has access to the full Finimatic workspace.
The agent MUST read the repair docs before writing any code.

---

```
You are a senior backend/frontend repair engineer for the Finimatic cold-email operations application.

WORKSPACE: C:\Users\rossd\OneDrive\Documents\notes\email

MANDATORY READS BEFORE ANY CODE:
1. Read repair.md (executive plan, severity table, ordered fixes)
2. Read repair/01_image_evidence.md (screenshot analysis)
3. Read repair/02_workflow_failure_map.md (user failures mapped to source)
4. Read repair/03_send_policy_unification.md (send path fixes)
5. Read repair/04_import_contact_repair.md (import fixes)
6. Read repair/05_queue_followup_repair.md (queue fixes)
7. Read repair/06_schema_migration_repair.md (migration fixes)
8. Read repair/07_security_and_secret_review.md (security fixes)
9. Read repair/09_test_plan.md (test requirements)

THEN READ these source files (do NOT rely on old docs):
- backend/app/main.py
- backend/app/db/models.py
- backend/app/db/session.py
- backend/app/send/policy.py
- backend/app/send/queue_worker.py
- backend/app/conversations/router.py
- backend/app/conversations/auto_reply_service.py
- backend/app/agent/tools.py
- backend/app/imports/service.py
- backend/app/contacts/router.py
- frontend/src/App.tsx (specifically QueuePanel, ImportPanel, DraftsPanel)
- frontend/src/api/client.ts

DO NOT READ OR PRINT:
- KEYS.md
- backend/.env
- Any file containing raw credentials

EXECUTION ORDER (do in this order, verify tests pass between phases):

PHASE 1 — SAFETY (P0/P1 issues that affect live sends):

Fix 1: backend/app/send/queue_worker.py
  Problem: TOCTOU race condition — two workers can process same queue entry.
  Fix: Add optimistic status='processing' claim step.
  - Add 'processing' to valid send_queue status values in models.py.
  - In queue worker, execute UPDATE SET status='processing' WHERE id=? AND status='pending'.
  - Only process entries where UPDATE rowcount==1.
  - Add cleanup: reset status='pending' for 'processing' entries older than 5 minutes.
  Test: backend/tests/test_queue_processing_race.py

Fix 2: backend/app/send/engaged_policy.py (NEW FILE)
  Problem: conversation, auto-reply, and agent sends miss critical safety gates.
  Missing: contact.deleted_at check, send_window check.
  Fix: Create evaluate_engaged_send() function per repair/03_send_policy_unification.md.
  Wire into:
    - backend/app/conversations/router.py (replace _engaged_send_block_reasons)
    - backend/app/conversations/auto_reply_service.py (replace inline checks)
    - backend/app/agent/tools.py (replace duplicate _engaged_send_block_reasons)
  Test: backend/tests/test_engaged_policy.py

Fix 3: backend/app/conversations/auto_reply_service.py
  Problem: autonomous send fires for OBJECTION-classified replies.
  Fix: Block autonomous send when reply intent is OBJECTION, HOSTILE, COMPLAINT, or UNKNOWN.
  Add check: if reply.classified_as in ('unsubscribe', 'bounce', 'complaint') OR
              reply.intent in ('objection', 'hostile', 'unknown') → skip autonomous send.
  Test: backend/tests/test_auto_reply.py (add test_autonomous_blocked_on_objection)

Fix 4: backend/app/replies/imap_fetcher.py
  Problem: synchronous imaplib blocks event loop on timeout.
  Fix: Wrap all imaplib operations in asyncio.get_event_loop().run_in_executor(None, ...).
  Add timeout=30 to IMAP4_SSL constructor.
  Test: backend/tests/test_import_policy_ai_followups.py (existing IMAP lock test)

Fix 5: backend/app/conversations/router.py
  Problem: GET /api/conversations and GET /api/conversations/{id} commit writes.
  Fix: Remove DB commits from GET handlers. Move backfill logic to POST /backfill endpoint.
  Test: backend/tests/test_conversations_get_readonly.py

PHASE 2 — RELIABILITY:

Fix 6: backend/app/imports/service.py
  Problem: PREVIEWS dict is process-local; lost on restart.
  Fix: Persist preview in import_batches with status='preview'.
  - Add status column to import_batches in models.py.
  - preview_import() writes ImportBatch(status='preview') and ImportRow records.
  - commit_import() finds batch by id AND status='preview', promotes to 'committed'.
  Test: backend/tests/test_import_policy_ai_followups.py (add test for restart scenario)

Fix 7: frontend/src/App.tsx — QueuePanel
  Problem: BLOCKS column not rendering, contact shows as UUID.
  Fix 7a: Parse policy_block_reasons JSON and render as badge pills in BLOCKS column.
  Fix 7b: Show contact_email instead of contact_id in Contact column (requires API to return it).
  Fix 7c: Add status filter dropdown (All / Pending / Sent / Blocked / Skipped).
  Also update: backend/app/send/router.py to return contact_email/contact_name in queue list.
  Test: manual browser verification.

Fix 8: frontend/src/App.tsx — QueuePanel + DraftsPanel
  Problem: toast "draft saved, approved, and queued" is misleading.
  Fix: 
    - Initial approval toast: "Draft approved — email queued for delivery. May take ~30 seconds."
    - Follow-up approval toast: "Follow-up #N approved and queued."
    - Show sequence_num in the toast.
  Test: manual verification.

Fix 9: backend/app/contacts/router.py
  Problem: source field shows "manualmanual" (double-write).
  Fix: Find where source is being concatenated/doubled in contact creation handler.
  Likely: source=request.source + some default is being appended.
  Fix to single assignment: contact.source = source_param (not += or +).
  Test: backend/tests/test_contacts_delete.py (add create contact and verify source field).

PHASE 3 — HYGIENE:

Fix 10: Replace all datetime.utcnow() in agent/campaign code with core/time.py:utcnow().
  Files: backend/app/agent/service.py, backend/app/campaigns/router.py
  Test: run python -m pytest and confirm deprecation warning count drops.

Fix 11: frontend/src/features/floating-assistant/assistantStore.ts
  Problem: localStorage stores action_id, draft_id, contact_id.
  Fix: Store only action_id and expiry. Add GET /api/agent/pending/{action_id} endpoint
  to fetch current status for display-only card.
  Test: manually verify pending card survives reload but shows expiry status from backend.

Fix 12: frontend/src/features/floating-assistant/AssistantWidget.tsx
  Problem: accepts attachments, sends metadata only — misleading UX.
  Fix: Show notice below file attach button: "Attachment filename is sent to assistant. File content is not processed."
  Test: manual verification.

Fix 13: frontend/src/styles.css + frontend/src/features/floating-assistant/AssistantWidget.css
  Problem: assistant z-index 80 overlays modal z-index 40.
  Fix: Option A — raise modal backdrop z-index to 90. Option B — set assistant z-index to 30 when modal is open.
  Test: open a modal, verify assistant doesn't overlay it.

Fix 14: backend/app/db/migrations/
  Problem: Alembic does not rebuild live schema.
  Fix: run alembic revision --autogenerate -m "0004_full_schema_parity".
  Review generated migration carefully before applying.
  Test: alembic upgrade head on empty DB, then compare columns to models.py.

AFTER EACH PHASE, RUN:

  cd backend && python -m pytest -v
  cd frontend && npm run build

Both must pass. Do not advance to next phase if tests fail.

CONSTRAINTS:
- Do NOT change the API contract for existing endpoints (only add new fields/endpoints).
- Do NOT switch from SQLite to PostgreSQL (preserve current dev setup).
- Do NOT add Groq/Gemini keys to any Vite env var.
- Do NOT remove the existing autonomous auto-reply mode — just add the quality gate.
- Do NOT change the queue policy gate order (only add engaged_policy.py alongside it).
- Preserve all existing test behavior. Add new tests, don't delete old ones.
- If a fix requires a new migration, write it. Don't rely on startup create_all alone.
- After EACH file edit, immediately run the relevant test file to catch regressions.

REPORT BACK:
After each phase, output:
- Files changed
- Lines changed (diff summary)
- Tests added
- Test result (pass/fail counts)
- Any unexpected behavior found during implementation
```
