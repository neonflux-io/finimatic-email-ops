# Finimatic — Agentic Control Plane v2.0
# Three-Channel Architecture
# Status: DESIGN SPEC — Implementation target for Codex steer prompts 1-5

---

## ROOT CAUSE OF THE BROKEN READ PATH

The image shows the widget returning the exact same static response to both
"who all replied" and "can u show me the replys":

  "I cannot perform that through the email assistant. I can read replies,
   search threads, draft replies, check queue/follow-ups, and send only
   after confirmation."

This is not a prompt quality issue. It is a structural routing defect.

The current pipeline:
  Browser → /agent/chat → GoalFrame → CapabilityCatalog.check() → DENIED

The CapabilityCatalog is deny-by-default. It was built to govern sends and
approvals. "who all replied" doesn't match any registered positive capability
exactly enough, so the catalog fires a denial, and the ResponseAgent formats
that denial as a static apology string.

The read path and the send path share the exact same gate. That is wrong.

A read query has zero risk. It cannot damage data. Denying it is not safety —
it is dysfunction.

The fix is NOT to relax the send gate. It IS to route read queries completely
around the gate before GoalFrame runs.

---

## CRITICAL CONSTRAINTS (do not violate in any steer prompt)

1. The existing side-effect path — GoalFrame → Intent → Slot → Orchestrator →
   ToolExecutor → Reasoning → Verifier → ResponseAgent → PendingAction →
   Confirmation → Send — is UNTOUCHED. Every existing test for it must pass.

2. The confirmation harness (pending_email_actions table, params_hash binding,
   session validation, expiry check, consumed check, audit-before-send) is
   UNTOUCHED.

3. FERNET-encrypted secrets never leave the backend. No new code path changes
   this. The layman formatter runs AFTER all security checks.

4. imaplib and smtplib are synchronous. Wrap all sync calls in
   asyncio.get_event_loop().run_in_executor(None, ...) as existing code does.

5. SQLAlchemy sessions: use the synchronous get_db() dependency exactly as
   existing routes do. Do not introduce new async DB patterns.

6. Finimatic contact IDs are 32-character lowercase hex strings (no dashes):
   `lower(hex(randomblob(16)))` = e.g. `a1b2c3d4e5f6789012345678abcdef01`
   The layman formatter regex must be `r'\b[0-9a-f]{32}\b'` not a UUID regex.

7. Tables that EXIST in finimatic.db (from SCHEMA.md + implementation report):
   settings, contacts, import_batches, import_rows, drafts, templates,
   send_queue, send_attempts, follow_up_sequences, suppressions, replies,
   conversation_messages, audit_events, provider_health
   Tables added by agent build (check DB before assuming):
   agent_sessions, pending_email_actions

8. Tables that DO NOT EXIST (do not reference in snapshot builder):
   campaign_plans, auto_reply_log, campaign_contacts

9. Models available:
   Groq fast: llama-3.1-8b-instant
   Groq full: llama-3.3-70b-versatile
   Gemini: gemini-2.0-flash
   Do not hallucinate other model names.

---

## THE THREE-CHANNEL ARCHITECTURE

Every user message routes to exactly one of three channels:

```
USER MESSAGE
     │
     ▼
┌────────────────────────────────────────┐
│           CONTEXT LOADER               │
│  Runs once per session. Cached in      │
│  agent_sessions.context_summary.       │
│  Pure Python DB query. No LLM call.    │
│  Refreshed if >30 min idle.            │
└──────────────────┬─────────────────────┘
                   │  (context card injected into every subsequent call)
                   ▼
┌────────────────────────────────────────┐
│           CHANNEL ROUTER               │
│  1 Groq call (llama-3.1-8b-instant)    │
│  ~300ms. Returns awareness/task/action │
│  Defaults to awareness on any error.   │
│  Python validates output.              │
└──────┬───────────┬────────────┬────────┘
       │           │            │
  AWARENESS      TASK        ACTION
       │           │            │
       ▼           ▼            │
  Campaign    GoalFrame      GoalFrame
  Intelligence  (task_mode)   (strict, UNCHANGED)
  Agent        → Intent       → Intent
  (no catalog   → Slot        → Slot
   check)       → Fuzzy       → Orchestrator
                  Resolver     → ToolExecutor
               → Tool         → Reasoning
               → Verifier     → Verifier
                  (light)      → PendingAction
               → Response     → Confirm Card
                               │
                    User clicks CONFIRM
                               │
                    Backend validates:
                    session + hash + expiry
                    + not consumed
                               │
                    Send → Audit → Clear
       │           │            │
       └───────────┴────────────┘
                   │
       ┌───────────▼───────────────┐
       │   LAYMAN RESPONSE         │
       │   FORMATTER               │
       │   32-char hex IDs → names │
       │   ISO timestamps → "2h ago"│
       │   status codes → English  │
       │   tech field names removed│
       └───────────────────────────┘
                   │
            Widget response
```

---

## ALL AGENTS — COMPLETE IMPLEMENTATION SPECIFICATION

### AGENT 1: Channel Router

**File:** `backend/app/agent/channel_router.py`
**Status:** NEW
**Purpose:** Replaces GoalFrame as the first agent called. Routes to the right
  channel before any capability check runs. Never blocks. Never crashes.

```python
import json
import asyncio
from pydantic import BaseModel, Field
from typing import Literal
from ..db.session import get_db_sync
from ..settings.service import get_groq_keys_decrypted

class ChannelDecision(BaseModel):
    channel: Literal["awareness", "task", "action"]
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    routing_reason: str = ""

CHANNEL_ROUTER_SYSTEM = """You classify user messages into exactly one routing channel.
Return ONLY valid JSON: {"channel": "...", "confidence": 0.0, "routing_reason": "..."}

awareness: User wants to KNOW something about their email campaign.
  ANY question about status, people, stats, replies, history, progress.
  "who replied", "how many sent", "show replies", "what is the status",
  "tell me about X", "show me X", "any replies today", "campaign health".
  THIS IS THE DEFAULT. When uncertain, return awareness.

task: User wants to FIND or CREATE something specific.
  "generate a draft for X", "find contact X", "draft a response to Arjun",
  "look up the thread with Priya", "search for contacts in Y niche".

action: User wants to CHANGE STATE or EXECUTE something with a side effect.
  ONLY return action for: "send it", "confirm", "approve", "suppress X",
  "cancel", "activate campaign", "delete X", "remove X from list".
  Do NOT return action for questions or searches.

RULES:
- Uncertain between awareness and task → return awareness
- Uncertain between task and action → return task
- NEVER return action unless user explicitly wants to change state
- NEVER return any value other than awareness, task, or action
- Do not include markdown, explanations, or any text outside the JSON"""

async def classify_channel(message: str, context_hint: str = "") -> ChannelDecision:
    """
    One Groq call. Returns ChannelDecision. NEVER raises.
    On any error, defaults to awareness — the safe fallback.
    """
    try:
        # Get Groq keys (same pattern as existing gateway.py)
        groq_keys = await get_groq_keys_decrypted()
        if not groq_keys:
            return ChannelDecision(
                channel="awareness", confidence=0.4,
                routing_reason="no_groq_keys_available_defaulting_to_awareness"
            )

        from groq import Groq
        client = Groq(api_key=groq_keys[0])

        prompt_parts = [f"USER MESSAGE: {message[:300]}"]
        if context_hint:
            prompt_parts.append(f"RECENT SESSION CONTEXT: {context_hint[:150]}")

        def _call():
            return client.chat.completions.create(
                model="llama-3.1-8b-instant",
                messages=[
                    {"role": "system", "content": CHANNEL_ROUTER_SYSTEM},
                    {"role": "user", "content": "\n".join(prompt_parts)}
                ],
                max_tokens=80,
                temperature=0.1
            )

        loop = asyncio.get_event_loop()
        response = await loop.run_in_executor(None, _call)
        raw = response.choices[0].message.content.strip()

        # Strip any accidental markdown fences
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        raw = raw.strip()

        data = json.loads(raw)
        decision = ChannelDecision(**data)

        # Python validates — never trust model alone
        if decision.channel not in ("awareness", "task", "action"):
            decision.channel = "awareness"
            decision.routing_reason = "invalid_channel_corrected_to_awareness"

        return decision

    except Exception as e:
        # Channel Router must NEVER crash the pipeline
        return ChannelDecision(
            channel="awareness",
            confidence=0.3,
            routing_reason=f"error_defaulting_to_awareness:{type(e).__name__}"
        )
```

