# Finimatic Repair Plan — Executive Summary

Generated: 2026-05-26  
Scope: Evidence-grounded repair plan derived from 15 screenshots, 4 evidence files,
       and project source documentation.  
Source priority: live `backend/app` + `frontend/src` > tests > models.py+session.py > Alembic > root docs.

---

## Severity-Ranked Issue Register

| ID | Title | Sev | Status | Surface |
|----|-------|-----|--------|---------|
| R-01 | Alembic does not rebuild live schema — `0001_initial.py` is no-op | P0 | CONFIRMED | DB/Deploy |
| R-02 | Queue processing mode ambiguous — background loop + manual button both exist; UI shows "queued" not "sent" | P0 | CONFIRMED | Queue |
| R-03 | Multiple send paths have divergent policy gates — conversation, auto-reply, agent bypass queue policy | P0 | CONFIRMED | All send paths |
| R-04 | Auto-Reply is in `Autonomous send` mode — sends without per-message approval, contradicts original AI-suggestion-only contract | P0 | CONFIRMED | Auto-Reply |
| R-05 | IMAP fetch is synchronous on scheduler thread — confirmed failed with TimeoutError, blocks reply/follow-up/auto-reply pipelines | P1 | CONFIRMED | Replies/IMAP |
| R-06 | Import preview stored in process-local memory — backend restart between preview and commit silently loses rows | P1 | CONFIRMED | Import |
| R-07 | Conversation GET routes commit backfill writes — loading page is a DB mutation | P1 | CONFIRMED | Conversations |
| R-08 | Draft "Approve Follow-up #2" path unclear — UI shows follow-up approval as same workflow as initial approval; user confused about what gets queued | P1 | CONFIRMED | Drafts/Follow-ups |
| R-09 | Send Delay = 0, Daily Cap = 500, Hourly Cap = 500 — settings allow unlimited rapid fire; warm-up not enabled | P1 | CONFIRMED | Settings/Queue |
| R-10 | Policy block reasons not surfaced in Queue UI — BLOCKS column is empty in queue table; user cannot see why email stalled | P1 | CONFIRMED | Queue UI |
| R-11 | Contact deleted-at check missing in conversation/auto-reply/agent send paths | P1 | RISK | Send paths |
| R-12 | AssistantWidget stores pending action metadata in localStorage — action_id, draft_id, contact_id retained across reloads | P2 | CONFIRMED | Agent/Frontend |
| R-13 | `datetime.utcnow()` deprecation warnings in agent context/campaign code | P2 | CONFIRMED | Agent/Campaign |
| R-14 | AssistantWidget accepts file attachments but sends metadata only — misleading UX | P2 | CONFIRMED | Agent/Frontend |
| R-15 | AssistantWidget z-index 80 overlays app modal z-index 40 | P2 | CONFIRMED | Frontend CSS |
| R-16 | Voice transcript interim segments can duplicate text | P2 | RISK | AssistantWidget |
| R-17 | `SCHEMA.md`, `PROJECT_IMPLEMENTATION_REPORT.md`, `DATA_FLOW.md` stale — missing agent/campaign/auto-reply tables | P2 | CONFIRMED | Docs |
| R-18 | `STACK.md` lists `google-generativeai`; requirements.txt uses `google-genai` | P2 | CONFIRMED | Docs/Setup |
| R-19 | Subject variant and campaign enrichment use first Groq key directly, not LRU pool | P2 | RISK | AI |
| R-20 | Bulk draft job state held in in-memory global dict — lost on restart | P3 | CONFIRMED | Drafts |

---

## Implementation Order

### Phase 1 — Safety stops (P0, must do before next live send batch)

1. **R-04** — Flip Auto-Reply to `Approval required` mode in Settings, or add hard gate documentation confirming autonomous mode is intentional.
2. **R-02** — Add explicit "PROCESSING" badge to queue entries and clarify queue worker state in UI.
3. **R-03** — Extract shared `engaged_send_gates()` function; call from conversation router, auto-reply service, and agent tools.
4. **R-10** — Surface `policy_block_reasons` in Queue UI BLOCKS column (column exists but appears empty).

### Phase 2 — Reliability (P1, within 1 sprint)

