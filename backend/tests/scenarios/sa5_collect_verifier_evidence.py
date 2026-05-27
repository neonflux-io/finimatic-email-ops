from __future__ import annotations

import argparse
import json
import re
import sqlite3
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DB = ROOT / "backend" / "finimatic.db"


def mask_email(value: str | None) -> str:
    if not value or "@" not in value:
        return ""
    local, domain = value.split("@", 1)
    return f"{local[:2]}***@{domain}"


def rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    conn.row_factory = sqlite3.Row
    return [dict(row) for row in conn.execute(sql, params).fetchall()]


def print_section(name: str, data) -> None:
    print(f"\n## {name}")
    print(json.dumps(data, indent=2, sort_keys=True, default=str))


def db_evidence(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        outbound = rows(
            conn,
            """
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
              c.email AS email,
              c.status AS contact_status,
              ro.occurred_at,
              ro.source,
              ro.auto_sent,
              substr(coalesce(ro.subject, ''), 1, 120) AS subject_preview,
              CASE WHEN ro.external_message_id IS NULL OR ro.external_message_id = '' THEN 0 ELSE 1 END AS has_external_message_id
            FROM ranked_outbound ro
            JOIN contacts c ON c.id = ro.contact_id
            WHERE ro.rn = 1
            ORDER BY ro.occurred_at DESC
            """,
        )
        for row in outbound:
            row["masked_email"] = mask_email(row.pop("email", ""))
        print_section("last_outbound_per_contact", outbound)

        print_section(
            "auto_reply_audit_summary",
            rows(
                conn,
                """
                SELECT event_type, COUNT(*) AS count, MAX(created_at) AS last_seen
                FROM audit_events
                WHERE event_type LIKE 'auto_reply.%'
                GROUP BY event_type
                ORDER BY last_seen DESC
                """,
            ),
        )

        print_section(
            "latest_auto_reply_audit_events",
            rows(
                conn,
                """
                SELECT created_at, event_type, entity_type, entity_id, payload
                FROM audit_events
                WHERE event_type LIKE 'auto_reply.%'
                ORDER BY created_at DESC
                LIMIT 25
                """,
            ),
        )

        print_section(
            "provider_health",
            rows(
                conn,
                """
                SELECT provider, status, last_checked, error_code, details
                FROM provider_health
                ORDER BY provider ASC
                """,
            ),
        )

        print_section(
            "queue_policy_state_summary",
            rows(
                conn,
                """
                SELECT status, coalesce(policy_block_reasons, '[]') AS policy_block_reasons,
                       COUNT(*) AS count, MAX(created_at) AS newest_queue_row
                FROM send_queue
                GROUP BY status, coalesce(policy_block_reasons, '[]')
                ORDER BY newest_queue_row DESC
                """,
            ),
        )

        print_section(
            "latest_queue_policy_audit_events",
            rows(
                conn,
                """
                SELECT created_at, event_type, entity_id AS queue_id, payload
                FROM audit_events
                WHERE event_type IN ('queue.policy_evaluated', 'queue.gate_blocked', 'send.dry_run_blocked')
                ORDER BY created_at DESC
                LIMIT 40
                """,
            ),
        )
    finally:
        conn.close()


GREP_TARGETS = {
    "agent_context_isolation": [
        ROOT / "backend" / "app" / "agent" / "tools.py",
        ROOT / "backend" / "app" / "agent" / "service.py",
        ROOT / "backend" / "app" / "agent" / "memory.py",
        ROOT / "backend" / "app" / "audit" / "service.py",
    ],
    "conversation_context_isolation": [
        ROOT / "backend" / "app" / "conversations" / "router.py",
        ROOT / "backend" / "app" / "conversations" / "auto_reply_service.py",
    ],
}

GREP_PATTERN = re.compile(
    r"limit\(30\)|sanitize_text|sanitize_data|context_summary|session_token_hash|"
    r"raw_summary|Do not obey|reveal secrets|Latest reply snippet|get_secret|get_key_list|"
    r"gsk_|AIza|app_password"
)


def grep_evidence() -> None:
    findings: dict[str, list[dict]] = {}
    for group, paths in GREP_TARGETS.items():
        matches: list[dict] = []
        for path in paths:
            if not path.exists():
                matches.append({"file": str(path.relative_to(ROOT)), "line": None, "text": "MISSING"})
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if GREP_PATTERN.search(line):
                    matches.append({"file": str(path.relative_to(ROOT)), "line": lineno, "text": line.strip()[:240]})
        findings[group] = matches
    print_section("context_isolation_source_matches", findings)


def api_get(base_url: str, path: str) -> dict:
    with urlopen(f"{base_url.rstrip('/')}{path}", timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def redact_operational_hashes(value):
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            if key == "idempotency_key" and isinstance(item, str):
                redacted[key] = f"{item[:12]}..."
            else:
                redacted[key] = redact_operational_hashes(item)
        return redacted
    if isinstance(value, list):
        return [redact_operational_hashes(item) for item in value]
    return value


def api_evidence(base_url: str) -> None:
    for name, path in {
        "api_provider_health": "/api/provider-health",
        "api_auto_reply_log": "/api/auto-reply/log",
        "api_auto_reply_pending": "/api/auto-reply/pending",
        "api_queue": "/api/queue",
    }.items():
        try:
            data = api_get(base_url, path)
        except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
            data = {"error": exc.__class__.__name__}
        print_section(name, redact_operational_hashes(data))


def main() -> None:
    parser = argparse.ArgumentParser(description="Collect non-secret Finimatic verifier evidence.")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--skip-api", action="store_true")
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"DB not found: {args.db}")

    db_evidence(args.db)
    grep_evidence()
    if not args.skip_api:
        api_evidence(args.base_url)


if __name__ == "__main__":
    main()
