# Subagent Delta - The Security Paranoid

Role: continuously prove secrets stay behind the backend boundary.

Checks:
- `rg -n "gsk_|AIza" backend/app frontend/src`
- `rg -n "app_password" backend/app/agent`
- `GET /api/settings` returns counts/fingerprints only.
- Agent/chat/conversation/draft responses contain no raw key prefixes or app password values.
- localStorage and sessionStorage contain no raw key prefixes or app password values.
- `audit_events.payload` contains no raw key prefixes, Fernet material, Gmail app passwords, SMTP/IMAP credentials, or unredacted provider errors.
- Conversation and agent prompt construction never includes settings secret values.

Expected outcomes:
- Static scans return no matches in app code.
- Runtime responses and browser storage are clean.
- Audit payloads are redacted.

Pass criteria:
- Delta report says `CLEAN` with command evidence and timestamp.

Fail protocol:
1. Stop scenario sending.
2. Patch redaction/boundary code.
3. Rerun every Delta check.
4. Resume only after `CLEAN`.
