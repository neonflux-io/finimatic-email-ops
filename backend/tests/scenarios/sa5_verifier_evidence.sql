-- SUBAGENT 5 verifier evidence SQL.
-- Run from repo root:
--   sqlite3 backend/finimatic.db ".read backend/tests/scenarios/sa5_verifier_evidence.sql"
--
-- These queries intentionally avoid settings.value, message bodies, SMTP responses,
-- provider keys, and app-password fields.

.headers on
.mode column

-- 1. Last outbound conversation email per contact.
WITH ranked_outbound AS (
  SELECT
    cm.contact_id,
    cm.subject,
    cm.source,
    cm.auto_sent,
    cm.external_message_id,
    cm.occurred_at,
    cm.created_at,
    ROW_NUMBER() OVER (
      PARTITION BY cm.contact_id
      ORDER BY cm.occurred_at DESC, cm.created_at DESC
    ) AS rn
  FROM conversation_messages cm
  WHERE cm.direction = 'outbound'
)
SELECT
  c.id AS contact_id,
  substr(c.email, 1, 2) || '***@' ||
    CASE WHEN instr(c.email, '@') > 0 THEN substr(c.email, instr(c.email, '@') + 1) ELSE 'unknown' END AS masked_email,
  c.status AS contact_status,
  ro.occurred_at,
  ro.source,
  ro.auto_sent,
  substr(coalesce(ro.subject, ''), 1, 120) AS subject_preview,
  CASE WHEN ro.external_message_id IS NULL OR ro.external_message_id = '' THEN 0 ELSE 1 END AS has_external_message_id
FROM ranked_outbound ro
JOIN contacts c ON c.id = ro.contact_id
WHERE ro.rn = 1
ORDER BY ro.occurred_at DESC;

-- 2. Auto-reply audit activity summary.
SELECT
  event_type,
  COUNT(*) AS count,
  MAX(created_at) AS last_seen
FROM audit_events
WHERE event_type LIKE 'auto_reply.%'
GROUP BY event_type
ORDER BY last_seen DESC;

-- 3. Latest auto-reply audit events, payload kept because audit service redacts secret-key fields.
SELECT
  created_at,
  event_type,
  entity_type,
  entity_id,
  payload
FROM audit_events
WHERE event_type LIKE 'auto_reply.%'
ORDER BY created_at DESC
LIMIT 25;

-- 4. Provider health rows.
SELECT
  provider,
  status,
  last_checked,
  error_code,
  details
FROM provider_health
ORDER BY provider ASC;

-- 5. Queue policy state summary by status/reason blob.
SELECT
  status,
  coalesce(policy_block_reasons, '[]') AS policy_block_reasons,
  COUNT(*) AS count,
  MAX(created_at) AS newest_queue_row
FROM send_queue
GROUP BY status, coalesce(policy_block_reasons, '[]')
ORDER BY newest_queue_row DESC;

-- 6. Latest queue policy audit decisions.
SELECT
  created_at,
  event_type,
  entity_id AS queue_id,
  payload
FROM audit_events
WHERE event_type IN ('queue.policy_evaluated', 'queue.gate_blocked', 'send.dry_run_blocked')
ORDER BY created_at DESC
LIMIT 40;

