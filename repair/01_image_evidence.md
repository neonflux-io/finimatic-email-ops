# repair/01_image_evidence.md — Per-Image Analysis

---

## Image 01 — Provider Health Surface + Floating Assistant Open

**Surface:** Provider Health  
**Mode indicators:** SMTP_VERIFIED | LIVE | LISTENING  
**Visible data:**
- Gmail: rossdmello869@gmail.com — SMTP_VERIFIED
- Groq: 3 keys, fingerprints b001c9c739b3, 9b5108e0ee4a, 2fe2dbd75d4f — CONFIGURED
- Gemini: 6 keys, fingerprints 77014cdbda05, 22f6d6b86441, 62a2a7dbc9f5, 35c29f5fe670, 8992a2c41ba7, 14b1d85b2feb — CONFIGURED
- IMAP panel is partially cut off (right side)
- Floating assistant is open, showing reply loop contact list including "Policy Gate G5 (crce.9955.ce+gate5@gmail.com)"
- Assistant shows: "Sachi Khan asked about what exactly RAG is, and also mentioned being interested in RAG chatbots, and asked about office policies."
- Assistant model selector shows "Auto (Groq → Gemini)"

**Related source files:**
- `backend/app/provider_health/router.py`
- `backend/app/agent/service.py`
- `backend/app/settings/router.py`
- `frontend/src/App.tsx` ProviderHealthPanel

**Suspected mismatches:**
- IMAP provider panel is cut off. Previously confirmed IMAP status = `failed` / `TimeoutError`. The health panel should prominently show this.
- Contact list in assistant shows test-persona emails like `rossdmello896+replyloop-*` and `+cleanround3-*` — these are test personas that should be suppressed or cleaned from production use.
- The assistant is answering an awareness query about Sachi Khan's reply intent. This is from `answer_awareness_query()` in `campaign_intelligence.py`.

**Confidence:** HIGH — screenshot is clear; IMAP failure is independently confirmed.

---

## Image 02 — Import Surface

**Surface:** Import  
**Mode indicators:** SMTP_VERIFIED | LIVE | LISTENING  
**Badge:** 36 contacts  
**Visible data:**
- Manual entry fields: Email, Creator Name, Website
- Tags field with placeholder "udemy-creator, coach"
- Info / AI Context field
- Upload CSV/TXT button
- Paste textarea
- Three action buttons: Preview, Commit, Submit

**Related source files:**
- `backend/app/imports/router.py`
- `backend/app/imports/service.py`
- `frontend/src/App.tsx` ImportPanel

**Suspected mismatches:**
- Two separate action buttons: **Commit** and **Submit**. The original design has Preview → Commit. A third "Submit" button implies a newer direct-submit path was added. This needs source inspection to confirm whether Submit is a single-row manual entry path or a duplicate of Commit.
- The 36-contacts badge is a header stat. If CSV import commits succeed but contacts are not appearing, the invalidation query may target a different cache key or the contact dedup is silently skipping.
- Preview stores state in process-local `PREVIEWS` dict (`imports/service.py`). A backend restart between Preview and Commit silently loses preview state; Commit then has no rows to write.

**Confidence:** HIGH on in-memory preview risk (confirmed in `architecture_test.md`).

---

## Image 03 — Contacts Surface

**Surface:** Contacts  
**Mode indicators:** SMTP_VERIFIED | LIVE (browser time 16:47)  
**Visible data:**
- Table columns: Checkbox, Email, Name, Website, Info, Status, Source, Tags, Auto-Reply, Actions
- Rows visible:
  - crce.9955.ce@gmail.com — Career Coach Creator — draft_ready — manualmanual — auto-reply ON
  - rossdmello896@gmail.com — Data Science Educator — draft_ready — manual — auto-reply INHERIT
  - sachitawte@gmail.com — sachi khan — draft_ready — manual — corsera creator — auto-reply INHERIT
  - rossdmello1@gmail.com — Ross Demo Contact — demo.example — draft_ready — browser-demo — INHERIT
  - rathiaditi2007@gmail.com — adil khan — draft_needed — manual — auto-reply ON
  - shawn.dmello2803@gmail.com — shawn dmello — sent — manual — youtube creator — auto-reply ON
  - support@zerotomastery.io — Zero To Mastery / Andrei Neagoie — imported — csv_import — coding education — auto-reply INHERIT
