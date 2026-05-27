# repair/02_workflow_failure_map.md — User-Reported Failure Mapping

---

## Failure 1 — Draft approved and queued but email does not reach recipient

### Reported symptom
After pressing "Approve" or "Approve & Queue", the UI shows a success toast
("draft saved, approved, and queued") but the email does not arrive.

### Exact workflow trace

```text
1. User clicks Approve (or Approve Follow-up #2) on a draft card.

2. Frontend sends:
   POST /api/drafts/{draft_id}/approve
   (or POST /api/drafts/{draft_id}/approve-followup for follow-up path)

3. Backend: backend/app/drafts/router.py
   - Sets draft.approved = true, draft.approved_at = now()
   - Calls send/router.py or creates send_queue entry directly
   - Creates send_queue row: status=pending, scheduled_at=now()+send_delay_s
     (send_delay_s = 0 from settings → scheduled_at = right now)
   - Emits audit: draft.approved, queue.entry_created
   - Returns 200 with queue_id

4. Frontend shows toast: "draft saved, approved, and queued"
   ← UI SUCCESS is here. Email is only IN THE QUEUE, not yet sent.

5. Queue worker (background, every 30s) OR manual Process button:
   backend/app/send/queue_worker.py
   - Scans for pending entries with scheduled_at <= now()
   - Calls evaluate_policy() from backend/app/send/policy.py

6. evaluate_policy() runs ALL gates:
   - Gate: sender_readiness (canary_verified required) → may BLOCK
   - Gate: draft_approved → passes (just approved)
   - Gate: contact not deleted (deleted_at IS NULL) → may BLOCK
   - Gate: recipient_suppressed → may BLOCK
   - Gate: recipient_domain_blocked → may BLOCK
   - Gate: recipient_bounced → may BLOCK
   - Gate: recipient_replied / unsubscribed → may BLOCK
   - Gate: manually_paused → may BLOCK
   - Gate: daily_cap (500/day, currently) → passes unless 500 already sent today
   - Gate: hourly_cap (500/hour) → passes
   - Gate: send_delay_s (0s) → passes
   - Gate: send_window (00:00–23:59 IST) → passes
   - Gate: idempotency_duplicate → passes for new entry

7a. If ANY gate fails:
    - send_queue.status = 'blocked'
    - send_queue.policy_block_reasons = JSON array of reason codes
    - contact.status = 'blocked_by_policy'
    - Emits audit: queue.gate_blocked
    - EMAIL IS NOT SENT
    - UI still shows the original "queued" toast from step 4
    ← USER SEES SUCCESS TOAST BUT EMAIL IS SILENTLY BLOCKED

7b. If dry_run=true (currently false):
    - send_queue.status = 'skipped'
    - send_attempts record: status='blocked_dry_run'
    - EMAIL IS NOT SENT
    ← Currently dry_run=false so this is not the current issue

7c. If all gates pass and dry_run=false:
    - GmailAdapter.send_message() called
    - send_queue.status = 'sent'
    - send_attempts.status = 'success', provider_msg_id recorded
    - conversation_messages outbound row written
    - follow_up_sequences row created (due_at = now() + followup_interval_days)
    - Emits audit: send.success

8. Gmail may silently deliver or soft-bounce the email at the Gmail server level.
   This is outside the application's visibility unless IMAP is used to check bounces.
```

### Most likely reasons email does not arrive

| Reason | Gate/Code | Detectable? |
|--------|-----------|-------------|
| Contact was replied/unsubscribed before send | `RECIPIENT_REPLIED` | YES — blocked, policy_block_reasons set |
| Contact was suppressed | `RECIPIENT_SUPPRESSED` | YES — blocked |
| Contact was deleted (soft-deleted) | `CONTACT_DELETED` | YES — blocked |
| Daily cap already hit | `DAILY_CAP_EXCEEDED` | YES — blocked |
| Queue worker hasn't run yet | (pending status, no block) | YES — status remains pending |
| Gmail delivered to spam | (outside app scope) | NO — not detectable without IMAP |
| SMTP send failed with exception | `send_attempts.status=failed` | YES — recorded |
| Background worker not running | pending stays pending | Partially — no audit event |

### Root cause of the UX gap
The success toast fires at step 4 (queue entry created), not step 7c (actual send).
The user interprets "queued" as "sent." The Queue surface (Image 07) shows `sent` status for
entries that DID complete, but blocked/pending entries are not prominently surfaced.

### Smallest safe fix
1. Change toast copy: `"Draft approved and queued — email will send within 30 seconds if all policy gates pass."` 
2. In Queue surface, add status filter dropdown (All / Pending / Sent / Blocked / Skipped).
3. Surface `policy_block_reasons` in the BLOCKS column (it is already stored in DB but not rendered).
4. Add a "Queue Processing" indicator showing last worker run time.

---

## Failure 2 — Queue and follow-up sections causing unknown issues

### Reported symptom
General instability or unexpected behavior in Queue and Follow-ups.

### Workflow trace — Queue processing ambiguity

```text
Two processing paths exist simultaneously:

Path A — Background loop (backend/app/main.py):
  _periodic_queue_worker runs every 30s via asyncio.sleep loop.
  Also _periodic_followup_worker runs every 5 min.
  These are started in the FastAPI lifespan function.

Path B — Manual trigger (frontend/src/App.tsx QueuePanel):
  "Process" button → POST /api/queue/process
  "Process" button → POST /api/followups/process
  These call the same worker logic.
```

**Conflict risk:** If background loop fires during a manual Process click, two concurrent
workers may try to process the same queue entry. SQLite does not support row-level locking.
If two workers read the same `pending` row before either writes `sent`, both may attempt SMTP send.
Idempotency key in `send_queue` (`UNIQUE(idempotency_key)`) prevents duplicate INSERT into
send_queue, but does NOT prevent two workers from reading the same queue row and both calling
`GmailAdapter.send_message()` before either sets status=sent.

