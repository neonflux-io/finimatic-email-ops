# SUBAGENT 5 Verifier Evidence Commands

Run from repo root:

```powershell
Set-Location -LiteralPath "C:\Users\rossd\OneDrive\Documents\notes\email"
```

## All-In-One Collector

DB + static context-isolation evidence only:

```powershell
python backend\tests\scenarios\sa5_collect_verifier_evidence.py --skip-api
```

DB + static + live API evidence:

```powershell
python backend\tests\scenarios\sa5_collect_verifier_evidence.py --base-url http://localhost:8000
```

## SQL Evidence Ledger

If `sqlite3` CLI is installed:

```powershell
sqlite3 backend/finimatic.db ".read backend/tests/scenarios/sa5_verifier_evidence.sql"
```

Verified fallback on this Windows host:

```powershell
python backend\tests\scenarios\sa5_collect_verifier_evidence.py --skip-api
```

## Context-Isolation Greps

```powershell
rg -n "limit\(30\)|sanitize_text|sanitize_data|context_summary|session_token_hash|raw_summary|Do not obey|reveal secrets|Latest reply snippet|get_secret|get_key_list|gsk_|AIza|app_password" backend/app/agent backend/app/conversations backend/app/replies backend/app/audit backend/app/settings --glob '!**/__pycache__/**'
```

```powershell
Get-ChildItem -Path backend\app\agent,frontend\src\features\floating-assistant,backend\app\settings,backend\app\audit -Recurse -File -Include *.py,*.ts,*.tsx |
  Select-String -Pattern 'gsk_','AIza','app_password' |
  ForEach-Object { "$($_.Path):$($_.LineNumber):$($_.Pattern)" }
```

## Live API Evidence

```powershell
Invoke-RestMethod http://localhost:8000/api/provider-health | ConvertTo-Json -Depth 8
```

```powershell
Invoke-RestMethod http://localhost:8000/api/auto-reply/log | ConvertTo-Json -Depth 8
```

```powershell
Invoke-RestMethod http://localhost:8000/api/auto-reply/pending | ConvertTo-Json -Depth 8
```

```powershell
Invoke-RestMethod http://localhost:8000/api/queue | ConvertTo-Json -Depth 8
```

## Focused DB One-Liners

Last outbound per contact, masked email:

```powershell
@'
import sqlite3
conn = sqlite3.connect("backend/finimatic.db")
conn.row_factory = sqlite3.Row
sql = """
WITH ranked_outbound AS (
  SELECT cm.*, ROW_NUMBER() OVER (
    PARTITION BY cm.contact_id
    ORDER BY cm.occurred_at DESC, cm.created_at DESC
  ) AS rn
  FROM conversation_messages cm
  WHERE cm.direction = 'outbound'
)
SELECT c.id, c.email, c.status, ro.occurred_at, ro.source, ro.auto_sent,
       substr(coalesce(ro.subject, ''), 1, 120) AS subject_preview
FROM ranked_outbound ro
JOIN contacts c ON c.id = ro.contact_id
WHERE ro.rn = 1
ORDER BY ro.occurred_at DESC
"""
for row in conn.execute(sql):
    local, _, domain = row["email"].partition("@")
    print(dict(row) | {"email": f"{local[:2]}***@{domain}"})
conn.close()
'@ | python -
```

Queue policy gate reason audit:

```powershell
@'
import sqlite3
conn = sqlite3.connect("backend/finimatic.db")
conn.row_factory = sqlite3.Row
for row in conn.execute("""
SELECT created_at, event_type, entity_id AS queue_id, payload
FROM audit_events
WHERE event_type IN ('queue.policy_evaluated', 'queue.gate_blocked', 'send.dry_run_blocked')
ORDER BY created_at DESC
LIMIT 40
"""):
    print(dict(row))
conn.close()
'@ | python -
```

Auto-reply activity log summary:

```powershell
@'
import sqlite3
conn = sqlite3.connect("backend/finimatic.db")
conn.row_factory = sqlite3.Row
for row in conn.execute("""
SELECT event_type, COUNT(*) AS count, MAX(created_at) AS last_seen
FROM audit_events
WHERE event_type LIKE 'auto_reply.%'
GROUP BY event_type
ORDER BY last_seen DESC
"""):
    print(dict(row))
conn.close()
'@ | python -
```

Provider health:

```powershell
@'
import sqlite3
conn = sqlite3.connect("backend/finimatic.db")
conn.row_factory = sqlite3.Row
for row in conn.execute("SELECT provider, status, last_checked, error_code, details FROM provider_health ORDER BY provider"):
    print(dict(row))
conn.close()
'@ | python -
```