- Source column shows "manualmanual" for first row (possible double-write bug)
- AUTO-REPLY column shows per-contact toggles: Inherit / On / Off / Propose

**Related source files:**
- `backend/app/contacts/router.py`
- `backend/app/db/models.py` Contact model
- `frontend/src/App.tsx` ContactsPanel

**Suspected mismatches:**
- Row 1 (crce.9955.ce@gmail.com) shows source = "manualmanual" — this is a concatenation/double-write bug in source labeling. Expected: "manual". `backend/app/contacts/utils.py` or the router may be appending source twice.
- AUTO-REPLY per-contact override column is newer than original design; `models.py` must include `auto_reply_override` column. Original docs do not document this column.
- `shawn.dmello2803@gmail.com` shows status=`sent`. Image 10 (Conversations) shows this contact's conversation thread and `Auto-reply ON`. After a `sent` state, the system should be watching for replies to trigger follow-ups, not issuing a new cold send.

**Confidence:** HIGH on source=manualmanual bug. MEDIUM on auto-reply column existence (need model confirmation).

---

## Image 04 — Drafts Surface

**Surface:** Drafts  
**Mode indicators:** SMTP_VERIFIED | LIVE  
**Visible data:**
- Contact dropdown: shawn.dmello2803@gmail.com selected
- Provider tabs: manual | auto | groq | **gemini** (selected, highlighted)
- Load Template dropdown: No template
- Auto-Reply toggle: AUTO-REPLY ON | On | Off
- Draft Library: 150 total, 65 unapproved
- Draft card 1: APPROVED badge, llama-3.1-8b-instant, shawn.dmello2803@gmail.com · approved 2026-05-26T11:08:35, Subject: "Enhance Your Course with AI-Powered Chatbots", Body visible. Buttons: Save, Save as Template, **Approve Follow-up #2**
- Draft card 2: APPROVED badge, gemini-2.5-flash, shawn.dmello2803@gmail.com · approved 2026-05-26T10:55:24, Subject: "RAG for your courses, Shawn?". Buttons: Save, Save as Template, **Approve Follow-up #2**
- Left compose panel: empty Subject/Body, Generate / Save Draft / Approve Follow-up #2 buttons

**Related source files:**
- `backend/app/drafts/router.py`
- `backend/app/followups/service.py`
- `frontend/src/App.tsx` DraftsPanel

**Key findings — Draft Approval Workflow:**

1. The button label is "Approve Follow-up #2" NOT "Approve & Queue". This means the visible drafts are already initial-sequence drafts, and the button creates a **follow-up** sequence-2 queue entry, not a fresh cold send.
2. 150 total drafts, 65 unapproved — high unapproved count suggests bulk generation was run but not all drafts approved.
3. The toast "draft saved, approved, and queued" referenced in the brief is for the Approve flow, but the UI here shows "Approve Follow-up #2" — the user may be confused because follow-up approval and initial approval look identical in the UI.
4. Draft cards are already APPROVED — initial send presumably happened or was queued.

**Suspected mismatches:**
- "Approve Follow-up #2" implies `followups/service.py` creates a `send_queue` entry with `sequence_num=2`. But the queue table (Image 07) shows some contacts with sequence 2 and 3 sent. The workflow is functioning for some contacts.
- If shawn.dmello2803@gmail.com is in `sent` status (Image 03), a follow-up approval should be gated on whether the first send actually landed. The follow-up button should check `send_attempts` existence.
- The compose panel on the LEFT is for generating a NEW draft. It has a "Approve Follow-up #2" button in the left panel as well, which is confusing — why would a freshly composed draft become a follow-up?