5. **R-06** — Persist import preview in `import_batches` table with `status=preview`; commit promotes rows.
6. **R-05** — Wrap all `imaplib` calls in `asyncio.get_event_loop().run_in_executor(None, ...)`.
7. **R-07** — Move conversation GET backfill into an explicit `/api/conversations/{id}/backfill` POST.
8. **R-08** — Add separate toast wording for follow-up approval vs. initial approval; show queue entry sequence number in confirmation.
9. **R-09** — Add settings validation: warn if `send_delay_s < 30` and `dry_run=false`; add minimum warm-up recommendation.
10. **R-11** — Add `contact.deleted_at IS NULL` check to `_engaged_send_block_reasons` in conversations, auto-reply, and agent tools.
11. **R-01** — Generate Alembic migration from current `models.py`; stop treating startup `create_all` as the only schema path.

### Phase 3 — UX and hygiene (P2/P3)

12. **R-12** — Replace localStorage pending metadata with backend-only lookup via `/api/agent/confirm` status endpoint.
13. **R-13** — Replace all `datetime.utcnow()` with `core/time.py:utcnow()`.
14. **R-14** — Show "Attachment content is not processed — only filename and type sent to assistant" notice.
15. **R-15** — Raise modal z-index to 90 or hide assistant when modal is open.
16. **R-16** — Fix voice transcript duplicate by tracking `resultIndex`.
17. **R-17/R-18** — Regenerate schema doc from `models.py`; fix stack doc dependency name.
18. **R-19** — Route subject variant and campaign enrichment through `groq_pool.acquire()`.
19. **R-20** — Persist bulk draft job state in a `bulk_draft_jobs` DB table.

---

## Acceptance Criteria

| ID | Acceptance Test |
|----|----------------|
| R-01 | `alembic upgrade head` on empty DB produces schema identical to `models.py` |
| R-02 | Queue UI shows distinct status: pending / processing / sent / blocked / skipped |
| R-03 | Single `evaluate_engaged_send_gates()` function called by 3 direct-send paths |
| R-04 | Auto-reply autonomous sends require explicit operator confirmation or clearly documented consent flow |
| R-05 | IMAP fetch runs in executor; `TimeoutError` records `provider_health` failure and emits audit without blocking scheduler loop |
| R-06 | Backend restart between preview and commit does not lose preview rows |
| R-07 | `GET /api/conversations` and `GET /api/conversations/{id}` never write to DB |
| R-08 | Toast messages distinguish initial cold-send approval from follow-up approval |
| R-09 | Save settings with `send_delay_s=0` returns a warning, not silent acceptance |
| R-10 | Queue table BLOCKS column shows reason codes when present |
| R-11 | Attempt to send to soft-deleted contact via conversation/auto-reply/agent returns `CONTACT_DELETED` block |

---

## Verification Commands

```powershell
# Backend tests (must stay at 182+ passed)
cd C:\Users\rossd\OneDrive\Documents\notes\email\backend
python -m pytest -v

# Frontend build
cd C:\Users\rossd\OneDrive\Documents\notes\email\frontend
npm run build

# Schema parity check (after R-01 fix)
alembic upgrade head
python -c "
from app.db.models import Base
from sqlalchemy import create_engine, inspect
engine = create_engine('sqlite:///./finimatic_fresh.db')
Base.metadata.create_all(engine)
insp = inspect(engine)
for t in sorted(insp.get_table_names()):
    cols = [c['name'] for c in insp.get_columns(t)]
    print(t, cols)
"

# Provider health check (non-mutating)
curl http://localhost:8000/api/provider-health

# Queue state check (non-mutating)
curl http://localhost:8000/api/queue | python -m json.tool | grep -E '"status"|"policy_block_reasons"'
```

---

## Files Produced

- `repair/01_image_evidence.md` — per-image analysis
- `repair/02_workflow_failure_map.md` — user failures mapped to source
- `repair/03_send_policy_unification.md` — send path comparison and consolidation plan
- `repair/04_import_contact_repair.md` — import commit/preview repair
- `repair/05_queue_followup_repair.md` — queue lifecycle repair
- `repair/06_schema_migration_repair.md` — Alembic parity plan
- `repair/07_security_and_secret_review.md` — secret/send confirmation audit
- `repair/08_coding_agent_prompt.md` — paste-ready coding agent prompt
- `repair/09_test_plan.md` — test suite extensions
