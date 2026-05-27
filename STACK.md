# Finimatic — Tech Stack

---

## Backend

| Component              | Library / Tool                                    |
|------------------------|---------------------------------------------------|
| Web framework          | FastAPI 0.111+                                    |
| ORM                    | SQLAlchemy 2.x (async where needed)               |
| Migrations             | Alembic                                           |
| Database (dev)         | SQLite 3                                          |
| Database (prod option) | PostgreSQL 15+                                    |
| Encryption             | cryptography (Fernet symmetric encryption)        |
| Email sending          | smtplib (stdlib) via ssl.create_default_context() |
| Background tasks       | APScheduler 3.x (AsyncIOScheduler)                |
| Groq AI                | groq SDK (OpenAI-compatible client)               |
| Gemini AI              | google-generativeai SDK                           |
| Validation             | pydantic v2                                       |
| Settings from env      | pydantic-settings                                 |
| Testing                | pytest + pytest-asyncio + httpx (TestClient)      |
| CORS                   | FastAPI CORSMiddleware (localhost origins only)    |

---

## Frontend

| Component          | Library / Tool                                |
|--------------------|-----------------------------------------------|
| Framework          | React 18 + TypeScript                         |
| Build tool         | Vite 5                                        |
| Styling            | TailwindCSS 3                                 |
| Data fetching      | TanStack Query (React Query) v5               |
| Routing            | React Router v6                               |
| File upload        | native `<input type="file">` (no extra lib)   |
| Icons              | lucide-react                                  |
| Toasts / alerts    | react-hot-toast or sonner                     |

**Critical frontend security rules:**
- `VITE_API_URL` is the only allowed env var → points to backend (e.g., `http://localhost:8000`)
- No GROQ keys, Gemini keys, or Gmail credentials in any Vite env var
- All credential fields use `type="password"` and are cleared from React state after POST confirms success
- Fingerprints (sha256[:12]) are shown for key health — never raw keys

---

## Dev & Ops

| Component          | Tool                                          |
|--------------------|-----------------------------------------------|
| Containerization   | Docker + Docker Compose                       |
| Secret management  | Fernet key in `FERNET_KEY` env var (auto-gen if missing on first run) |
| Linting            | ruff (Python), eslint (TypeScript)            |
| Type checking      | mypy (Python), tsc (TypeScript)               |
| Browser testing    | Playwright (Python) or Codex browser extension |

---

## requirements.txt (backend)

```
fastapi>=0.111.0
uvicorn[standard]>=0.29.0
sqlalchemy>=2.0.0
alembic>=1.13.0
aiosqlite>=0.20.0
pydantic>=2.7.0
pydantic-settings>=2.2.0
cryptography>=42.0.0
groq>=0.9.0
google-generativeai>=0.7.0
apscheduler>=3.10.0
httpx>=0.27.0
pytest>=8.0.0
pytest-asyncio>=0.23.0
```

---

## package.json (frontend, key deps)

```json
{
  "dependencies": {
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "react-router-dom": "^6.23.0",
    "@tanstack/react-query": "^5.40.0",
    "lucide-react": "^0.383.0",
    "sonner": "^1.4.0"
  },
  "devDependencies": {
    "typescript": "^5.4.0",
    "vite": "^5.2.0",
    "@vitejs/plugin-react": "^4.3.0",
    "tailwindcss": "^3.4.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0"
  }
}
```

---

## sample.env.example

```bash
# Backend environment variables — copy to .env, DO NOT commit .env
# Generate a Fernet key: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
FERNET_KEY=__generate_with_command_above__

# Server
PORT=8000
ALLOWED_ORIGINS=http://localhost:5173

# Database
DATABASE_URL=sqlite+aiosqlite:///./finimatic.db

# All other credentials (Gmail, Groq, Gemini) are stored in DB via Settings UI.
# DO NOT put them here.
```

`.gitignore` must include:
```
.env
*.db
__pycache__/
.pytest_cache/
node_modules/
dist/
```

---

## Gmail SMTP Adapter

```python
# backend/app/send/smtp_adapter.py
class GmailAdapter:
    def __init__(self, transport: SMTPTransport | FakeTransport): ...

    async def verify(self, user: str, password: str) -> SenderReadiness: ...
    #   → SenderReadiness enum: not_configured | configured | smtp_verified | canary_verified | failed

    async def send_message(self, to: str, subject: str, body: str,
                           sender: str, password: str) -> SendResult: ...

    async def canary_send(self, user: str, password: str,
                          report_recipient: str) -> CanaryResult: ...
    #   → includes nonce, timestamp, idempotency_key, provider_msg_id

class FakeTransport:
    """Used in all automated tests. Never calls smtp.gmail.com."""
    sent: list[dict]  # inspection in tests
    def send(self, ...) -> dict: ...  # always succeeds unless configured to fail
```

---

## Policy Gate Dataclass

```python
# backend/app/send/policy.py
@dataclass
class GateResult:
    gate: str
    passed: bool
    reason_code: str | None = None

@dataclass
class PolicyDecision:
    all_passed: bool
    gates: list[GateResult]
    block_reason_codes: list[str]

async def evaluate_policy(queue_entry, db) -> PolicyDecision:
    """Runs all gates in order. Returns full result with per-gate status."""
```

Gate IDs and reason codes:
```
sender_not_verified        → SENDER_NOT_VERIFIED
canary_not_verified        → CANARY_NOT_VERIFIED
draft_not_approved         → DRAFT_NOT_APPROVED
recipient_suppressed       → RECIPIENT_SUPPRESSED
recipient_bounced          → RECIPIENT_BOUNCED
recipient_replied          → RECIPIENT_REPLIED
recipient_paused           → RECIPIENT_MANUALLY_PAUSED
daily_cap_exceeded         → DAILY_CAP_EXCEEDED
hourly_cap_exceeded        → HOURLY_CAP_EXCEEDED
window_not_elapsed         → SEND_WINDOW_NOT_ELAPSED
idempotency_duplicate      → IDEMPOTENCY_DUPLICATE
```
