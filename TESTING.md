# Finimatic — Rigorous Testing Protocol

## Authority & Scope

The Codex agent has full authority to:
- Send as many test emails as needed from the configured sender account
- Open, read, and inspect both the sender inbox and the recipient inbox using the Codex browser extension
- Paste all credentials from KEYS.md into the Settings UI and test each
- Generate AI drafts using all configured Groq and Gemini keys
- Rotate through all provided keys to test pooling, cooldown, and fallback
- Repeat any test case until it passes with reproducible evidence
- Mark a test BLOCKED (not PASS) if browser evidence is unavailable for that step

Do not stop at the first pass. Run every test case to completion.

---

## Pre-Test Setup (execute before any test case)

1. Read KEYS.md. Load all credentials.
2. Open Finimatic Settings UI in browser.
3. Paste GMAIL_USER into Gmail User field.
4. Paste GMAIL_APP_PASSWORD into App Password field (type=password).
5. Click "Save & Verify SMTP". Confirm sender_readiness = smtp_verified.
6. Paste all GROQ_KEYS (one per line) into Groq Keys field. Save.
7. Paste all GEMINI_KEYS (one per line) into Gemini Keys field. Save.
8. Confirm Settings page shows: Groq key count, Gemini key count, fingerprints — no raw keys.
9. Open both browser profiles:
   - Sender profile: logged into GMAIL_USER (rossdmello869@gmail.com)
   - Recipient profile: logged into REPORT_RECIPIENT (crce.9955.ce@gmail.com)

---

## TEST SUITE A — Sender Setup & SMTP Verification

A1: SMTP verify with correct credentials → readiness = smtp_verified ✓
A2: SMTP verify with wrong password → readiness = failed, redacted error shown ✓
A3: GET /api/settings response contains ZERO raw secrets — only fingerprints and counts ✓
A4: Fernet-decrypted value accessible to backend service but never returned via API ✓

---

## TEST SUITE B — Canary Send (end-to-end with browser inbox verification)

B1: Click "Test Send" → confirmation modal shows REPORT_RECIPIENT address → operator confirms
B2: POST /api/canary/send → response includes { nonce, sent_at, sender_identity, status: "success" }
B3: Open sender browser profile → Gmail Sent folder → confirm nonce email appears with correct subject
B4: Open recipient browser profile → Gmail Inbox → confirm nonce email received, subject matches
B5: Retry canary immediately → second POST returns { status: "duplicate_blocked" } → NO second email in recipient inbox
B6: Confirm audit log shows: canary.attempt + canary.success events
B7: Confirm Settings shows canary_verified = true after B2

---

## TEST SUITE C — Contact Import

C1: Upload a CSV with 5 valid contacts → preview shows 5 accepted rows
C2: Include one row with invalid email → row shows invalid_email
C3: Include one duplicate email (already in DB) → row shows duplicate
C4: Include one email that is in suppressions → row shows suppressed
C5: Include one row missing business_name and creator_name → row shows missing_field
C6: Commit batch → contacts appear in Contacts surface with status=imported
C7: Re-commit same batch → duplicate/suppressed counts updated, no new contacts created (replay-safe)
C8: Manual entry: fill form with single contact → submitted → appears in Contacts surface

---

## TEST SUITE D — AI Draft Generation (test all providers, all keys)

D1: Select contact → "Generate Draft" → provider=Groq → draft appears with subject+body+warnings
D2: Edit subject and body manually → save → confirm edited content persisted
D3: "Generate Draft" → provider=Gemini → draft appears with subject+body+warnings
D4: Provider=auto → draft appears from whichever provider responds first
D5: Rewrite draft → tone=casual → body changes, warnings updated
D6: Revoke all Groq keys temporarily (set to invalid) → "Generate Draft" Groq → shows AIFailure + error_code, fallback to empty draft, manual draft still creatable
D7: Confirm no raw API key appears in console, network tab, audit log, or UI
D8: Malformed AI output (inject via test endpoint or mock) → AIFailure, audit event(draft.ai_failed), UI shows actionable error
D9: After D6, restore keys → Groq drafts work again

---

## TEST SUITE E — Policy Gates (each gate tested independently)

