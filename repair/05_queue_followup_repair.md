# repair/05_queue_followup_repair.md — Queue and Follow-Up Lifecycle Repair

---

## Queue Lifecycle

```text
send_queue.status values:
  pending  → entry exists, not yet processed
  sent     → SMTP send succeeded (send_attempts.status=success exists)
  failed   → SMTP attempt failed (send_attempts.status=failed)
  blocked  → policy gate failed (policy_block_reasons populated)
  skipped  → dry_run=true, not sent
  cancelled → contact deleted or manually cancelled
```

---

## Issue R-02: Queue Processing Ambiguity

### Background loop
`backend/app/main.py` starts `_periodic_queue_worker()` in FastAPI lifespan.
This function runs `asyncio.sleep(30)` in a loop and calls the queue processing logic.
It also starts `_periodic_followup_worker()` every 300s (5 min).

### Manual trigger
`POST /api/queue/process` — calls the same worker logic on demand.
`POST /api/followups/process` — same for follow-ups.

### Race condition (TOCTOU)

```python
# Current vulnerable pattern (inferred from architecture):
async def _process_queue_entry(entry, db):
    # STEP 1: Read status
    if entry.status != 'pending':
        return
    
    # STEP 2: Evaluate policy
    decision = await evaluate_policy(entry, db)
    
    # RACE WINDOW: background worker reads same entry as 'pending' here
    
    # STEP 3: Write outcome
    entry.status = 'sent' if decision.all_passed else 'blocked'
    await db.commit()
    
    # If two workers both reach step 2 on the same entry, both may call SMTP.
```

### Fix: Optimistic locking with status='processing'

```python
async def _try_claim_queue_entry(entry_id: str, db) -> bool:
    """
    Atomically claim a queue entry for processing.
    Returns True if this worker owns the entry.
    """
    result = await db.execute(
        text("""
        UPDATE send_queue 
        SET status = 'processing' 
        WHERE id = :id AND status = 'pending'
        """),
        {"id": entry_id}
    )
    await db.commit()
    return result.rowcount == 1  # Only one worker wins

async def process_queue(db):
    entries = await db.execute(
        select(SendQueue).where(
            SendQueue.status.in_(['pending', 'skipped']),
            SendQueue.scheduled_at <= utcnow()
        )
    )
    for entry in entries.scalars():
        if not await _try_claim_queue_entry(entry.id, db):
            continue  # Another worker claimed it
        # Now safely process entry
        await _process_claimed_entry(entry, db)
```

Add `'processing'` to the valid status values in the model.
Add a cleanup job that resets `processing` entries older than 5 minutes back to `pending`
(handles crash recovery).

---

## Issue R-10: BLOCKS Column Not Rendering

### Evidence
Image 07 shows Queue table with a BLOCKS column but all cells are empty.
`send_queue.policy_block_reasons` is stored as a JSON array of reason code strings.

### Frontend fix (App.tsx QueuePanel)

```tsx
// Current (likely):
<td>{entry.policy_block_reasons}</td>

// Fix — parse and render:
<td>
  {entry.policy_block_reasons 
    ? JSON.parse(entry.policy_block_reasons).map((code: string) => (
        <span key={code} className="badge badge-error text-xs mr-1">{code}</span>
      ))
    : null
  }
</td>
```

---

## Issue: Contact UUID in Queue Table

### Evidence
Image 07 shows contact column as UUID hex strings like `bad1154525e04feb9b03e3b3b51f1c45`.
This is unhelpful for operators.

### Fix
Join or enrich the queue API response to include `contact_email` and `contact_name`:

```python
# backend/app/send/router.py
# In queue list endpoint, join contacts:
result = await db.execute(
    select(SendQueue, Contact.email, Contact.creator_name)
    .outerjoin(Contact, SendQueue.contact_id == Contact.id)
)
```

Return `contact_email` and `contact_name` fields in the queue entry response.

---

## Issue: Approve Follow-up #2 Confusion (R-08)

### How follow-up approval works