**Confidence:** HIGH on workflow confusion. HIGH on follow-up vs. initial approval conflation.

---

## Image 05 — Templates Surface

**Surface:** Templates  
**Mode indicators:** SMTP_VERIFIED | LIVE  
**Visible data:**
- Create form: Name, Subject Template, Body Template
- Saved templates:
  - Browser Template: "Idea for {{full_name}}" / "Hi {{first_name}}, I saw {{website}}."
  - Browser Demo AI Automation: "AI automation idea for {{first_name}}" / "Hi {{first_name}}, I saw {{website}} and wanted to share..."
  - Browser Demo AI: "AI automation idea for {{first_name}}" / similar body
- Token placeholders visible: `{{first_name}}`, `{{full_name}}`, `{{website}}`

**Related source files:**
- `backend/app/templates/router.py`
- `frontend/src/App.tsx` TemplatesPanel

**Suspected mismatches:**
- Templates appear normal and functional.
- Two nearly duplicate templates ("Browser Demo AI Automation" and "Browser Demo AI") — possible accidental double-save.
- The `{{niche}}` token defined in source is not visible in any template body here — minor inconsistency but not a bug.

**Confidence:** LOW severity. Templates surface appears healthy.

---

## Image 06 — Campaigns Surface

**Surface:** Campaigns  
**Mode indicators:** SMTP_VERIFIED | LIVE  
**Visible data:**
- Create Campaign form: Name, Target Tags, Status=draft, Campaign Goal textarea
- Action buttons: Generate 3-Step Sequence, Save Plan, Activate Campaign
- Three sequence slots: Initial Email (initial outreach), Follow-up 1 (value-add follow-up), Breakup Email (polite breakup email)
- All Subject/Body fields are empty
- Active Campaigns section visible but cut off

**Related source files:**
- `backend/app/campaigns/router.py`
- `frontend/src/App.tsx` CampaignsPanel

**Suspected mismatches:**
- Campaign surface is newer than original docs (confirmed stale in `relation.md`).
- "Activate Campaign" button with empty fields — if clicked, should the backend validate non-empty Subject/Body? If not, an empty campaign activation could push blank drafts into queue.
- Campaigns have their own target-tag filtering. If tag-based send intersects with existing queue entries, duplicate sends may occur.
- The Campaign surface is not connected to the standard queue policy in the same way as individual draft approval. This needs verification.

**Confidence:** MEDIUM risk on empty activation / policy integration. UNVERIFIED on campaign-to-queue path.

---

## Image 07 — Queue Surface

**Surface:** Queue  
**Mode indicators:** SMTP_VERIFIED | LIVE  
**Visible data:**
- Process button (top right) — manual trigger
- Table columns: Status, Contact, Subject, Sequence, Scheduled, Blocks
- ALL visible rows show status = **sent**
- Rows span dates 2026-05-23 to 2026-05-26
- Contacts are shown as UUID hex strings (not emails) — unusual for a user-facing column
- One contact (934d90a5...) has sequences 1, 2, 3 all showing status `sent`
- One contact (92d8fa13...) has sequences 1, 2 visible
- BLOCKS column appears EMPTY for all rows

**Related source files:**
- `backend/app/send/router.py`
- `backend/app/send/queue_worker.py`
- `backend/app/send/policy.py`

**Key findings:**

1. All visible queue entries are `sent`. This means for the contacts shown, the sends succeeded (or were marked sent in dry-run-blocked/skipped state — cannot confirm from this screenshot alone).
2. The BLOCKS column is present but empty — this means either no entries were blocked, or `policy_block_reasons` is not being displayed even when populated.
3. Contact column shows UUID hex, not email. This is harder to read for an operator. Should show email or name.
4. The "Process" button triggers manual queue processing (`POST /api/queue/process`). Background worker also runs every 30s. Both paths exist.
5. The user symptom "email does not reach end user" is not directly visible in this screenshot — all shown entries are `sent`. The problem may be in the underlying SMTP delivery, or in OTHER contacts not visible on this page.