**Diagnosis:** This is a TOCTOU (time-of-check to time-of-use) race condition in the queue worker
under SQLite. Fixing requires:
1. Optimistic locking: `UPDATE send_queue SET status='processing' WHERE id=? AND status='pending'` as
   the first step, then only process rows where the UPDATE returned rowcount=1.
2. OR disable background loop and make processing manual-only.

### Workflow trace — Follow-up dispatch vs. send gap

```text
Follow-up processor (followups/service.py):
  1. Finds due follow_up_sequences rows
  2. Checks stop conditions
  3. Generates draft (Groq or template)
  4. Creates approved draft
  5. Creates send_queue entry
  6. Sets follow_up_sequences.status = 'dispatched'

At this point:
  - follow_up_sequences.status = dispatched  ← UI shows this (Image 08)
  - send_queue.status = pending  ← queued, not yet sent

Then queue worker must fire (within 30s) and ALSO pass policy:
  - If the contact was replied between dispatch and send, RECIPIENT_REPLIED blocks
  - If caps were hit, blocks
  - etc.

UI shows 'dispatched' but email may be blocked at queue level.
The follow-up surface has no cross-reference to the queue entry.
```

---

## Failure 3 — CSV import succeeds but contacts not added

### Reported symptom
CSV file with multiple columns previews correctly and commit says success,
but emails/contacts do not appear in Contacts.

### Workflow trace

```text
Step 1: Frontend parses CSV file client-side:
  frontend/src/App.tsx ImportPanel
  Papa.parse or similar client-side CSV parsing
  Rows are read from the file and displayed in preview table

Step 2: POST /api/import/preview { rows: [...] }
  backend/app/imports/router.py
  backend/app/imports/service.py: preview_import()
  For each row:
    - Validate email format
    - Check existing contacts table for duplicate email
    - Check suppressions table
    - Check blocked domains
  Result: { batch_id_temp, rows: [preview_results], summary }
  ← preview_results stored in PROCESS-LOCAL memory: `PREVIEWS[batch_id_temp]`

Step 3: User clicks Commit
  POST /api/import/commit { batch_id: batch_id_temp }
  backend/app/imports/router.py
  backend/app/imports/service.py: commit_import(batch_id_temp)
  - LOOKS UP PREVIEWS[batch_id_temp]
  ← If backend restarted between steps 2 and 3, PREVIEWS is empty → commit fails or writes 0 contacts

  If PREVIEWS entry exists:
  - Re-runs duplicate + suppression check (replay-safe)
  - Accepts rows that pass all checks
  - Inserts into contacts, import_batches, import_rows
  - Emits audit: import.committed
  - CLEARS preview from PREVIEWS dict

Step 4: Frontend refetches contacts query on success
  ← If TanStack Query invalidation key does not match, contacts list does not refresh
```

### Root causes

| Cause | Likelihood |
|-------|-----------|
| Backend restarted between preview and commit | MEDIUM (local dev, server can restart) |
| ALL rows were duplicates (already in contacts) | HIGH (after initial import, re-importing same CSV) |
| ALL rows had suppressed emails | LOW |
| ALL rows had invalid email formats | MEDIUM (CSV formatting issues) |
| ALL rows had blocked domains | LOW (only example.com blocked) |
| Frontend query invalidation did not refetch contacts | MEDIUM |
| The "Submit" button (Image 02) was used instead of Preview→Commit | UNVERIFIED |

### Multi-column CSV mapping

The ImportPanel shows fields: Email, Creator Name, Website, Notes, Tags, Info/AI Context.
The backend `imports/service.py` must map CSV columns to these fields.
A CSV with columns NOT named "email", "creator_name", etc. (e.g. "Email Address", "Full Name")
may parse with wrong field mapping, causing contacts to be created with empty email fields
(which would then fail validation and be rejected as `invalid_email`).

### Fix
1. Persist preview data in `import_batches` table with `status='preview'`; commit promotes to `status='committed'`.
2. After commit, always return per-row outcome (accepted, duplicate, suppressed, invalid) in the API response.
3. Frontend: show per-row outcome table after commit, not just a summary count.
4. Add CSV column header auto-detection with explicit field-mapping UI for non-standard headers.

---

## Failure 4 — Approve button creates follow-up instead of initial send

### Reported symptom
User presses "Approve" expecting cold send, but the button says "Approve Follow-up #2"
and may be creating a follow-up queue entry, not an initial cold send.

### Workflow trace

```text
DraftsPanel (frontend/src/App.tsx):
  Shows draft cards for a selected contact.
  If contact already has sequence_num=1 queued/sent, the approval button changes to
  "Approve Follow-up #2" or "Approve Follow-up #3".

  Button "Approve Follow-up #2":
    POST /api/drafts/{draft_id}/approve?sequence_num=2
    OR
    POST /api/followups/{followup_id}/approve
    Creates send_queue entry with sequence_num=2

  ← Toast still says "draft saved, approved, and queued"
  ← User cannot tell if they just queued an initial send or a follow-up
```

### Root cause
Button label and toast copy do not distinguish follow-up sequence from initial send.
A contact in `sent` status should only show follow-up approval buttons.
A contact in `draft_ready` should only show initial send approval buttons.
Currently both buttons produce the same toast and are visually similar.

### Fix
- Toast for initial approval: "Draft approved — initial email queued for delivery."
- Toast for follow-up: "Follow-up #N approved and queued."
- Disable "Approve Follow-up" if contact status is not `sent`.
- Show sequence number in queue table alongside contact.
