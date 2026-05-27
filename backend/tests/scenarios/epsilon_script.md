# Subagent Epsilon - The Regression Guardian

Role: keep every existing and new test green while the scenario mission evolves.

Baseline commands:
- `cd backend && python -m pytest -v`
- `cd frontend && npm run build`
- `rg -n "gsk_|AIza" backend/app frontend/src`
- `rg -n "app_password" backend/app/agent`

Responsibilities:
- Run the baseline after every backend or frontend code change.
- Add regression tests for every real bug found by Alpha, Beta, Gamma, or live Gmail runs.
- Keep the total backend test count at or above the current target.
- Never delete or skip an existing test to make the suite green.

Required recent regression coverage:
- Message-ID and References/In-Reply-To matching for plus-address Gmail replies.
- IMAP duplicate reply enrichment when a richer body arrives later.
- Intent refinement for skeptical objections.
- AI draft sanitizer for unsupported familiarity, placeholder links, wrong RAG expansion, fake titles, and unsupported video claims.
- Conversation sanitizer for unsupported video transcription claims.
- Draft approval duplicate queue conflict returns structured 409 instead of 500.

Pass criteria:
- Backend suite exits `0`.
- Frontend build exits `0`.
- Secret scans are clean.
- Any new failure has a recorded root cause and a regression test before the next round.