**Suspected mismatches:**
- If any queue entries exist with `blocked` or `pending` status for current live contacts (like crce.9955.ce@gmail.com whose follow-ups are stopped), they would not appear in this view unless the user scrolls or filters. The UI doesn't show a filter by status.
- The `sent` status in `send_queue` means the queue entry was processed, but does NOT guarantee Gmail delivered the email. `send_attempts.status=success` and `provider_msg_id` are the real SMTP success indicators.

**Confidence:** HIGH that BLOCKS column is empty/not rendering. HIGH that contact UUIDs reduce operator clarity.

---

## Image 08 — Follow-ups Surface

**Surface:** Follow-ups  
**Mode indicators:** SMTP_VERIFIED | LIVE  
**Visible data:**
- Process button (top right)
- Table columns: Status, Sequence, Due, Contact, Stop Reason
- Status values: dispatched, stopped
- Stop reasons: RECIPIENT_REPLIED, CONTACT_DELETED
- Follow-up rows for emails like crce.9955.ce+persona1@gmail.com through +persona4r3@gmail.com
- Multiple `CONTACT_DELETED` stops — these are test personas that were deleted after follow-up was scheduled
- `RECIPIENT_REPLIED` stops — reply was received and follow-up correctly stopped
- `dispatched` rows for +persona4r2 and +persona4r3 — two sequence numbers (2 and 3) dispatched

**Related source files:**
- `backend/app/followups/router.py`
- `backend/app/followups/service.py`
- `backend/app/replies/service.py`

**Key findings:**

1. `CONTACT_DELETED` as a stop reason confirms soft-delete does cascade to follow-up stopping — this is working correctly.
2. `RECIPIENT_REPLIED` stop confirms reply detection → follow-up stop pipeline is working for some contacts.
3. `dispatched` status means a follow-up draft was generated and a queue entry was created for the sequence. The email would then go through queue → policy → send. So "dispatched" ≠ "sent to Gmail."
4. The user's complaint about follow-ups may be that `dispatched` rows don't have a clear "was it actually sent" path visible.

**Suspected mismatches:**
- A `dispatched` follow-up creates a new queue entry. That queue entry must pass ALL policy gates again. If the contact was suppressed or replied after the follow-up was scheduled, the queue entry would be blocked — but this surface wouldn't show that.
- No `skipped` or `due` rows visible — all follow-ups have been processed. This is expected if the background loop is healthy.

**Confidence:** HIGH on dispatched ≠ delivered confusion. MEDIUM on missing cross-reference between follow-up dispatch and queue send status.

---

## Image 09 — Replies/Stops Surface

**Surface:** Replies/Stops  
**Mode indicators:** SMTP_VERIFIED | LIVE (browser time 16:49)  
**Visible data:**
- Counts: ACTIVE 65, ARCHIVED 0, VISIBLE 65
- Filters: View=Active only, Class=All classes, Intent=All intents, Contact=All contacts
- Manual Stop panel showing contact crce.9955.ce@gmail.com, Class=reply
- Reply entries from crce.9955.ce@gmail.com:
  - 2026-05-26T09:31:12 — REPLY / OBJECTION — "50 users per day On Tue, 26 May 2026..."
  - 2026-05-26T09:20:14 — REPLY / POSITIVE_INTEREST — "Yes, I would. tomorrow at 3 am ist..."
  - 2026-05-26T09:14:40 — REPLY / QUESTION — "How much do you charge?"
- Archive / Delete buttons per reply

**Related source files:**
- `backend/app/replies/router.py`
- `backend/app/replies/service.py`
- `backend/app/replies/imap_fetcher.py`

