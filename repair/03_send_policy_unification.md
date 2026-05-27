# repair/03_send_policy_unification.md — Send Path Comparison and Consolidation

---

## Current Send Path Inventory

| Path | File | Trigger | Policy Function | Idempotency | Missing Gates |
|------|------|---------|-----------------|-------------|---------------|
| Queue cold send | `send/queue_worker.py` | Background loop / `POST /api/queue/process` | `send/policy.py:evaluate_policy()` | `sha256(contact_id+seq+draft_id)` unique in send_queue | **Canonical — all 11 gates** |
| Canary send | `send/canary_router.py` | `POST /api/canary/send` | Inline duplicate check only | `sha256(sender+report_recipient)` | Intentionally minimal — not a lead send |
| Conversation direct send | `conversations/router.py` | `POST /api/conversations/{id}/send` | `_engaged_send_block_reasons()` local | `sha256("conversation", contact_id, sent_at, subject, body)` | No `draft_approved` check; no `send_window` check; no deleted-contact check |
| Auto-reply autonomous send | `conversations/auto_reply_service.py` | Reply received in autonomous mode | `_can_auto_reply()` + `_check_hard_stops()` | `sha256("auto_reply", contact_id, reply_id or draft_id)` | No `send_window` check; no `draft_approved`; no deleted-contact check; separate daily cap |
| Agent confirmed send | `agent/tools.py` | `POST /api/agent/confirm` | `_engaged_send_block_reasons()` local | `sha256("agent", action_id, draft_id)` | Same as conversation — no `draft_approved`, no `send_window`, no deleted-contact |

---

## Gate Comparison Matrix

| Gate | Queue | Canary | Conversation | Auto-Reply | Agent |
|------|-------|--------|--------------|------------|-------|
| sender_readiness (canary_verified) | ✅ | ✅ (canary IS the verification step) | ✅ | ✅ | ✅ |
| contact not deleted (`deleted_at IS NULL`) | ✅ | N/A | ❌ MISSING | ❌ MISSING | ❌ MISSING |
| draft approved | ✅ | N/A | ❌ MISSING | ❌ MISSING | ❌ MISSING |
| recipient not suppressed | ✅ | N/A | ✅ | ✅ | ✅ |
| recipient not bounced | ✅ | N/A | ✅ (in block reasons) | ✅ (hard stop) | ✅ |
| recipient not unsubscribed | ✅ | N/A | ✅ | ✅ | ✅ |
| recipient not manually paused | ✅ | N/A | ✅ | ✅ | ✅ |
| daily cap | ✅ (global) | N/A | ✅ (global) | ✅ (separate auto-reply cap) | ✅ (global) |
| hourly cap | ✅ | N/A | ❓ UNVERIFIED | ❌ MISSING | ❓ UNVERIFIED |
| send_delay_s elapsed | ✅ | N/A | ❌ NOT APPLICABLE (engaged reply) | ❌ NOT APPLICABLE | ❌ NOT APPLICABLE |
| send_window (business hours) | ✅ | N/A | ❌ MISSING | ❌ MISSING | ❌ MISSING |
| idempotency (no duplicate send) | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## Proposed Gate Taxonomy

### Hard Gates — apply to EVERY send path (no exceptions)

```python
HARD_GATES = [
    "sender_readiness",        # canary_verified = true
    "contact_not_deleted",     # contact.deleted_at IS NULL
    "recipient_not_suppressed", # email NOT IN suppressions
    "recipient_not_bounced",    # no bounce reply for contact
    "recipient_not_unsubscribed", # no unsubscribe reply
    "idempotency",              # no existing successful send for same idempotency_key
]
```

### Cold-Send-Only Gates — only for queue (initial cold outbound)

```python
COLD_GATES = [
    "canary_verified",          # canary send completed
    "draft_approved",           # draft.approved = true
    "recipient_not_replied",    # no reply received yet (engaged replies bypass this)
    "recipient_not_paused",     # contact.status != manually_paused
    "daily_cap",
    "hourly_cap",
    "send_delay_elapsed",       # send_delay_s since last send
    "send_window",              # within configured hour window
]
```

### Engaged-Reply Gates — conversation, auto-reply, agent

```python
ENGAGED_GATES = [
    # Hard gates apply
    "recipient_not_paused",    # still applies — operator can pause even engaged contacts
    "daily_cap",               # global daily limit still applies
    "send_window",             # SHOULD apply — do not send at 3am even to a replier
    "min_gap_between_replies", # auto-reply specific — minimum time between auto-replies
]
```