```text
1. Queue worker sends initial email (sequence_num=1).
2. Queue worker creates FollowUpSequence(sequence_num=2, status='due', due_at=now()+3days).
3. Follow-up processor runs:
   - Checks stop conditions.
   - If not stopped: calls followups/service.py to generate draft.
   - Creates approved draft.
   - Creates SendQueue entry with sequence_num=2.
   - Sets FollowUpSequence.status = 'dispatched'.
4. Queue worker sends follow-up (sequence_num=2) if policy passes.
```

### What "Approve Follow-up #2" button does (Image 04)

The button in the Drafts surface for a contact that is already in `sent` status
calls the follow-up approval path directly from the Drafts surface, bypassing step 3
(the automated follow-up processor). This is a MANUAL follow-up approval for an
already-approved initial draft.

This is correct behavior BUT the UI makes it look identical to initial send approval.

### Fixes
1. **Rename button**: "Queue Follow-up #2" instead of "Approve Follow-up #2" (clearer intent).
2. **Toast distinction**: "Follow-up #2 queued — will send in N days if no reply received."
3. **Disable condition**: Show follow-up approval button only if `follow_up_sequences` for
   this contact has `sequence_num=2, status='due'`. If it's already dispatched, hide the button.

---

## Issue: Why Queued Emails May Not Reach Recipients — Full Checklist

### Gate failures (silently block after toast shows "queued")

```
RECIPIENT_REPLIED        → contact replied; queue was pending before reply was logged
RECIPIENT_SUPPRESSED     → contact was suppressed after queue entry was created
CONTACT_DELETED          → contact was soft-deleted after queue entry was created
DAILY_CAP_EXCEEDED       → 500 sends/day already hit (unlikely with 500 cap)
IDEMPOTENCY_DUPLICATE    → same idempotency key exists with status=sent (double-approval)
SENDER_NOT_VERIFIED      → canary_verified reset somehow (unlikely)
```

### Queue worker not running

If `_periodic_queue_worker` crashes silently (unhandled exception in the loop), the
background loop stops. The 30-second sleep/loop does not restart on exception.

**Fix**: Wrap the entire loop body in try/except and log + continue on error:

```python
async def _periodic_queue_worker():
    while True:
        try:
            await _run_queue_worker_once()
        except Exception as e:
            logger.error(f"Queue worker error: {e}")
        await asyncio.sleep(30)
```

### SMTP delivery failures

Even if `send_queue.status=sent` and `send_attempts.status=success`, Gmail may:
- Soft-bounce the email (delivery to spam)
- Rate-limit the account
- Reject the email on receiving server

These are outside the app's visibility without IMAP bounce detection.
With Send Delay=0 and caps at 500, bulk sends look like spam.

**Recommendation**: Set Send Delay=60 (minimum 1 minute between sends) and Hourly Cap=20
for sustainable deliverability.

---

## Follow-Up Stop Condition Verification

### Current stop conditions (confirmed from architecture_test.md)
```
contact.status IN (replied, unsubscribed, suppressed, bounced, manually_paused)
OR suppressions table match
OR bounce record exists
OR follow_up_sequences count >= max_followups_per_lead
OR cap/window block
OR idempotency duplicate
```

### Evidence (Image 08)
- `CONTACT_DELETED` is a stop reason — this is a NEWER stop condition not in the original docs.
- `RECIPIENT_REPLIED` is working correctly.

### Gap: `CONTACT_DELETED` needs to cascade to queue cancellation
When a contact is soft-deleted, `contacts/router.py` should:
1. Cancel pending `send_queue` entries (set status='cancelled').
2. Stop `follow_up_sequences` entries (set status='stopped', stop_reason='CONTACT_DELETED').
3. Currently: follow_up stop works (Image 08 confirms). Queue cancellation needs verification.

### Test to add
```python
async def test_deleted_contact_queue_cancelled():
    # Create contact, draft, queue entry
    # Soft-delete contact
    # Assert send_queue.status == 'cancelled'
    # Assert follow_up_sequences.status == 'stopped'
```
