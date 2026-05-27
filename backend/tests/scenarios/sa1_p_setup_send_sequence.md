# SA1 P-SETUP Send Sequence

Scope: SUBAGENT 1 support only. These commands do not require Chrome control.

Base URL:

```powershell
$Base = "http://localhost:8000"
```

## 1. Read settings and confirm live send readiness

```powershell
$settings = Invoke-RestMethod -Uri "$Base/api/settings" -Method Get
$settings | Select-Object mode,canary_verified,dry_run,groq_keys_count,gemini_keys_count,auto_reply_enabled,auto_reply_mode
```

Required before live send:

- `mode = LIVE`
- `canary_verified = True`
- `dry_run = False`
- `groq_keys_count > 0`
- `gemini_keys_count > 0`

## 2. Optional test-session settings

```powershell
Invoke-RestMethod -Uri "$Base/api/settings" -Method Post -ContentType "application/json" -Body (@{
  auto_reply_enabled = $true
  auto_reply_mode = "propose"
  imap_fetch_interval_minutes = 2
} | ConvertTo-Json)
```

## 3. Resolve or create dual-account contacts

```powershell
function Get-FinContact($email) {
  $contacts = (Invoke-RestMethod -Uri "$Base/api/contacts" -Method Get).items
  $contacts | Where-Object { $_.email -eq $email } | Select-Object -First 1
}

function Ensure-FinContact($payload) {
  $existing = Get-FinContact $payload.email
  if ($existing) { return $existing }
  Invoke-RestMethod -Uri "$Base/api/contacts" -Method Post -ContentType "application/json" -Body ($payload | ConvertTo-Json -Depth 6)
}

$contactA = Ensure-FinContact @{
  email = "rossdmello896@gmail.com"
  creator_name = "Data Science Educator"
  website_url = "rossdmello896courses.com"
  notes = "Udemy Python/DS instructor, 8000 students, technical audience"
  tags = "udemy-creator,educator,technical"
  source = "manual"
}

$contactB = Ensure-FinContact @{
  email = "crce.9955.ce@gmail.com"
  creator_name = "Career Coach Creator"
  notes = "cohort courses, career coaching, Instagram/YouTube audience, non-technical, worried about personal touch"
  tags = "youtuber,coach,non-technical"
  source = "manual"
}
```

Current DB caveat observed on 2026-05-24:

- `rossdmello896@gmail.com` already exists as contact `7cd83c8440bb44b1bf5d5a23c955907d`, with no queue entries.
- `crce.9955.ce@gmail.com` already exists as contact `08349be4c8b84121820fa4876441cdf3`, with an old sent sequence-1 queue entry.
- `PATCH /api/contacts/{id}` cannot update `creator_name`, `website_url`, or `tags`; it only accepts `status`, `notes`, `personalization`, and `auto_reply_override`.
- If exact persona metadata is required for existing contacts, update the DB metadata before draft generation or use a fresh plus-address contact.

## 4. Generate Contact A cold draft with Groq

```powershell
$draftA = Invoke-RestMethod -Uri "$Base/api/drafts/generate" -Method Post -ContentType "application/json" -Body (@{
  contact_id = $contactA.id
  provider = "groq"
  tone = "technical, practical, non-hype"
  length = "medium"
} | ConvertTo-Json)

$draftA | Select-Object id,contact_id,subject,ai_provider,ai_model,error_code
```

Expected: subject references data science, Python, pandas, NumPy, Udemy, or technical course support.

## 5. Approve Contact A draft and queue it

```powershell
$approvedA = Invoke-RestMethod -Uri "$Base/api/drafts/$($draftA.id)/approve" -Method Post
$approvedA | Select-Object id,queue_id,subject,approved
```

## 6. Process queue for Contact A

```powershell
$queueResultA = Invoke-RestMethod -Uri "$Base/api/queue/process" -Method Post
$queueResultA
```

Expected: `sent >= 1`, or if another pending item is processed first, inspect `/api/queue` and `/api/audit`.

```powershell
(Invoke-RestMethod -Uri "$Base/api/queue" -Method Get).items |
  Where-Object { $_.contact_id -eq $contactA.id } |
  Sort-Object created_at -Descending |
  Select-Object -First 3
```

## 7. Generate Contact B cold draft with Gemini

```powershell
$draftB = Invoke-RestMethod -Uri "$Base/api/drafts/generate" -Method Post -ContentType "application/json" -Body (@{
  contact_id = $contactB.id
  provider = "gemini"
  tone = "warm, plain-language, non-technical"
  length = "medium"
} | ConvertTo-Json)

$draftB | Select-Object id,contact_id,subject,ai_provider,ai_model,error_code
```

Expected: subject references career coaching, personal development, student support, or cohort support.

## 8. Contact B send options

### Option B1: Normal queue path if there is no existing sequence-1 queue for Contact B

```powershell
$approvedB = Invoke-RestMethod -Uri "$Base/api/drafts/$($draftB.id)/approve" -Method Post
$approvedB | Select-Object id,queue_id,subject,approved
$queueResultB = Invoke-RestMethod -Uri "$Base/api/queue/process" -Method Post
$queueResultB
```

### Option B2: Current-state safe path for `crce.9955.ce@gmail.com`

Because Contact B currently has an old sent sequence-1 queue row, `POST /api/drafts/{draft_id}/approve` can return `409 sequence_already_queued`.

Use the existing conversation send endpoint for this existing contact:

```powershell
$sendB = Invoke-RestMethod -Uri "$Base/api/conversations/$($contactB.id)/send" -Method Post -ContentType "application/json" -Body (@{
  subject = $draftB.subject
  body = $draftB.body
} | ConvertTo-Json)

$sendB | Select-Object status,provider_msg_id,error_code
```

This records:

- `send_attempts.queue_id = "conversation"`
- `conversation_messages.source = "conversation"`
- `audit_events.event_type = conversation.sent` and `send.success`

## 9. Confirm both sends from API-side evidence

```powershell
$audit = Invoke-RestMethod -Uri "$Base/api/audit" -Method Get
$audit.items |
  Where-Object { $_.event_type -in @("send.success","conversation.sent","draft.approved") } |
  Select-Object -First 20 event_type,entity_type,entity_id,created_at,payload

$convos = Invoke-RestMethod -Uri "$Base/api/conversations" -Method Get
$convos.items |
  Where-Object { $_.email -in @("rossdmello896@gmail.com","crce.9955.ce@gmail.com") } |
  Select-Object email,name,status,inbound,outbound,last_subject,last_message_at
```

## 10. Required external inbox checks

SUBAGENT 5 / browser owner must verify:

- `rossdmello896@gmail.com` inbox contains Contact A subject and the subject is data-science/Python specific.
- `crce.9955.ce@gmail.com` inbox contains Contact B subject and the subject is career-coaching/personal-development specific.
- Subjects are different.

