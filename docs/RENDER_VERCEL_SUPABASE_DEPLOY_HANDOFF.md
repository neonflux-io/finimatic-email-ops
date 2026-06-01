# Render, Vercel, Supabase Deploy Handoff

This is the current deployment handoff for Finimatic using:

- Supabase Postgres for persistent production data
- Render Free for the FastAPI backend
- Vercel for the Vite/React frontend

Do not put Gmail, Groq, Gemini, SMTP, IMAP, Fernet, Render, Vercel, or database secrets in frontend code or repository files.

## Verified Current State

Supabase project:

| Field | Value |
| --- | --- |
| Project name | `finimatic` |
| Project ref | `hpamfbjawuyztqowtrth` |
| Region | `ap-south-1` |
| API URL | `https://hpamfbjawuyztqowtrth.supabase.co` |
| Database host | `db.hpamfbjawuyztqowtrth.supabase.co` |
| Status | `ACTIVE_HEALTHY` |
| Public app tables | `18` |
| Alembic version | `0003_reply_followup_campaigns` |

GitHub repository:

```text
https://github.com/RossDmello2/email-automation
```

Deployment files are present in the repository:

- `render.yaml`
- `vercel.json`
- `backend/requirements.txt` with `psycopg[binary]`

## Architecture

```text
Browser
  -> Vercel static frontend
  -> VITE_API_URL
  -> Render FastAPI backend
  -> DATABASE_URL
  -> Supabase Postgres
```

The frontend must use only:

```text
VITE_API_URL=https://<render-backend>.onrender.com
```

The backend owns all secrets and side effects.

## Required Backend Env Vars On Render

Set these on the Render web service:

| Key | Value |
| --- | --- |
| `FERNET_KEY` | Stable Fernet key generated once and kept forever for this DB |
| `DATABASE_URL` | Supabase Postgres Session Pooler connection string |
| `ALLOWED_ORIGINS` | Final Vercel frontend origin, comma-separated if more than one |
| `FINIMATIC_DISABLE_SCHEDULER` | `0` for normal app behavior, `1` only for diagnostics |

Generate `FERNET_KEY` locally:

```powershell
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Use Supabase Dashboard -> Connect -> Session Pooler for `DATABASE_URL`.

Recommended connection type for Render Free:

```text
postgres://postgres.<project-ref>:[YOUR-PASSWORD]@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
```

The exact hostname can vary. Copy it from Supabase rather than guessing.

## Render Backend Deploy

Use the Blueprint because `render.yaml` is already committed.

Dashboard link:

```text
https://dashboard.render.com/blueprint/new?repo=https://github.com/RossDmello2/email-automation
```

Expected service from `render.yaml`:

| Setting | Value |
| --- | --- |
| Service name | `finimatic-backend` |
| Type | `web` |
| Runtime | `python` |
| Plan | `free` |
| Root directory | `backend` |
| Build command | `pip install -r requirements.txt` |
| Start command | `uvicorn app.main:app --host 0.0.0.0 --port $PORT` |
| Health check | `/api/health` |

After deploy, verify:

```powershell
Invoke-RestMethod https://<render-backend>.onrender.com/api/health
```

Expected response:

```json
{"status":"ok"}
```

## Vercel Frontend Deploy

Import the same GitHub repository into Vercel.

Use the root repository as the project root because `vercel.json` is at the repo root and already runs commands inside `frontend`.

Expected Vercel settings from `vercel.json`:

| Setting | Value |
| --- | --- |
| Framework | `vite` |
| Install command | `cd frontend && npm ci` |
| Build command | `cd frontend && npm run build` |
| Output directory | `frontend/dist` |

Set the Vercel environment variable:

```text
VITE_API_URL=https://<render-backend>.onrender.com
```

After Vercel gives the final frontend URL, update Render:

```text
ALLOWED_ORIGINS=https://<vercel-frontend>.vercel.app
```

Then redeploy or restart the Render service.

## Post-Deploy Verification

Minimum proof before calling deployment complete:

- Render latest deploy is live.
- `GET https://<render-backend>.onrender.com/api/health` returns `{"status":"ok"}`.
- Vercel production URL loads the dashboard.
- Browser network calls go to the Render backend URL, not `localhost:8000`.
- Backend CORS allows the exact Vercel origin.
- Supabase still shows `ACTIVE_HEALTHY`.
- `GET /api/settings` returns fingerprints/counts only, not raw keys.
- Frontend source and build contain no Gmail/Groq/Gemini secrets.

## Render Free Limitation

Render Free is acceptable for a backend/API smoke deployment, but not for live Gmail SMTP sending.

Render Free blocks outbound SMTP ports `25`, `465`, and `587`. This app uses Gmail SMTP through the backend, so live canary/send behavior will fail on Render Free unless one of these changes is made:

- upgrade the backend host to a paid SMTP-capable service, or
- refactor sending to Gmail API over HTTPS, or
- keep the hosted app in non-live/dry-run mode.

The app defaults to dry-run in settings, so do not disable dry-run on Render Free and expect Gmail SMTP to work.

## Current Automation Blocker

This environment could not complete the live Render/Vercel deployment directly:

- Render CLI is not installed.
- Vercel CLI is not installed.
- Direct REST calls to `api.render.com` and `api.vercel.com` fail with a network-level connection error.
- The available Vercel connector can list projects but cannot create this project here.
- No Render MCP write tools are available in this session.

The remaining deployment action is therefore dashboard-side unless a network-capable runner or configured Render/Vercel MCP write tool becomes available.
