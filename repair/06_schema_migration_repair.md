# repair/06_schema_migration_repair.md — Schema / Alembic Parity

---

## Current State (CONFIRMED from relation.md and architecture_test.md)

### Active DB: `backend/finimatic.db` — 17 tables
```
agent_sessions, audit_events, campaign_plans, contacts, conversation_messages,
drafts, follow_up_sequences, import_batches, import_rows, pending_email_actions,
provider_health, replies, send_attempts, send_queue, settings, suppressions, templates
```

### Alembic chain
| Migration | File | What it does |
|-----------|------|--------------|
| 0001_initial | `versions/0001_initial.py` | **NO-OP** — upgrade/downgrade both `pass` |
| 0002_agent_tables | `versions/0002_agent_tables.py` | Creates `agent_sessions`, `pending_email_actions` — but MISSING extra columns present in live model |
| 0003_reply_followup_campaigns | `versions/0003_reply_followup_campaigns.py` | Alters replies/drafts/follow-ups, creates `campaign_plans` |

### Runtime schema repair (`session.py`)
`_apply_lightweight_migrations()` adds columns via `ALTER TABLE` at startup.
These columns ARE in `models.py` but NOT in Alembic.

### Known columns in `models.py` NOT in Alembic

| Table | Missing Columns |
|-------|-----------------|
| `agent_sessions` | `context_loaded_at`, `contact_name_map`, `turn_history`, `current_channel` |
| `contacts` | `deleted_at`, `auto_reply_override`, `auto_reply_last_checked` (UNVERIFIED exact names) |
| `drafts` | `sequence_type` (UNVERIFIED) |
| `replies` | `intent`, `raw_body`, `is_archived`, `external_message_id` (per 0003 migration) |
| `follow_up_sequences` | `draft_id` column added in 0003 |
| `campaign_plans` | Entire table (added in 0003) |

---

## Risk Assessment

### Fresh DB via Alembic alone

```bash
alembic upgrade head
```

This will:
1. Run no-op 0001 (no tables created).
2. Create `agent_sessions` (missing 4 columns) and `pending_email_actions` via 0002.
3. Run 0003 — `ALTER TABLE replies ADD COLUMN ...` will FAIL if replies table doesn't exist yet.

**Result**: Alembic head on empty DB likely fails or creates an incomplete schema.
The app will crash at startup when accessing missing columns.

---

## Proposed Fix: Regenerate Alembic from models.py

### Step 1: Freeze current models

The live `models.py` is the source of truth. Do not edit it during this process.

### Step 2: Create a new baseline migration

```bash
cd backend

# Mark current Alembic as having a known broken head
# Create a single new migration from models.py autogenerate

alembic revision --autogenerate -m "0004_full_schema_parity"
```

This should detect all missing tables and columns by comparing `models.py` against
the Alembic schema state.

### Step 3: Verify the migration

```bash
# Create a fresh SQLite DB
DATABASE_URL=sqlite+aiosqlite:///./test_fresh.db alembic upgrade head

# Check tables and columns
python -c "
from sqlalchemy import create_engine, inspect
engine = create_engine('sqlite:///./test_fresh.db')
insp = inspect(engine)
for t in sorted(insp.get_table_names()):
    cols = [c['name'] for c in insp.get_columns(t)]
    print(t, '->', sorted(cols))
"
```

Compare output against `models.py` column definitions.

### Step 4: Remove startup lightweight migrations

Once Alembic encodes full schema, `_apply_lightweight_migrations()` in `session.py`
should be reduced to just `Base.metadata.create_all(engine)` for truly new DBs,
with Alembic handling all additions from that point.

Or, keep startup `create_all` but ALSO have a valid Alembic chain so production
deployments can use either path.

### Step 5: Add migration parity test

```python
# backend/tests/test_schema_migration.py

async def test_alembic_matches_models():
    """
    Run alembic upgrade head on fresh DB, then compare table/column list
    to what models.py declares. Fail if any column is missing.
    """
    import subprocess
    import os
    
    test_db = "test_alembic_parity.db"
    env = {**os.environ, "DATABASE_URL": f"sqlite:///./{test_db}"}
    
    result = subprocess.run(
        ["alembic", "upgrade", "head"],
        capture_output=True, text=True, env=env
    )
    assert result.returncode == 0, f"Alembic failed: {result.stderr}"
    
    # Check all expected tables exist
    from sqlalchemy import create_engine, inspect
    engine = create_engine(f"sqlite:///./{test_db}")
    insp = inspect(engine)
    tables = insp.get_table_names()
    
    expected_tables = [
        "agent_sessions", "audit_events", "campaign_plans", "contacts",
        "conversation_messages", "drafts", "follow_up_sequences",
        "import_batches", "import_rows", "pending_email_actions",
        "provider_health", "replies", "send_attempts", "send_queue",
        "settings", "suppressions", "templates"
    ]
    for table in expected_tables:
        assert table in tables, f"Table {table} missing from Alembic schema"
    
    os.unlink(test_db)
```

---

## Stale Documentation Fix

| Document | Status | Action |
|----------|--------|--------|
| `SCHEMA.md` | STALE — missing 5+ tables | Regenerate from models.py |
| `PROJECT_IMPLEMENTATION_REPORT.md` | STALE — missing agent/campaign/auto-reply routes | Add note: "snapshot as of initial build; current source has more features" |
| `DATA_FLOW.md` | PARTIALLY STALE — missing new routes | Update file structure section |
| `STACK.md` | `google-generativeai` → should be `google-genai` | Update SDK name |

### Generating current schema doc

```bash
python -c "
from backend.app.db.models import Base
for table in Base.metadata.sorted_tables:
    print(f'## {table.name}')
    for col in table.columns:
        nullable = '' if col.nullable else ' NOT NULL'
        default = f' DEFAULT {col.default.arg}' if col.default and hasattr(col.default, 'arg') else ''
        print(f'  {col.name}: {col.type}{nullable}{default}')
    print()
"
```