**Key findings:**

1. 65 active replies is significant. These are real replies from crce.9955.ce@gmail.com (Career Coach Creator). The replies are classified with intents: OBJECTION, POSITIVE_INTEREST, QUESTION.
2. This contact has `RECIPIENT_REPLIED` follow-up stops (Image 08), which is correct.
3. The most recent reply (OBJECTION — "50 users per day") appears to be a price/scope objection in an ongoing negotiation. The auto-reply system in `Autonomous send` mode (Image 11) may be responding to this contact WITHOUT the operator seeing it.
4. IMAP fetch is confirmed failing (TimeoutError). The replies shown here were fetched previously when IMAP was healthy, OR were entered manually via the Replies/Stops surface.

**Suspected mismatches:**
- If IMAP is currently failing, no new replies are being ingested automatically. The "Fetch Now" button would also fail. The operator needs to know this.
- The `OBJECTION` intent classification on the most recent reply from crce.9955.ce@gmail.com raises a question: is the auto-reply system (in Autonomous mode) responding to OBJECTION-classified replies? This would be risky behavior.

**Confidence:** HIGH on IMAP failure impact. HIGH on autonomous reply risk for OBJECTION-class replies.

---

## Image 10 — Conversations Surface

**Surface:** Conversations  
**Mode indicators:** SMTP_VERIFIED | LIVE  
**Visible data:**
- View filter: Needs reply (0)
- Contact filter: shawn.dmello2803@gmail.com
- Contact info panel: Prospect=shawn dmello, Website=not provided, Status=sent, Auto-reply=Auto-reply ON, Last Checked=5/26/2026 4:49:05 PM
- Conversation thread showing one outbound message from "You" at 5/26/2026 4:39:01 PM: Subject "Enhance Your Course with AI-Powered Chatbots", full body visible
- Reply composer: Provider=gemini, Language=match recipient, Subject field, Instruction="Answer the latest reply and move toward one practical next step."
- Reply Body section visible at bottom

**Related source files:**
- `backend/app/conversations/router.py`
- `backend/app/conversations/auto_reply_service.py`
- `frontend/src/App.tsx` ConversationsPanel

**Key findings:**

1. This conversation has only ONE message (outbound cold send). Status = `sent`. View filter shows "Needs reply (0)" — meaning the system correctly treats this as a one-way send with no received reply yet.
2. The **GET of this conversation page committed a backfill write** — the outbound message was written to `conversation_messages` by the queue worker originally, but loading the conversation page can backfill additional messages. This is the GET-writes concern from `relation.md`.
3. The instruction pre-filled in the composer is "Answer the latest reply and move toward one practical next step." — this instruction is persisted or defaulted, but there is NO latest reply to answer (status=sent, no replies).
4. `Auto-reply ON` for this contact. Since IMAP is failing and no reply has arrived, the auto-reply would not fire yet.

**Suspected mismatches:**
- The reply composer is shown even though there's no inbound reply. A user could manually compose and send a follow-on email to shawn.dmello from the Conversations surface, bypassing the queue policy entirely (engaged send path in `conversations/router.py`).
- Generating a reply with the instruction "Answer the latest reply" when there IS no reply would produce hallucinated or irrelevant content.

**Confidence:** HIGH on premature reply composer display. HIGH on GET-backfill write concern.

---

## Image 11 — Auto-Reply Surface

**Surface:** Auto-Reply  
**Mode indicators:** SMTP_VERIFIED | LIVE (browser time 16:49)  
**Visible data:**
- Mode section: **Autonomous send** selected (active green button)
- Pending Approval tab active
- Activity Log tab available
- Pending approvals table:
  - Ross Demo Contact (rossdmello1@gmail.com) — Their Reply: "Yes, that works for me..." — AI Reply: "Re: AI automation idea for Ross..." — Generated: 5/25/2026 11:50:18 AM — Buttons: Approve, Edit, Reject
  - Clean Round 3 Data Science Educator (rossdmello896+cleanround3...) — CLEAN-ROUND-3 Python assistant — Generated: 5/24/2026 10:55:29 PM — Approve/Edit/Reject
  - Clean Round 2 Data Science Educator — CLEAN-ROUND-2 Python assistant — Generated: 5/24/2026 10:50:48 PM
  - Clean Round 1 Data Science Educator — Generated: 5/24/2026 10:42:27 PM