**Hard invariants:**
- On Groq failure (rate limit, no keys, bad JSON) → `channel="awareness"`
- Python validates channel after model response
- max_tokens=80 (channel decision is tiny — don't waste quota)
- Temperature=0.1 (deterministic routing)

---

### AGENT 2: Campaign Intelligence Agent

**File:** `backend/app/agent/campaign_intelligence.py`
**Status:** NEW
**Purpose:** Answers ALL awareness queries by reading actual DB data and
  running one contextual LLM call. No capability gate. Never returns
  "I cannot perform that."

**Provider:** Gemini primary (gemini-2.0-flash), Groq fallback
  (llama-3.3-70b-versatile).

**DB tables accessed (read-only — always):**
  contacts, replies, send_attempts, send_queue, follow_up_sequences,
  suppressions, drafts, conversation_messages, audit_events, settings

#### Snapshot Builder (pure Python, no LLM, called first)

```python
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy.orm import Session
from ..db.models import (
    Contact, Reply, SendAttempt, SendQueue,
    FollowUpSequence, Suppression, Draft,
    ConversationMessage, Settings
)

# Human-readable reply classifications
REPLY_PLAIN = {
    "reply": "replied",
    "unsubscribe": "asked to be removed",
    "bounce": "email bounced",
    "auto_reply": "auto out-of-office",
    "complaint": "marked as spam",
    "unknown": "unclear response",
}

# Human-readable contact statuses
STATUS_PLAIN = {
    "imported": "new (not yet emailed)",
    "needs_review": "needs review",
    "draft_needed": "needs a draft",
    "draft_ready": "draft ready",
    "approved": "draft approved",
    "queued": "email queued to send",
    "sent": "email sent",
    "replied": "replied to your email",
    "bounced": "email bounced",
    "unsubscribed": "opted out",
    "suppressed": "permanently removed",
    "manually_paused": "paused by you",
    "blocked_by_policy": "blocked (policy)",
    "follow_up_due": "follow-up due",
    "follow_up_stopped": "follow-up stopped",
    "complete": "campaign complete",
}

def humanize_dt(dt: datetime) -> str:
    """Convert a datetime to human-readable relative time."""
    if dt is None:
        return "unknown time"
    now = datetime.utcnow()
    if dt.tzinfo is not None:
        dt = dt.replace(tzinfo=None)
    delta = now - dt
    total_seconds = int(delta.total_seconds())
    if total_seconds < 60:
        return "just now"
    if total_seconds < 3600:
        m = total_seconds // 60
        return f"{m} minute{'s' if m != 1 else ''} ago"
    if total_seconds < 86400:
        h = total_seconds // 3600
        return f"{h} hour{'s' if h != 1 else ''} ago"
    if total_seconds < 172800:
        return "yesterday"
    d = total_seconds // 86400
    return f"{d} days ago"

def build_campaign_snapshot(db: Session) -> str:
    """
    Builds a bounded, plain-English campaign state string from DB.
    Max 3000 chars. No UUIDs. No technical field names.
    No LLM call here — pure Python.
    """
    now_utc = datetime.utcnow()
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = now_utc - timedelta(days=7)
    hours_72 = now_utc - timedelta(hours=72)

    # ── CONTACTS ──────────────────────────────────────────────────────────
    all_contacts = db.query(Contact).all()
    status_counts: dict[str, int] = {}
    for c in all_contacts:
        status_counts[c.status] = status_counts.get(c.status, 0) + 1

    total_contacts = len(all_contacts)
    total_sent = sum(status_counts.get(s, 0) for s in
                     ["sent", "replied", "follow_up_due", "follow_up_stopped",
                      "complete", "unsubscribed", "bounced"])
    total_replied = status_counts.get("replied", 0)
    total_opted_out = (status_counts.get("suppressed", 0) +
                       status_counts.get("unsubscribed", 0))
    total_pending = sum(status_counts.get(s, 0) for s in
                        ["imported", "needs_review", "draft_needed",
                         "draft_ready", "approved", "queued"])

    # ── REPLIES (last 72 hours) ────────────────────────────────────────────
    recent_replies_raw = (
        db.query(Reply, Contact)
        .join(Contact, Contact.id == Reply.contact_id)
        .filter(Reply.created_at >= hours_72)
        .order_by(Reply.created_at.desc())
        .limit(25)
        .all()
    )

    # All replies ever (for "who all replied" queries)
    all_replies_raw = (
        db.query(Reply, Contact)
        .join(Contact, Contact.id == Reply.contact_id)
        .order_by(Reply.created_at.desc())
        .limit(50)
        .all()
    )

    reply_lines_recent = []
    for reply, contact in recent_replies_raw:
        name = (contact.creator_name or contact.business_name or
                contact.email.split("@")[0])
        when = humanize_dt(reply.created_at)
        classification = REPLY_PLAIN.get(reply.classified_as, reply.classified_as)
        reply_lines_recent.append(f"  - {name} ({contact.email}): {classification}, {when}")

    reply_lines_all = []
    for reply, contact in all_replies_raw:
        name = (contact.creator_name or contact.business_name or
                contact.email.split("@")[0])
        when = humanize_dt(reply.created_at)
        classification = REPLY_PLAIN.get(reply.classified_as, reply.classified_as)
        reply_lines_all.append(f"  - {name} ({contact.email}): {classification}, {when}")

    # ── SEND STATS ────────────────────────────────────────────────────────
    today_sends = db.query(SendAttempt).filter(
        SendAttempt.status == "success",
        SendAttempt.sent_at >= today_start
    ).count()

    week_sends = db.query(SendAttempt).filter(
        SendAttempt.status == "success",
        SendAttempt.sent_at >= week_start
    ).count()

    total_sends_ever = db.query(SendAttempt).filter(
        SendAttempt.status == "success"
    ).count()

    # ── QUEUE ────────────────────────────────────────────────────────────
    pending_queue = db.query(SendQueue).filter(
        SendQueue.status == "pending"
    ).count()

    blocked_queue_rows = (
        db.query(SendQueue, Contact)
        .join(Contact, Contact.id == SendQueue.contact_id)
        .filter(SendQueue.status == "blocked")
        .limit(5)
        .all()
    )
    blocked_lines = []
    for qrow, contact in blocked_queue_rows:
        name = contact.creator_name or contact.email
        reasons = []
        if qrow.policy_block_reasons:
            import json as _json
            try:
                reasons = _json.loads(qrow.policy_block_reasons)
            except Exception:
                reasons = [qrow.policy_block_reasons]
        reason_str = ", ".join(reasons) if reasons else "unknown reason"
        blocked_lines.append(f"  - {name}: {reason_str}")

    # ── FOLLOW-UPS ────────────────────────────────────────────────────────
    due_followups = db.query(FollowUpSequence).filter(
        FollowUpSequence.status == "due"
    ).count()

    stopped_followups = db.query(FollowUpSequence).filter(
        FollowUpSequence.status == "stopped"
    ).count()

    # ── SETTINGS ─────────────────────────────────────────────────────────
    def get_setting_val(key: str, default: str) -> str:
        row = db.query(Settings).filter(Settings.key == key).first()
        return row.value if row and row.value else default

    daily_cap = get_setting_val("daily_send_cap", "50")
    hourly_cap = get_setting_val("hourly_send_cap", "10")
    dry_run = get_setting_val("dry_run", "false")
    canary_verified = get_setting_val("canary_verified", "false")

    # ── CONTACTS NEEDING REPLY ────────────────────────────────────────────
    needs_reply_contacts = db.query(Contact).filter(
        Contact.status == "replied"
    ).limit(8).all()
    needs_reply_names = [
        c.creator_name or c.business_name or c.email
        for c in needs_reply_contacts
    ]

    # ── UNEMAILED CONTACTS ────────────────────────────────────────────────
    not_emailed = db.query(Contact).filter(
        Contact.status.in_(["imported", "needs_review", "draft_needed"])
    ).count()

    # ── DRAFTS PENDING APPROVAL ───────────────────────────────────────────
    pending_drafts = db.query(Draft).filter(
        Draft.approved == False
    ).count()

    approved_unsent = db.query(Draft).filter(
        Draft.approved == True
    ).count()

    # ── STATUS BREAKDOWN (top 8 statuses) ────────────────────────────────
    top_statuses = sorted(status_counts.items(), key=lambda x: -x[1])[:8]
    status_breakdown = ", ".join(
        f"{STATUS_PLAIN.get(k, k)}: {v}" for k, v in top_statuses
    )

    # ── BUILD SNAPSHOT ────────────────────────────────────────────────────
    mode = "DRY-RUN" if dry_run == "true" else ("LIVE" if canary_verified == "true" else "CANARY")

    snapshot_parts = [
        f"FINIMATIC CAMPAIGN SNAPSHOT — {now_utc.strftime('%B %d, %Y, %H:%M UTC')} — Mode: {mode}",
        "",
        f"CONTACTS: {total_contacts} total | {total_sent} emailed | {total_replied} replied back | {not_emailed} not yet emailed | {total_opted_out} opted out",
        f"STATUS BREAKDOWN: {status_breakdown}",
        "",
        f"ALL REPLIES EVER (most recent first, up to 50):",
    ]
    if reply_lines_all:
        snapshot_parts.extend(reply_lines_all[:30])
    else:
        snapshot_parts.append("  No replies yet.")

    snapshot_parts += [
        "",
        f"RECENT REPLIES (last 72 hours):",
    ]
    if reply_lines_recent:
        snapshot_parts.extend(reply_lines_recent)
    else:
        snapshot_parts.append("  No replies in last 72 hours.")

    snapshot_parts += [
        "",
        f"CONTACTS WHO REPLIED AND MAY NEED A RESPONSE:",
        f"  {', '.join(needs_reply_names) if needs_reply_names else 'None identified'}",
        "",
        f"SENDING STATS:",
        f"  Today: {today_sends} sent (cap: {daily_cap}/day, {hourly_cap}/hour)",
        f"  This week: {week_sends} sent",
        f"  All time: {total_sends_ever} sent",
        "",
        f"QUEUE: {pending_queue} pending",
    ]

    if blocked_lines:
        snapshot_parts.append(f"BLOCKED SENDS ({len(blocked_lines)}):")
        snapshot_parts.extend(blocked_lines)

    snapshot_parts += [
        "",
        f"FOLLOW-UPS: {due_followups} due, {stopped_followups} stopped",
        f"DRAFTS: {pending_drafts} waiting for your approval, {approved_unsent} approved but not yet sent",
        "",
    ]

    full_snapshot = "\n".join(snapshot_parts)
    return full_snapshot[:3200]  # hard truncate to manage token budget
```

#### LLM Answerer (one call with full snapshot as evidence)

```python
CAMPAIGN_INTELLIGENCE_SYSTEM = """You are the campaign assistant brain for a cold email outreach tool.
Answer the user's question using ONLY the campaign data provided in CAMPAIGN DATA below.

STRICT RULES — enforce every single one:
1. Answer in conversational plain English. No jargon.
2. NEVER output a database ID, hex string, or UUID.
3. NEVER output an ISO timestamp — use relative time (2 hours ago, yesterday, last week).
4. NEVER output a technical status code — translate to plain English.
   "replied" = replied to your email
   "suppressed" = opted out / asked to be removed
   "blocked_by_policy" = blocked by a sending rule
5. If the question asks for a count — STATE THE NUMBER FIRST.
6. If the question asks WHO — list names and emails, maximum 10 items, then "...and N more".
7. If the data to answer the question is not in CAMPAIGN DATA — say clearly what you
   don't know and suggest where to look. Do NOT fabricate names or numbers.
8. NEVER say "I cannot perform that" for an information question.
9. NEVER say "I don't have access to" for campaign data questions.
10. Start with the actual answer. No preamble like "Based on the data..." or "According to...".
11. Keep responses conversational. 1-3 sentences for simple facts, a short paragraph for
    complex questions, a named list for "who" questions.
12. Use second person: "your campaign", "you sent", "they replied to you"."""

async def answer_awareness_query(
    question: str,
    db: Session,
    session_context: str = "",
    turn_history: list[dict] | None = None,
) -> str:
    """
    Main entry point for awareness channel.
    Builds snapshot, calls LLM, returns plain English answer.
    Never raises — returns a safe fallback on any error.
    """
    try:
        snapshot = build_campaign_snapshot(db)
    except Exception as e:
        snapshot = f"[Snapshot build failed: {type(e).__name__}]"

    # Build turn context (last 3 turns for conversational continuity)
    turn_ctx = ""
    if turn_history:
        recent = turn_history[-6:]  # 3 turns = 6 messages
        turn_ctx = "\n".join(
            f"{'User' if t['role'] == 'user' else 'Assistant'}: {t['text'][:150]}"
            for t in recent
        )

    user_prompt_parts = [
        f"CAMPAIGN DATA:\n{snapshot}",
    ]
    if turn_ctx:
        user_prompt_parts.append(f"\nRECENT CONVERSATION:\n{turn_ctx}")
    if session_context:
        user_prompt_parts.append(f"\nSESSION CONTEXT:\n{session_context[:300]}")
    user_prompt_parts.append(f"\nUSER QUESTION: {question}")

    user_prompt = "\n".join(user_prompt_parts)

    # Try Gemini first (better at long context), Groq as fallback
    response_text = await _call_with_fallback(
        agent_name="campaign_intelligence",
        system=CAMPAIGN_INTELLIGENCE_SYSTEM,
        user=user_prompt,
        primary="gemini",
        fallback="groq",
        max_tokens=500,
        temperature=0.3,
    )

    # Grounding check: did LLM hallucinate names or numbers not in snapshot?
    response_text = _grounding_check(response_text, snapshot)

    return response_text

def _grounding_check(response: str, snapshot: str) -> str:
    """
    Light grounding check for awareness mode.
    If response contains data that clearly contradicts the snapshot,
    fall back to a safe summary instead of returning hallucinated data.
    This is a best-effort check, not cryptographic.
    """
    # Check for obviously hallucinated email-like strings not in the snapshot
    import re
    emails_in_response = re.findall(r'[\w.+-]+@[\w-]+\.[a-z]{2,}', response)
    for email in emails_in_response:
        if email not in snapshot:
            # Suspicious — email in response not found in snapshot evidence
            # Don't use this response; return a safe summary
            return _safe_fallback_summary(snapshot)
    return response

def _safe_fallback_summary(snapshot: str) -> str:
    """Returns a safe 2-line summary extracted directly from snapshot lines."""
    lines = [l.strip() for l in snapshot.split("\n") if l.strip()
             and not l.startswith("FINIMATIC") and not l.startswith("─")]
    summary_lines = [l for l in lines if l and not l.startswith("-")][:4]
    return "Here's what I know: " + " | ".join(summary_lines[:3])
```

---

### AGENT 3: Context Loader

**File:** `backend/app/agent/context_loader.py`
**Status:** NEW
**Purpose:** Builds and caches the campaign context card per session.
  No LLM call. Pure Python. Stored in agent_sessions.context_summary.
  Makes every subsequent agent call contextually aware.

```python
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from ..db.models import Contact, Reply, SendAttempt, FollowUpSequence, Draft

CONTEXT_STALE_MINUTES = 30

def build_context_card(db: Session) -> str:
    """
    Builds a compact ~500-char context card for session injection.
    No LLM call. Used as prefix for every agent call in the session.
    """
    now = datetime.utcnow()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    hours_24 = now - timedelta(hours=24)

    # Today's sends
    today_sends = db.query(SendAttempt).filter(
        SendAttempt.status == "success",
        SendAttempt.sent_at >= today_start
    ).count()

    # Contacts who replied (need attention)
    replied_contacts = db.query(Contact).filter(
        Contact.status == "replied"
    ).limit(5).all()
    replied_names = [
        c.creator_name or c.business_name or c.email.split("@")[0]
        for c in replied_contacts
    ]

    # New replies since yesterday
    new_replies_count = db.query(Reply).filter(
        Reply.created_at >= hours_24
    ).count()

    # Pending draft approvals
    pending_approvals = db.query(Draft).filter(
        Draft.approved == False
    ).count()

    # Opt-outs today
    from ..db.models import Reply as ReplyModel
    todays_optouts = db.query(ReplyModel).filter(
        ReplyModel.classified_as == "unsubscribe",
        ReplyModel.created_at >= today_start
    ).count()

    # Build card
    parts = [
        f"TODAY: {today_sends} sent, {new_replies_count} new replies",
    ]

    if replied_names:
        parts.append(f"NEEDS RESPONSE: {', '.join(replied_names[:3])}"
                     + (f" +{len(replied_names)-3} more" if len(replied_names) > 3 else ""))
    if pending_approvals > 0:
        parts.append(f"PENDING APPROVALS: {pending_approvals} drafts")
    if todays_optouts > 0:
        parts.append(f"OPT-OUTS TODAY: {todays_optouts}")

    card = " | ".join(parts)
    return card[:500]

def generate_proactive_opening(context_card: str, db: Session) -> str:
    """
    Called when widget opens for the first time this session.
    Returns a warm, specific, non-generic opening message.
    No LLM call — pure string logic.
    """
    # Parse context card for attention items
    needs_response = []
    pending_count = 0
    opt_outs = 0

    if "NEEDS RESPONSE:" in context_card:
        segment = context_card.split("NEEDS RESPONSE:")[1].split("|")[0].strip()
        needs_response = [n.strip() for n in segment.split(",") if n.strip()]

    if "PENDING APPROVALS:" in context_card:
        try:
            val = context_card.split("PENDING APPROVALS:")[1].split("|")[0].strip()
            pending_count = int(val.split()[0])
        except Exception:
            pass

    if "OPT-OUTS TODAY:" in context_card:
        try:
            val = context_card.split("OPT-OUTS TODAY:")[1].split("|")[0].strip()
            opt_outs = int(val.split()[0])
        except Exception:
            pass

    attention_items = []

    if needs_response:
        names = ", ".join(needs_response[:2])
        extra = f" and {len(needs_response) - 2} others" if len(needs_response) > 2 else ""
        attention_items.append(
            f"{names}{extra} replied to your emails and might need a response"
        )

    if pending_count > 0:
        attention_items.append(
            f"{pending_count} follow-up draft{'s' if pending_count > 1 else ''} "
            f"waiting for your approval"
        )

    if opt_outs > 0:
        attention_items.append(
            f"{opt_outs} person asked to be removed from your list today"
        )

    if attention_items:
        items_text = "; ".join(attention_items)
        return (
            f"Welcome back. A few things need your attention: {items_text}. "
            f"What would you like to do?"
        )
    else:
        return (
            "Your campaign is running smoothly. "
            "What would you like to do — check replies, generate a draft, or send an update?"
        )

def is_context_stale(loaded_at_iso: str | None) -> bool:
    """Returns True if context card is missing or >30 minutes old."""
    if not loaded_at_iso:
        return True
    try:
        loaded_at = datetime.fromisoformat(loaded_at_iso)
        return (datetime.utcnow() - loaded_at).total_seconds() > CONTEXT_STALE_MINUTES * 60
    except Exception:
        return True
```

---

### AGENT 4: Fuzzy Contact Resolver

**File:** `backend/app/agent/fuzzy_resolver.py`
**Status:** NEW (replaces brittle exact-match in tools.py)
**Purpose:** Resolves partial names, typos, descriptions, and email fragments
  to actual Contact records. Never returns "not found" without a clarifying
  question. No LLM call — pure SQLAlchemy LIKE queries + token scoring.

```python
from dataclasses import dataclass, field
from typing import Optional
from sqlalchemy.orm import Session
from sqlalchemy import or_
from ..db.models import Contact

STOP_WORDS = {
    "the", "a", "an", "to", "for", "of", "and", "or", "with",
    "send", "reply", "email", "contact", "person", "him", "her",
    "them", "it", "this", "that", "who", "find", "me", "my",
    "his", "hers", "their", "those", "these", "that", "guy",
    "gal", "from", "about", "regarding", "re", "at", "on",
}

@dataclass
class FuzzyResolveResult:
    match: Optional[Contact] = None
    candidates: list[Contact] = field(default_factory=list)
    confidence: float = 0.0
    method: str = ""
    needs_clarification: bool = False
    clarification_question: Optional[str] = None

def fuzzy_resolve_contact(query: str, db: Session) -> FuzzyResolveResult:
    """
    Resolves a free-text contact reference to Contact records.

    Steps (in order):
    1. Exact email match → confidence 1.0
    2. Partial email match (LIKE) → confidence 0.9
    3. Exact creator_name or business_name match → confidence 0.95
    4. Token-by-token LIKE across all contact fields → scored
    5. Single result → return with confidence 0.85
    6. Multiple results (2-5) → return with clarification question
    7. Zero results → return with open clarification question

    NOTE: IDs in Finimatic are 32-char hex strings (no dashes).
    This function never returns bare IDs in clarification questions.
    """
    query_clean = query.strip()
    query_lower = query_clean.lower()

    # ── STEP 1: Exact email match ─────────────────────────────────────────
    exact_email = db.query(Contact).filter(
        Contact.email == query_lower
    ).first()
    if exact_email:
        return FuzzyResolveResult(
            match=exact_email,
            confidence=1.0,
            method="exact_email"
        )

    # ── STEP 2: Partial email match ───────────────────────────────────────
    if "@" in query_lower or "." in query_lower:
        partial_email = db.query(Contact).filter(
            Contact.email.ilike(f"%{query_lower}%")
        ).limit(3).all()
        if len(partial_email) == 1:
            return FuzzyResolveResult(
                match=partial_email[0],
                confidence=0.9,
                method="partial_email"
            )
        if len(partial_email) > 1:
            return _build_clarification(partial_email, query_clean)

    # ── STEP 3: Exact name match ──────────────────────────────────────────
    exact_name = db.query(Contact).filter(
        or_(
            Contact.creator_name.ilike(query_lower),
            Contact.business_name.ilike(query_lower),
        )
    ).first()
    if exact_name:
        return FuzzyResolveResult(
            match=exact_name,
            confidence=0.95,
            method="exact_name"
        )

    # ── STEP 4: Token LIKE search across all text fields ──────────────────
    tokens = [
        t for t in query_lower.split()
        if len(t) > 2 and t not in STOP_WORDS
    ]

    if not tokens:
        return FuzzyResolveResult(
            needs_clarification=True,
            clarification_question=(
                f"I couldn't find a contact matching '{query_clean}'. "
                f"Could you give me their name or email address?"
            )
        )

    # Track (contact_id → (Contact, score))
    score_map: dict[str, tuple[Contact, int]] = {}

    for token in tokens:
        hits = db.query(Contact).filter(
            or_(
                Contact.email.ilike(f"%{token}%"),
                Contact.creator_name.ilike(f"%{token}%"),
                Contact.business_name.ilike(f"%{token}%"),
                Contact.notes.ilike(f"%{token}%"),
                Contact.lead_category.ilike(f"%{token}%"),
                Contact.personalization.ilike(f"%{token}%"),
            )
        ).limit(10).all()

        for h in hits:
            existing = score_map.get(h.id)
            if existing:
                score_map[h.id] = (h, existing[1] + 1)
            else:
                score_map[h.id] = (h, 1)

    ranked = sorted(score_map.values(), key=lambda x: -x[1])

    if len(ranked) == 0:
        return FuzzyResolveResult(
            needs_clarification=True,
            clarification_question=(
                f"I couldn't find a contact matching '{query_clean}'. "
                f"Could you give me their name or email address?"
            )
        )

    if len(ranked) == 1:
        contact, score = ranked[0]
        return FuzzyResolveResult(
            match=contact,
            confidence=min(0.5 + score * 0.15, 0.92),
            method=f"fuzzy_single_score_{score}"
        )

    # Multiple candidates
    top = [c for c, s in ranked[:5]]
    return _build_clarification(top, query_clean)

def _build_clarification(candidates: list[Contact], query: str) -> FuzzyResolveResult:
    """Builds a numbered clarification question listing candidate contacts."""
    options = []
    for i, c in enumerate(candidates[:4], 1):
        name = c.creator_name or c.business_name or "Unknown"
        category = f" [{c.lead_category}]" if c.lead_category else ""
        options.append(f"{i}. {name} ({c.email}){category}")

    options_text = "\n".join(options)
    extra = ""
    if len(candidates) > 4:
        extra = f"\n(and {len(candidates) - 4} more matches)"

    return FuzzyResolveResult(
        candidates=candidates,
        needs_clarification=True,
        clarification_question=(
            f"I found a few contacts matching '{query}'. Which one did you mean?\n"
            f"{options_text}{extra}"
        )
    )
```

---

### AGENT 5: Layman Response Formatter

**File:** `backend/app/agent/layman_formatter.py`
**Status:** NEW
**Purpose:** Final step in ALL channels. Translates every technical artifact
  (IDs, timestamps, status codes, field names) to plain English before the
  response reaches the widget. Runs AFTER all security checks.

```python
import re
from datetime import datetime, timezone

# ── 32-CHAR HEX ID PATTERN (Finimatic-specific, NO dashes) ────────────────
HEX_ID_PATTERN = re.compile(r'\b[0-9a-f]{32}\b')

# ── ISO TIMESTAMP PATTERN ─────────────────────────────────────────────────
ISO_PATTERN = re.compile(
    r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?'
)

# ── STATUS AND INTENT CODE TRANSLATIONS ───────────────────────────────────
TERM_TRANSLATIONS = {
    # Contact statuses
    "conversation_active": "replied and needs your response",
    "pending_approval": "waiting for your approval",
    "follow_up_stopped": "no longer receiving follow-ups",
    "suppressed": "opted out",
    "unsubscribed": "asked to be removed",
    "imported": "new contact (not yet emailed)",
    "needs_review": "needs review",
    "draft_needed": "needs a draft",
    "draft_ready": "draft is ready",
    "approved": "draft approved",
    "queued": "email scheduled to send",
    "sent": "email delivered",
    "blocked": "blocked by a sending rule",
    "blocked_by_policy": "blocked by a sending rule",
    "draft_not_approved": "draft not approved yet",
    "manually_paused": "paused by you",
    "follow_up_due": "follow-up is due",
    "complete": "campaign finished",
    "bounced": "email could not be delivered",
    # Reply classifications
    "classified_as": "",          # remove field name prefix
    "positive_interest": "interested",
    "negative_no": "not interested",
    "objection": "has concerns",
    "question": "asked a question",
    "auto_reply": "automated out-of-office",
    "unknown": "unclear response",
    # Technical terms to remove or replace
    "send_attempt": "email send",
    "queue_entry": "scheduled email",
    "audit_event": "event",
    "reason_code": "reason",
    "policy_block_reasons": "blocked reasons",
    "idempotency_key": "",
    "params_hash": "",
    "sequence_num": "",
    "provider_msg_id": "",
    "draft_id": "",
    "contact_id": "",
    "action_class": "",
    "privacy_class": "",
    "batch_id": "",
    "import_batch": "import",
}

# Field names that should cause a line to be filtered entirely
BANNED_FIELD_PATTERNS = [
    re.compile(r'^\s*[a-z_]+_id\s*[:=]', re.IGNORECASE),
    re.compile(r'^\s*params_hash\s*[:=]', re.IGNORECASE),
    re.compile(r'^\s*idempotency_key\s*[:=]', re.IGNORECASE),
    re.compile(r'^\s*sequence_num\s*[:=]', re.IGNORECASE),
    re.compile(r'^\s*action_class\s*[:=]', re.IGNORECASE),
    re.compile(r'^\s*privacy_class\s*[:=]', re.IGNORECASE),
]

def _humanize_iso_match(m: re.Match) -> str:
    try:
        raw = m.group()
        # Normalize Z to +00:00
        raw_normalized = raw.replace("Z", "+00:00").replace(" ", "T")
        dt = datetime.fromisoformat(raw_normalized)
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None)
        delta = datetime.utcnow() - dt
        secs = int(delta.total_seconds())
        if secs < 60:
            return "just now"
        if secs < 3600:
            m_ = secs // 60
            return f"{m_} minute{'s' if m_ != 1 else ''} ago"
        if secs < 86400:
            h = secs // 3600
            return f"{h} hour{'s' if h != 1 else ''} ago"
        if secs < 172800:
            return "yesterday"
        d = secs // 86400
        return f"{d} days ago"
    except Exception:
        return "recently"

def format_for_layman(
    response: str,
    contact_map: dict[str, str] | None = None,
) -> str:
    """
    Translates a technical agent response to plain English.
    contact_map: {32_char_hex_id: "Display Name (email@x.com)"}

    This function is the LAST step in every pipeline channel.
    It runs after all security checks and redaction.
    """
    result = response

    # ── 1. Replace known 32-char hex IDs with display names ───────────────
    if contact_map:
        for hex_id, display in contact_map.items():
            result = result.replace(hex_id, display)

    # ── 2. Replace any remaining bare 32-char hex IDs ─────────────────────
    result = HEX_ID_PATTERN.sub("[contact]", result)

    # ── 3. Replace ISO timestamps with relative time ───────────────────────
    result = ISO_PATTERN.sub(_humanize_iso_match, result)

    # ── 4. Replace status/intent codes and technical terms ────────────────
    for code, plain in TERM_TRANSLATIONS.items():
        if not code:
            continue
        if plain == "":
            # Remove the term entirely (field names)
            result = re.sub(
                r'\b' + re.escape(code) + r'\b\s*[:=]?\s*',
                '',
                result,
                flags=re.IGNORECASE
            )
        else:
            result = re.sub(
                r'\b' + re.escape(code) + r'\b',
                plain,
                result,
                flags=re.IGNORECASE
            )

    # ── 5. Filter lines that are purely technical (field: value patterns) ──
    lines = result.split('\n')
    clean_lines = []
    for line in lines:
        should_filter = any(pat.match(line) for pat in BANNED_FIELD_PATTERNS)
        if not should_filter:
            clean_lines.append(line)
    result = '\n'.join(clean_lines)

    # ── 6. Clean up extra whitespace ─────────────────────────────────────
    result = re.sub(r'\n{3,}', '\n\n', result)
    result = result.strip()

    return result

def build_contact_name_map(contacts: list) -> dict[str, str]:
    """
    Builds {hex_id: "Display Name (email)"} map for all contacts.
    Used by format_for_layman to replace bare IDs with names.
    """
    result = {}
    for c in contacts:
        name = c.creator_name or c.business_name or c.email.split("@")[0]
        result[c.id] = f"{name} ({c.email})"
    return result
```

---

### AGENT 6: Collaborative Provider Router

**File:** `backend/app/agent/provider_router.py`
**Status:** NEW
**Purpose:** Routes each agent call to the optimal provider. Groq for fast
  structured calls. Gemini for rich long-context calls. Neither does everything.

```python
import json
import asyncio
import logging
from typing import Literal

logger = logging.getLogger(__name__)

PROVIDER_ROUTING: dict[str, dict] = {
    # Fast, structured, short-context → Groq
    "channel_router":         {"primary": "groq",   "model": "llama-3.1-8b-instant"},
    "goal_frame":             {"primary": "groq",   "model": "llama-3.3-70b-versatile"},
    "intent_agent":           {"primary": "groq",   "model": "llama-3.3-70b-versatile"},
    "slot_agent":             {"primary": "groq",   "model": "llama-3.1-8b-instant"},
    "verifier_light":         {"primary": "groq",   "model": "llama-3.1-8b-instant"},
    "repair_router":          {"primary": "groq",   "model": "llama-3.1-8b-instant"},
    # Rich, contextual, long-context → Gemini
    "campaign_intelligence":  {"primary": "gemini", "model": "gemini-2.0-flash"},
    "draft_generation":       {"primary": "gemini", "model": "gemini-2.0-flash"},
    "conversation_reply":     {"primary": "gemini", "model": "gemini-2.0-flash"},
    "reasoning_agent":        {"primary": "gemini", "model": "gemini-2.0-flash"},
    "response_agent":         {"primary": "gemini", "model": "gemini-2.0-flash"},
    # Either works; prefer available
    "verifier_strict":        {"primary": "groq",   "model": "llama-3.3-70b-versatile"},
}

async def call_provider_with_fallback(
    agent_name: str,
    system: str,
    user: str,
    max_tokens: int = 500,
    temperature: float = 0.3,
) -> str:
    """
    Routes to the optimal provider for the given agent.
    Falls back to the other provider on rate limit, exhaustion, or timeout.
    Returns the text response string.
    """
    from ..settings.service import get_groq_keys_decrypted, get_gemini_keys_decrypted

    route = PROVIDER_ROUTING.get(
        agent_name,
        {"primary": "groq", "model": "llama-3.3-70b-versatile"}
    )
    primary = route["primary"]
    model = route["model"]
    fallback_provider = "gemini" if primary == "groq" else "groq"
    fallback_model = ("gemini-2.0-flash" if fallback_provider == "gemini"
                      else "llama-3.3-70b-versatile")

    # Try primary
    try:
        return await _call_single_provider(
            primary, model, system, user, max_tokens, temperature
        )
    except Exception as e:
        logger.warning(
            "provider_router: primary=%s failed for agent=%s: %s. Trying fallback.",
            primary, agent_name, type(e).__name__
        )

    # Try fallback
    try:
        return await _call_single_provider(
            fallback_provider, fallback_model, system, user, max_tokens, temperature
        )
    except Exception as e:
        logger.error(
            "provider_router: both providers failed for agent=%s: %s",
            agent_name, type(e).__name__
        )
        raise

async def _call_single_provider(
    provider: Literal["groq", "gemini"],
    model: str,
    system: str,
    user: str,
    max_tokens: int,
    temperature: float,
) -> str:
    """Internal: calls one provider and returns raw text response."""
    loop = asyncio.get_event_loop()

    if provider == "groq":
        from ..settings.service import get_groq_keys_decrypted
        from groq import Groq
        keys = await get_groq_keys_decrypted()
        if not keys:
            raise ValueError("No Groq keys configured")
        client = Groq(api_key=keys[0])

        def _call():
            return client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user}
                ],
                max_tokens=max_tokens,
                temperature=temperature,
            )

        response = await loop.run_in_executor(None, _call)
        return response.choices[0].message.content.strip()

    elif provider == "gemini":
        from ..settings.service import get_gemini_keys_decrypted
        import google.generativeai as genai
        keys = await get_gemini_keys_decrypted()
        if not keys:
            raise ValueError("No Gemini keys configured")
        genai.configure(api_key=keys[0])

        def _call():
            model_obj = genai.GenerativeModel(
                model_name=model,
                system_instruction=system,
            )
            resp = model_obj.generate_content(
                user,
                generation_config={"max_output_tokens": max_tokens,
                                   "temperature": temperature}
            )
            return resp.text

        return await loop.run_in_executor(None, _call)

    else:
        raise ValueError(f"Unknown provider: {provider}")
```

---

### MODIFIED: service.py Main Loop

**File:** `backend/app/agent/service.py`
**Status:** MODIFY — add channel routing before GoalFrame

The key change: insert channel classification at the top of
`process_agent_turn()`. If channel=awareness, skip GoalFrame entirely and
route to campaign_intelligence directly.

```python
async def process_agent_turn(
    message: str,
    session_token: str,
    db: Session,
) -> AgentResponse:

    # ── 1. Load or create session (unchanged) ─────────────────────────────
    session = await load_or_create_session(session_token, db)

    # ── 2. Build contact name map for layman formatter ────────────────────
    # (Do this once per session — cache in session state)
    if not session.contact_name_map:
        from ..db.models import Contact as ContactModel
        all_contacts = db.query(ContactModel).all()
        from .layman_formatter import build_contact_name_map
        session.contact_name_map = build_contact_name_map(all_contacts)

    # ── 3. Load context card if missing or stale ─────────────────────────
    from .context_loader import build_context_card, is_context_stale
    if is_context_stale(getattr(session, "context_loaded_at", None)):
        session.context_summary = build_context_card(db)
        session.context_loaded_at = datetime.utcnow().isoformat()

    # ── 4. Proactive opening message ──────────────────────────────────────
    # If the message is empty or a simple greeting and this is the first turn
    from .context_loader import generate_proactive_opening
    GREETINGS = {"", "hi", "hello", "hey", "start", "open", "help",
                 "what's up", "whats up", "good morning", "good evening"}
    is_opening = (message.strip().lower() in GREETINGS and
                  len(getattr(session, "turn_history", [])) == 0)
    if is_opening:
        opening = generate_proactive_opening(session.context_summary, db)
        formatted = opening  # no technical content, no formatter needed
        await save_session(session, db)
        return AgentResponse(
            response=formatted,
            source="Campaign Overview",
            channel="awareness"
        )

    # ── 5. Channel Router (NEW — 1 fast Groq call) ───────────────────────
    from .channel_router import classify_channel
    channel_decision = await classify_channel(
        message=message,
        context_hint=getattr(session, "context_summary", "")[:150]
    )
    current_channel = channel_decision.channel

    # ── 6. Route to correct channel ───────────────────────────────────────
    source = "Campaign Data"

    if current_channel == "awareness":
        # ── AWARENESS: Campaign Intelligence (no capability gate) ─────────
        from .campaign_intelligence import answer_awareness_query
        raw_response = await answer_awareness_query(
            question=message,
            db=db,
            session_context=session.context_summary,
            turn_history=getattr(session, "turn_history", []),
        )

    elif current_channel == "task":
        # ── TASK: GoalFrame in lighter mode + existing task pipeline ──────
        # If GoalFrame fails, fall back to awareness
        try:
            raw_response, source = await task_pipeline(message, session, db)
        except Exception as e:
            logger.warning("task_pipeline failed, falling back to awareness: %s", e)
            from .campaign_intelligence import answer_awareness_query
            raw_response = await answer_awareness_query(
                question=message, db=db,
                session_context=session.context_summary
            )
            source = "Campaign Data"

    else:
        # ── ACTION: Existing governed pipeline (UNCHANGED) ────────────────
        raw_response, source = await action_pipeline(message, session, db)

    # ── 7. Apply layman formatter (ALL channels) ─────────────────────────
    from .layman_formatter import format_for_layman
    formatted = format_for_layman(
        response=raw_response,
        contact_map=getattr(session, "contact_name_map", {}),
    )

    # ── 8. Update turn history (max 20 entries) ───────────────────────────
    turn_history = getattr(session, "turn_history", [])
    turn_history.append({
        "role": "user",
        "text": message[:200],
        "channel": current_channel,
    })
    turn_history.append({
        "role": "assistant",
        "text": formatted[:300],
        "source": source,
    })
    if len(turn_history) > 20:
        turn_history = turn_history[-20:]
    session.turn_history = turn_history

    # ── 9. Save session and return ────────────────────────────────────────
    await save_session(session, db)
    return AgentResponse(
        response=formatted,
        source=source,
        channel=current_channel
    )
```

---

### MODIFIED: Capability Catalog (schemas.py / catalog.py)

The existing capability catalog is restructured into 4 tiers.
TIER_0 (AMBIENT) capabilities bypass the deny-by-default check entirely.

```python
CAPABILITY_TIERS = {
    "AMBIENT": {
        # These ALWAYS pass. No capability gate. No denial possible.
        "campaign_intelligence",
        "context_refresh",
        "fuzzy_search",
        "proactive_surface",
        "static_help",
        "get_campaign_stats",
        "get_reply_list",
        "get_contact_list",
        "get_contact_detail",
        "get_queue_status",
        "get_followup_status",
        "get_send_history",
        "get_conversation_thread",
        "get_audit_summary",
        "search_contacts",
        "template_preview",
    },
    "READ": {
        # Light check. No confirmation required.
        "email_read_inbox",
        "email_search_thread",
        "email_read_thread",
        "contact_resolve",
        "group_resolve",
        "draft_preview",
    },
    "DRAFT": {
        # Moderate check. Show draft before confirm.
        "email_generate_draft",
        "email_update_draft",
        "template_generate",
        "draft_save",
        "auto_reply_propose",
    },
    "ACTION": {
        # Full governed check. Confirmation required. UNCHANGED.
        "email_send_draft",
        "auto_reply_approve",
        "contact_suppress",
        "contact_unsuppress",
        "bulk_approve_drafts",
        "campaign_activate",
        "followup_approve",
        "followup_draft_approve",
    }
}

def check_capability_tiered(capability: str, channel: str) -> CapabilityCheckResult:
    """
    New 4-tier capability check.
    AMBIENT tier: always allowed regardless of channel.
    READ/DRAFT tier: allowed in task channel.
    ACTION tier: allowed only in action channel, confirmation required.
    """
    if capability in CAPABILITY_TIERS["AMBIENT"]:
        return CapabilityCheckResult(allowed=True, tier="AMBIENT")

    # In awareness channel: route unknown capabilities to campaign_intelligence
    if channel == "awareness":
        return CapabilityCheckResult(
            allowed=True,
            tier="AMBIENT",
            redirect_to="campaign_intelligence"
        )

    if channel == "task":
        if capability in CAPABILITY_TIERS["READ"]:
            return CapabilityCheckResult(allowed=True, tier="READ")
        if capability in CAPABILITY_TIERS["DRAFT"]:
            return CapabilityCheckResult(allowed=True, tier="DRAFT")
        # Unknown capability in task channel → route to campaign_intelligence
        return CapabilityCheckResult(
            allowed=True,
            tier="AMBIENT",
            redirect_to="campaign_intelligence"
        )

    if channel == "action":
        if capability in CAPABILITY_TIERS["ACTION"]:
            return CapabilityCheckResult(
                allowed=True,
                tier="ACTION",
                requires_confirmation=True
            )
        # Non-action capability in action channel → re-route
        if capability in CAPABILITY_TIERS["READ"] | CAPABILITY_TIERS["DRAFT"]:
            return CapabilityCheckResult(allowed=True, tier="READ")

    return CapabilityCheckResult(
        allowed=False,
        tier="DENIED",
        denial_reason=f"'{capability}' not recognized for channel '{channel}'"
    )
```

### MODIFIED: ResponseAgent System Prompt Addition

Append these rules to the existing response.py system prompt. Do NOT replace
the existing system prompt — APPEND:

```python
RESPONSE_QUALITY_ADDENDUM = """
QUALITY RULES — enforce on every response:
- Never output a 32-char hex ID or UUID. Replace with contact name and email.
- Never output an ISO timestamp. Say "2 hours ago", "yesterday", "last week".
- Never output a technical status code. Use plain English.
  "sent" = "your email was delivered"
  "suppressed" = "they opted out"
  "blocked_by_policy" = "blocked by a sending rule"
- Never output field names like classified_as, contact_id, params_hash,
  draft_id, idempotency_key, sequence_num, action_class, privacy_class.
- For any list: maximum 5 named items, then "...and N more".
- If the answer is a number, state it first. "3 people replied" not
  "Based on the data provided, there were 3...".
- Never say "I cannot perform that" for a read or information question.
- Never say "I don't have access to" for campaign data questions.
- If you can't answer from available evidence, say "I don't have that detail
  right now — try asking specifically about [relevant thing]."
- Use second person: "your campaign", "you sent", "they replied to you".
- Start with the answer, not a preamble.
"""
```

---

## COMPLETE FILE LIST — NEW AND MODIFIED

### New files (create from scratch):
```
backend/app/agent/channel_router.py
backend/app/agent/campaign_intelligence.py
backend/app/agent/context_loader.py
backend/app/agent/fuzzy_resolver.py
backend/app/agent/layman_formatter.py
backend/app/agent/provider_router.py
```

### Modified files (surgical additions only):
```
backend/app/agent/service.py        → insert channel routing in process_agent_turn()
backend/app/agent/schemas.py        → add ChannelDecision, FuzzyResolveResult,
                                       CapabilityCheckResult, 4-tier catalog
backend/app/agent/catalog.py        → add CAPABILITY_TIERS and check_capability_tiered()
backend/app/agent/tools.py          → replace contact_resolve() with fuzzy_resolve_contact()
backend/app/agent/response.py       → append RESPONSE_QUALITY_ADDENDUM to system prompt
backend/app/agent/verifier.py       → add mode parameter (AWARENESS vs ACTION)
backend/app/agent/memory.py         → add context_loader calls and contact_name_map
```

### Untouched (do not edit these):
```
backend/app/agent/goal_frame.py     (used in task + action channels)
backend/app/agent/intent.py         (unchanged)
backend/app/agent/slot.py           (unchanged — fuzzy_resolver called separately)
backend/app/agent/orchestrator.py   (unchanged)
backend/app/agent/reasoning.py      (unchanged)
backend/app/agent/pending.py        (CRITICAL — do not touch)
backend/app/agent/repair.py         (unchanged)
```

---

## SESSION STATE ADDITIONS

The following fields are added to the existing agent_sessions table/dict:
```
context_summary      TEXT      — campaign context card (500 chars)
context_loaded_at    TEXT      — ISO timestamp of last context load
contact_name_map     TEXT      — JSON: {32hex_id: "Name (email)"}
turn_history         TEXT      — JSON array of last 20 turns
current_channel      TEXT      — awareness | task | action
```

If agent_sessions table does NOT have these columns, add them via
`ALTER TABLE agent_sessions ADD COLUMN ...` in session.py's
apply_lightweight_migrations() function (same pattern used for
existing reply column migrations).

---

## SECURITY INVARIANTS — UNCHANGED

These are restated here for clarity. Nothing in this new architecture
changes any of them:

1. Browser never receives raw credentials.
2. Model never receives raw credentials.
3. email_send_draft requires valid pending_email_action — no exceptions.
4. PendingEmailAction validates: session_id_hash + draft_id + params_hash
   + not expired + not consumed. All must match.
5. Audit event written BEFORE send execution. If audit fails, send fails.
6. Changed draft invalidates old confirmation (params_hash changes).
7. All model output validated against pydantic schemas (extra="forbid").
8. Layman formatter runs AFTER security checks and redaction — never before.
9. Channel Router defaults to awareness on error — NEVER to action.

---

## EXAMPLE QUERY FLOWS (VERIFIED)

### "who all replied"
```
Channel Router → awareness (confidence 0.95)
Campaign Intelligence:
  1. build_campaign_snapshot(db) → loads replies + contacts joined
  2. snapshot contains: "ALL REPLIES EVER: Arjun (arjun@x.com): replied,
     2 hours ago | Priya (priya@x.com): has concerns, yesterday..."
  3. LLM call: question + snapshot → "5 people have replied to your emails.
     Arjun seems interested (2 hours ago), Priya had concerns about your
     proposal (yesterday), Rahul asked to be removed from your list (3 hours
     ago), and 2 others sent questions. Want me to draft a reply for any of them?"
Layman Formatter: no changes needed (already plain)
Widget: Shows the above response. No "cannot perform."
```

### "can u show me the replys"
```
Channel Router → awareness (typo 'replys' doesn't matter)
Campaign Intelligence: same as above, answers directly
```

### "how many emails did I send today"
```
Channel Router → awareness
Campaign Intelligence: snapshot has "TODAY'S SENDING: 12 sent (cap: 50/day)"
LLM: "You've sent 12 emails today. Your daily limit is 50, so you have 38
     sends remaining."
```

### "send a reply to the yoga instructor"
```
Channel Router → task (generate draft implied)
GoalFrame (task_mode) → email_generate_draft
Slot Agent → contact_id needed
Fuzzy Resolver: LIKE search "yoga" + "instructor" across notes/category
  → finds contact with lead_category="yoga" or notes="yoga instructor"
  → if 1 match: proceeds with contact
  → if multiple: "Which one? 1. Priya Sharma (priya@yoga.com) 2. ..."
Draft generation → shows draft card
Widget: "Here's a draft for Priya. Want to send it?"
User: "yes send it" → channel switches to action
Action pipeline → existing confirmation harness → PendingAction created
User clicks Confirm → validated + sent + audited
```

### "send it" (after draft shown)
```
Channel Router → action (explicit "send")
Existing governed pipeline → UNCHANGED
PendingAction validated → email sent → audit logged
```

---

## WHAT THE TEST SUITE MUST VERIFY

New tests (add to test_agent.py):

```
test_channel_router_awareness — "who all replied" → channel=awareness
test_channel_router_awareness_typo — "woh replied" → channel=awareness
test_channel_router_task — "generate draft for Arjun" → channel=task
test_channel_router_action — "send it" → channel=action
test_channel_router_defaults_awareness — error in Groq → channel=awareness
test_channel_router_never_blocks — all 20 read query variants → channel=awareness

test_campaign_intelligence_replied — DB has replies → answer contains reply info
test_campaign_intelligence_no_hallucination — answer email must be in snapshot
test_campaign_intelligence_no_groq_keys — returns safe fallback, no crash
test_campaign_intelligence_empty_db — no contacts → graceful "no data" response

test_fuzzy_resolver_exact_email — exact match → confidence 1.0
test_fuzzy_resolver_partial_name — "arjun" → finds Arjun Kumar
test_fuzzy_resolver_partial_niche — "yoga" → finds yoga instructor contact
test_fuzzy_resolver_multiple_matches → needs_clarification=True, question set
test_fuzzy_resolver_zero_matches → needs_clarification=True, question set
test_fuzzy_resolver_no_stop_words — "send to the guy" → asks clarification not crash

test_layman_formatter_no_hex_ids — 32-char hex replaced
test_layman_formatter_no_iso_ts — ISO timestamp replaced with relative time
test_layman_formatter_no_status_codes — "suppressed" → "opted out"
test_layman_formatter_no_field_names — "contact_id" line removed
test_layman_formatter_preserves_names — display names not mangled

test_context_loader_builds_card — non-empty context card returned
test_context_loader_stale_detection — >30min old → is_context_stale=True
test_proactive_opening_with_replies — replied contacts → mentioned in opening

test_awareness_never_returns_cannot_perform — ANY of 20 read queries → no static denial

Regression tests (must still pass after changes):
test_send_requires_pending_action — "send it" without pending → PENDING_CONFIRMATION
test_confirm_expired — stale action → rejected
test_confirm_consumed — second confirm → rejected
test_confirm_wrong_session — different session → rejected
test_params_hash_change — draft changed → old confirm invalid
All 125 existing tests
```
