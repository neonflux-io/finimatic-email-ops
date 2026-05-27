# Subagent Beta - The Feature Torturer

Role: push every feature through edge conditions until no 500s, stuck UI states, or inconsistent DB writes remain.

Edge cases:
- Empty fields, null fields, missing settings, zero AI keys, expired agent sessions, corrupted JSON, malformed AI output, 10,000-character inputs, Unicode and emoji subjects.
- Contacts with identical names, duplicate plus-addresses, two campaigns running simultaneously, daily cap exactly `1`, bulk draft generation while queue processing, IMAP fetch while conversation send is in flight, provider 429 during generation.

Expected outcomes:
- Every API returns structured success or structured 4xx/5xx error with redacted detail.
- No UI button stays loading after failure.
- Bulk jobs remain idempotent and resumable.
- Queue/policy/audit state remains consistent after concurrent operations.
- Malformed AI output creates an unapproved fallback draft or clear failure without sending.

Pass criteria:
- No unhandled exception trace in API responses.
- No raw secret in logs, network responses, localStorage, sessionStorage, or audit payloads.
- Regression tests cover each fixed bug.

Fail protocol:
1. Preserve the failing input.
2. Identify root cause, not the surface symptom.
3. Patch the smallest owning module.
4. Run full backend tests and frontend build.
5. Add or update a regression test.
6. Rerun the edge case and then the complete persona round.