**Related source files:**
- `backend/app/conversations/auto_reply_service.py`
- `backend/app/conversations/auto_reply_router.py`
- `frontend/src/App.tsx` AutoReplyPanel

**CRITICAL finding:**

The mode is **Autonomous send** but the tab shows **Pending Approval**. This is contradictory. In autonomous mode, replies should send WITHOUT approval. The pending approval queue implies either:
1. These were generated BEFORE the mode was switched to autonomous.
2. There is a quality gate that held them back even in autonomous mode.
3. The mode label is cosmetic — the actual behavior is still approval-required.

Looking at Image 14 (Settings), the Reply Mode is "Autonomous (send immediately)" with Auto-Reply Daily Cap=100 and Min Gap=0 minutes. This IS the actual autonomous mode configuration. Pending items shown here are pre-existing proposals that have not yet been approved/rejected.

**Impact:** In autonomous mode, NEW incoming replies (when IMAP is healthy) will be responded to WITHOUT operator review. Given the OBJECTION-classified reply from crce.9955.ce@gmail.com (Image 09), an autonomous response to an objection could damage the sales relationship.

**Confidence:** CONFIRMED risk. The autonomous mode + OBJECTION reply combination is high risk.

---

## Image 12 — Suppressions Surface

**Surface:** Suppressions  
**Mode indicators:** SMTP_VERIFIED | LIVE  
**Visible data:**
- One suppression: crce.9955.ce+persona5r1@gmail.com — reason=unsubscribe — source=reply

**Related source files:**
- `backend/app/suppressions/router.py`
- `backend/app/replies/service.py`

**Findings:**
- Only 1 suppression visible. The crce.9955.ce persona variants that were deleted (CONTACT_DELETED in follow-ups, Image 08) were deleted rather than suppressed. If these are test personas for the main crce.9955.ce@gmail.com account (using Gmail alias +persona5r1), they could receive email again if new contact records are created with the same address.
- The suppression was created automatically from a reply classified as `unsubscribe`.
- Suppression source=reply confirms `replies/service.py` → suppression creation path is working.

**Confidence:** LOW severity. Functioning correctly.

---

## Image 13 — Audit Logs Surface

**Surface:** Audit Logs  
**Mode indicators:** SMTP_VERIFIED | LIVE  
**Visible data:**
- Events in chronological order (oldest first):
  - 2026-05-23T09:22:19 — settings.updated
  - 2026-05-23T09:22:22 — sender.smtp_verified
  - 2026-05-23T09:23:00 — settings.updated (×3 more)
  - 2026-05-23T09:25:42 — canary.attempt
  - 2026-05-23T09:25:42 — canary.success
  - 2026-05-23T09:26:49 — canary.attempt / canary.duplicate_blocked
  - 2026-05-23T09:27:21 — import.preview / import.committed (entity: import_batch)
  - 2026-05-23T09:27:51 — draft.ai_generated (entity: contact)
  - 2026-05-23T09:30:47 — draft.ai_failed (entity: contact)
  - 2026-05-23T09:32:02 — draft.ai_failed (entity: contact)
  - 2026-05-23T09:37:18 — draft.ai_generated (entity: contact)
  - 2026-05-23T09:40:11 — settings.updated

**Key findings:**

