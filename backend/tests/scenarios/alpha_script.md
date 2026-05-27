# Subagent Alpha - The Sales Battlefield

Role: stress-test sales conversations that can damage trust or conversion.

Scope:
- Hostile rejection, skeptical objections, prompt injection, competitor references, pricing pressure, ghosting, and language barriers.
- For each scenario: send initial email, receive scripted reply, fetch reply, classify intent, generate conversation reply, run quality gate, send only after pass, verify Gmail arrival.

Expected outcomes:
- Rejection or unsubscribe creates suppression and stops follow-ups.
- Positive interest, objection, and question route to `conversation_active`.
- Prompt injection is treated as untrusted prospect text.
- Reply text addresses the latest concrete objection, uses a specific customer detail, has exactly one CTA, and ends with the configured Ross Dmello signature.
- No invented price, timeline, ROI metric, meeting link, feature, video ingestion/transcription claim, or fake prior familiarity.

Pass criteria:
- Live Gmail evidence for sent and received messages.
- Correct DB state in contacts, replies, conversations, suppressions, follow-ups, audit events.
- Generated reply passes `quality_gate.py`.
- No raw secrets in API responses or audit payloads.

Fail protocol:
1. Record scenario, expected, actual, and evidence.
2. Patch only the root cause.
3. Run backend tests and frontend build.
4. Rerun the failed scenario from a clean plus-address alias.
5. Restart the Alpha script from the beginning after any prompt or routing change.