For each test: create a draft, set up the blocking condition, attempt to send, confirm blocked with correct reason_code.

E1: draft_approved=false → DRAFT_NOT_APPROVED
E2: canary_verified=false → CANARY_NOT_VERIFIED
E3: email in suppressions → RECIPIENT_SUPPRESSED
E4: contact.status=manually_paused → RECIPIENT_MANUALLY_PAUSED
E5: contact.status=replied → RECIPIENT_REPLIED
E6: bounce record exists → RECIPIENT_BOUNCED
E7: daily sends >= daily_send_cap → DAILY_CAP_EXCEEDED
E8: hourly sends >= hourly_send_cap → HOURLY_CAP_EXCEEDED
E9: idempotency_key already in sent_attempts → IDEMPOTENCY_DUPLICATE

For each: confirm queue entry shows status=blocked + correct policy_block_reasons in UI.

---

## TEST SUITE F — Full Live Send (to REPORT_RECIPIENT)

F1: Import REPORT_RECIPIENT as a contact with creator_name="Test Recipient" source="manual"
F2: Generate AI draft (use Groq) — personalize with "This is a Finimatic live send test"
F3: Review warnings, edit subject to include a timestamp for uniqueness
F4: Click Approve → contact.status = approved
F5: Queue entry created → background worker picks it up
F6: Confirm send attempt recorded: status=success, provider_msg_id present
F7: Open sender browser profile → Gmail Sent → confirm email present
F8: Open recipient browser profile → Gmail Inbox → confirm email received with exact subject
F9: Confirm audit_event(send.success) in Audit Logs surface
F10: Confirm contact.status = sent

---

## TEST SUITE G — Follow-up Sequences

G1: Set followup_interval_days=1, max_followups=2 in Settings
G2: After F10 (contact=sent), confirm follow_up_sequences entry created with due_at = sent_at + 1 day
G3: Manually set due_at to now()-5min via test endpoint or direct DB edit
G4: APScheduler fires → follow-up draft created → sent → confirm in recipient inbox
G5: Mark contact as replied (manual stop) → second follow-up → status=stopped, stop_reason=RECIPIENT_REPLIED
G6: Confirm audit_event(followup.stopped) in Audit Logs

---

## TEST SUITE H — Dry-Run Mode

H1: Toggle dry_run=true in Settings
H2: Approve a draft → queue entry created
H3: Worker processes → status=skipped, audit_event(send.dry_run_blocked)
H4: Open recipient inbox → NO new email received
H5: Toggle dry_run=false → Mode label switches DRY-RUN → LIVE
H6: Same queue entry: worker retries → sends successfully → F7/F8 verification

---

## TEST SUITE I — Groq Key Pool Stress (multi-key rotation)

Requires ≥2 Groq keys in KEYS.md.

I1: Trigger 5 concurrent AI draft requests → confirm all 5 complete (LRU rotation across keys)
I2: Force-cooldown one key (inject 429 response or remove it) → remaining keys serve the requests
I3: Remove all Groq keys → trigger draft → model_unavailable_rate_limited returned, UI shows error, manual draft unblocked
I4: Confirm no raw key appears in any error message or audit payload throughout I1–I3

---

## TEST SUITE J — Security Scan

J1: Search entire codebase for the app password string → 0 matches
J2: Search all test files and fixtures for raw API key patterns (gsk_, AIza) → 0 matches
J3: Check browser network tab during Settings save → response body contains 0 raw secrets
J4: Check browser localStorage and sessionStorage → 0 secret values stored
J5: Check console logs during any send → 0 raw credentials printed
J6: Confirm .env is listed in .gitignore and not committed

---

## Scoring

Every test case gets one verdict:
- PASS: evidence from code + browser confirms expected behavior
- FAIL: behavior wrong — give exact case, expected, actual, trace, fix applied
- BLOCKED: external dependency (Gmail rate limit, provider outage) prevented truthful verdict — document smallest next action

Report must include browser screenshots or transcript for: B3, B4, B5, F7, F8, H4.

Final verdict is NOT COMPLETE until:
- All A–J suites have no FAIL
- B3+B4 (canary inbox proof) and F7+F8 (live send inbox proof) are PASS with browser evidence
- J1–J6 are all clean