---

## Proposed Consolidated Implementation

### New file: `backend/app/send/engaged_policy.py`

```python
"""
Engaged-reply gate evaluation for conversation, auto-reply, and agent direct sends.
Does NOT replace queue policy (send/policy.py).
"""
from dataclasses import dataclass
from typing import Literal

@dataclass
class EngagedGateResult:
    gate: str
    passed: bool
    reason_code: str | None = None

@dataclass 
class EngagedPolicyDecision:
    all_passed: bool
    gates: list[EngagedGateResult]
    block_reason_codes: list[str]

async def evaluate_engaged_send(
    contact,
    db,
    settings,
    sender_readiness: str,
    check_send_window: bool = True,
    min_gap_minutes: int = 0,
) -> EngagedPolicyDecision:
    """
    Run hard gates + engaged-reply-specific gates.
    Called by: conversations/router.py, auto_reply_service.py, agent/tools.py
    """
    gates = []
    
    # 1. Sender readiness
    gates.append(EngagedGateResult(
        gate="sender_readiness",
        passed=sender_readiness in ("smtp_verified", "canary_verified"),
        reason_code=None if sender_readiness in ("smtp_verified", "canary_verified") 
                    else "SENDER_NOT_VERIFIED"
    ))
    
    # 2. Contact not deleted
    gates.append(EngagedGateResult(
        gate="contact_not_deleted",
        passed=contact.deleted_at is None,
        reason_code=None if contact.deleted_at is None else "CONTACT_DELETED"
    ))
    
    # 3. Recipient not suppressed
    suppressed = await db.execute(
        "SELECT 1 FROM suppressions WHERE email=?", (contact.email,))
    gates.append(EngagedGateResult(
        gate="not_suppressed",
        passed=suppressed is None,
        reason_code=None if suppressed is None else "RECIPIENT_SUPPRESSED"
    ))
    
    # 4. Not bounced
    # (similar pattern to policy.py)
    
    # 5. Not unsubscribed
    # (similar pattern)
    
    # 6. Not manually paused
    gates.append(EngagedGateResult(
        gate="not_paused",
        passed=contact.status != "manually_paused",
        reason_code=None if contact.status != "manually_paused" else "RECIPIENT_MANUALLY_PAUSED"
    ))
    
    # 7. Daily cap (global)
    # (reuse same counting logic from policy.py)
    
    # 8. Send window
    if check_send_window:
        in_window = await _check_send_window(settings)
        gates.append(EngagedGateResult(
            gate="send_window",
            passed=in_window,
            reason_code=None if in_window else "SEND_WINDOW_CLOSED"
        ))
    
    # 9. Min gap between replies (auto-reply specific)
    if min_gap_minutes > 0:
        last_send = await _get_last_send_to_contact(contact.id, db)
        gap_ok = last_send is None or (utcnow() - last_send).total_seconds() >= min_gap_minutes * 60
        gates.append(EngagedGateResult(
            gate="min_gap",
            passed=gap_ok,
            reason_code=None if gap_ok else "MIN_GAP_NOT_ELAPSED"
        ))
    
    block_codes = [g.reason_code for g in gates if not g.passed and g.reason_code]
    return EngagedPolicyDecision(
        all_passed=all(g.passed for g in gates),
        gates=gates,
        block_reason_codes=block_codes
    )
```

### Callers to update

1. `conversations/router.py` — replace `_engaged_send_block_reasons()` with `evaluate_engaged_send()`.
2. `conversations/auto_reply_service.py` — replace inline safety checks with `evaluate_engaged_send(check_send_window=True, min_gap_minutes=settings.auto_reply_min_gap)`.
3. `agent/tools.py` — replace duplicate `_engaged_send_block_reasons()` with `evaluate_engaged_send()`.

---

## Security Impact of Current Divergence

If a contact is:
- Soft-deleted but their `contact_id` is known to the agent
- OR soft-deleted but they have a recent reply in the DB

Then:
- Queue cold send: BLOCKED (deleted_at check)
- Conversation send: NOT BLOCKED (deleted_at not checked)
- Auto-reply: NOT BLOCKED
- Agent send: NOT BLOCKED

This means a deleted contact CAN receive emails via non-queue paths.
This is a P1 safety issue.

---

## Audit Coverage After Unification

All three paths should call `audit_service.emit_event()` with the same event types:
- `send.attempt` before SMTP
- `send.success` or `send.failed` after SMTP
- `queue.gate_blocked` equivalent for engaged sends (new event type: `send.engaged_blocked`)
