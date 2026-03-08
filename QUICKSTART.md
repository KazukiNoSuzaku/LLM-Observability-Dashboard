# LLM Observability Dashboard — Quick Start Guide

A production-grade observability platform for LLM applications.
Tracks latency, token usage, cost, errors, and safety violations across multiple providers.

---

## What you get

| Component | URL | Description |
|---|---|---|
| REST API | http://localhost:8000 | FastAPI backend — generate, monitor, alert |
| Swagger UI | http://localhost:8000/docs | Interactive API docs |
| Dashboard | http://localhost:8501 | Streamlit charts + metrics |

---

## Prerequisites

- Python 3.10 or newer
- At least one LLM API key (Anthropic, OpenAI, or Mistral)
- Git

---

## 1 — Clone and install

```bash
git clone https://github.com/KazukiNoSuzaku/LLM-Observability-Dashboard.git
cd LLM-Observability-Dashboard

python -m venv .venv

# Windows
.venv\Scripts\activate

# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

---

## 2 — Configure

```bash
cp .env.example .env
```

Open `.env` and set **at minimum**:

```ini
# Required — at least one provider key
ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-...
# MISTRAL_API_KEY=...
```

Everything else works with the defaults. Full options are documented inside `.env.example`.

---

## 3 — Start the API

```bash
uvicorn llm_observability.main:app --host 0.0.0.0 --port 8000 --reload
```

Visit **http://localhost:8000/health** — you should see:
```json
{"status": "healthy", "service": "llm-observability"}
```

---

## 4 — Seed sample data (optional but recommended)

Inserts 500 synthetic requests so the dashboard has charts to show:

```bash
python scripts/seed_data.py
```

---

## 5 — Start the dashboard

Open a second terminal (with the same venv active):

```bash
streamlit run llm_observability/dashboard/app.py
```

Visit **http://localhost:8501**

---

## 6 — Make your first real LLM call

```bash
curl -X POST http://localhost:8000/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Explain observability in one sentence."}'
```

Response includes the model's reply, latency, token counts, and estimated cost — all stored automatically.

---

## Key API endpoints

| Method | Path | What it does |
|---|---|---|
| `POST` | `/api/v1/generate` | Run a prompt through an LLM (fully tracked) |
| `GET` | `/api/v1/metrics/summary` | Aggregate stats for the last N hours |
| `GET` | `/api/v1/metrics/timeseries` | Time-bucketed series data |
| `GET` | `/api/v1/metrics/requests` | Paginated request log |
| `POST` | `/api/v1/metrics/requests/{id}/feedback` | Attach a quality score |
| `GET` | `/api/v1/guardrails/stats` | Safety violation breakdown |
| `POST` | `/api/v1/prompts` | Create a versioned prompt template |
| `POST` | `/api/v1/prompts/{name}/ab-generate` | Run an A/B test across two template versions |

Full interactive docs at **http://localhost:8000/docs**.

---

## Switching LLM providers

Pass `model` in your request — the system auto-detects the provider:

```bash
# Anthropic (default)
curl -X POST http://localhost:8000/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello!", "model": "claude-haiku-4-5-20251001"}'

# OpenAI
curl -X POST http://localhost:8000/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello!", "model": "gpt-4o-mini"}'

# Mistral
curl -X POST http://localhost:8000/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Hello!", "model": "mistral-large-latest"}'
```

---

## Optional features

### Authentication

By default auth is off (open access). To require credentials:

```ini
# .env
AUTH_ENABLED=true
AUTH_PASSWORD=changeme
AUTH_API_KEY=my-static-key    # optional alternative to Bearer token
```

```bash
# Get a Bearer token
TOKEN=$(curl -sX POST http://localhost:8000/auth/token \
  -d "username=admin&password=changeme" \
  -H "Content-Type: application/x-www-form-urlencoded" | python -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

curl http://localhost:8000/api/v1/metrics/summary \
  -H "Authorization: Bearer $TOKEN"

# Or use the static API key
curl http://localhost:8000/api/v1/metrics/summary \
  -H "X-API-Key: my-static-key"
```

### Social login (Google / GitHub)

```ini
# .env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
OAUTH_REDIRECT_BASE_URL=http://localhost:8000
OAUTH_SESSION_SECRET=your-random-32-char-secret
```

Then visit **http://localhost:8000/auth/google/login** in a browser.
The callback returns a JWT you can use as a Bearer token.

### PostgreSQL / Supabase

```ini
# .env — replace the DATABASE_URL line
DATABASE_URL=postgresql+asyncpg://user:password@host:5432/dbname
```

Requires: `pip install asyncpg psycopg2-binary` (already in requirements.txt).

### Alerting (Slack / Discord / PagerDuty / Teams)

Set any combination of webhook URLs in `.env`:

```ini
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
DISCORD_WEBHOOK_URL=https://discord.com/api/webhooks/...
PAGERDUTY_ROUTING_KEY=your-32-char-key
TEAMS_WEBHOOK_URL=https://tenant.webhook.office.com/...
```

Alerts fire automatically when latency or cost thresholds are breached.

---

## Common commands

```bash
# Run API (production-style, no reload)
uvicorn llm_observability.main:app --host 0.0.0.0 --port 8000 --workers 2

# Run dashboard
streamlit run llm_observability/dashboard/app.py --server.port 8501

# Re-seed the database
python scripts/seed_data.py

# Check metrics via curl
curl http://localhost:8000/api/v1/metrics/summary | python -m json.tool
```

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError` | Make sure the venv is activated and `pip install -r requirements.txt` completed |
| Port already in use | Change `API_PORT` or `--port` in the start command |
| Dashboard shows no data | Run `python scripts/seed_data.py` or make a few API calls first |
| `ANTHROPIC_API_KEY` errors | Verify the key is set in `.env` and the venv was restarted after editing |
| OAuth login fails | Check `OAUTH_REDIRECT_BASE_URL` matches your server address exactly |

---

## Project layout (for reference)

```
llm_observability/
├── api/
│   ├── auth.py          # JWT + API Key authentication
│   ├── oauth.py         # Google + GitHub OAuth2 social login
│   └── routes.py        # All /api/v1/* endpoints
├── core/
│   ├── config.py        # All settings (env-driven)
│   └── llm_wrapper.py   # Instrumented LLM client
├── db/
│   ├── models.py        # SQLAlchemy ORM models
│   └── database.py      # Engine, sessions, migrations
├── services/
│   ├── guardrails_service.py   # PII + jailbreak + NeMo rails
│   ├── alerting_service.py     # Slack/Discord/PagerDuty/Teams
│   ├── judge_service.py        # LLM-as-judge quality scoring
│   └── metrics_service.py     # Time-series aggregation
└── dashboard/
    └── app.py           # Streamlit UI
scripts/
└── seed_data.py         # Generate synthetic test data
```