1. The audit trail shows a complete correct setup flow: settings → SMTP verify → canary → duplicate block → import → draft generation.
2. Two `draft.ai_failed` events at 09:30 and 09:32 — Groq generation failures during initial setup. The fallback or manual path was used.
3. `import.preview` and `import.committed` show as the same timestamp (09:27:21) — preview and commit happened almost simultaneously. This is unusually fast, suggesting the preview response was immediate and commit was triggered right after.
4. No `queue.gate_blocked` events visible — either none occurred, or this view is paginated and early events are not shown.

**Confidence:** HIGH. Audit trail appears correct and complete for shown events.

---

## Image 14 — Settings Surface (Top)

**Surface:** Settings  
**Mode indicators:** SMTP_VERIFIED | LIVE (browser time 16:50)  
**Visible data:**
- Gmail User: rossdmello869@gmail.com
- App Password: (empty — cleared after save)
- Report Recipient: crce.9955.ce@gmail.com
- Daily Cap: **500**
- Hourly Cap: **500**
- Send Delay: **0**
- Follow-up Days: 3
- Max Follow-ups: 2
- IMAP Fetch Interval: **2 minutes**
- About You: Ross Dmello, AI Systems Engineer, Direct tone, "I build RAG chatbots for course creators"
- Email Signature: "Best regards / Ross Dmello / AI Systems Engineer"
- Autonomous Reply section: Enable Auto-Reply System = CHECKED
- Reply Mode: **Autonomous (send immediately)**
- Auto-Reply Daily Cap: 100
- Minimum Gap Between Replies: **0 minutes**
- Warning text: "In Autonomous mode, replies will be sent without your review."

**CRITICAL findings:**

1. **Send Delay = 0**: No inter-send delay. With Daily/Hourly cap = 500, the system can fire 500 emails in a burst. This is a Gmail deliverability risk and may trigger Gmail's spam filters or account suspension.
2. **Autonomous mode enabled** with **Min Gap = 0 minutes**: Auto-replies fire immediately with no rate limiting beyond the 100/day cap. No cooldown.
3. The warning "replies will be sent without your review" is visible but may not have been read or understood before enabling.
4. IMAP Fetch Interval = 2 minutes — very aggressive polling. Combined with IMAP failure (TimeoutError), this means the scheduler retries IMAP every 2 minutes and fails every time.

**Confidence:** CONFIRMED risk on all four points above.

---

## Image 15 — Settings Surface (Bottom)

**Surface:** Settings  
**Mode indicators:** SMTP_VERIFIED | LIVE  
**Visible data:**
- Groq Keys: empty textarea (cleared after save — correct behavior)
- Gemini Keys: empty textarea (cleared after save — correct behavior)
- AI Model Configuration: Groq Model = llama-3.1-8b-instant, Gemini Model = gemini-2.5-flash
- Follow-up Templates:
  - Template 1: "Brief friendly check-in. Reference the first email. Add one new piece of value - a relevant insight or result. Keep it under 80 words. No hard sell."
  - Template 2: "Polite breakup email. Acknowledge they may be busy. Leave the door open. One sentence offer. Sign off warmly. Under 60 words."
- Suppression & Sending: Blocked Domains = "example.com"
- Send Window Start: 00:00, Send Window End: 23:59, Timezone: Asia/Kolkata
- Dry run: UNCHECKED
- Warm-up Mode: UNCHECKED
- Key fingerprints: 9 total (3 Groq + 6 Gemini) visible at bottom — FINGERPRINTS ONLY, no raw keys

**Key findings:**

1. Secret clearing is working: Groq/Gemini key textareas are empty after save.
2. Send Window 00:00–23:59 = effectively 24 hours. No business-hours restriction.
3. `example.com` is the only blocked domain — minimal suppression protection.
4. Dry run is OFF, Warm-up is OFF. The system sends full volume immediately.
5. Follow-up templates are system prompts (instructions), not actual email copy — `followups/service.py` uses Groq to expand these into actual emails.

**Confidence:** HIGH. All visible data is consistent with a system configured for aggressive live sending.
