# LLM Observability Dashboard

> Production-grade monitoring, safety, and analytics for LLM applications — built with FastAPI, Streamlit, and SQLite / PostgreSQL (Supabase).

Track every LLM request across **four providers** (Anthropic, OpenAI, Google Gemini, Mistral AI), surface real-time latency/cost/quality metrics, detect anomalies, run A/B prompt tests, and enforce four-layer input/output safety guardrails — all in one self-hosted stack.

**[→ Quick Start Guide](QUICKSTART.md)** — get up and running in 5 minutes.

---

## What's Inside

| Layer | What it does |
|---|---|
| **Multi-provider routing** | Auto-detect provider from model name — Claude, GPT, Gemini, Mistral — zero config changes |
| **Full request tracing** | Latency, token usage, cost, error tracking, and OTel spans on every call |
| **Safety & Guardrails** | 4-layer middleware: PII detection (Presidio), jailbreak blocking, Guardrails AI schema checks, NeMo dialogue-flow rails |
| **LLM-as-Judge scoring** | Auto-score responses 0–1 via a cheap judge model after every generation |
| **Anomaly detection** | Z-score flagging of latency and cost spikes with per-bucket analysis |
| **Cost forecasting** | Linear regression on cumulative cost trend with a forward projection |
| **A/B prompt testing** | Run two template versions in parallel and get a head-to-head verdict |
| **Webhook alerting** | Slack, Discord, PagerDuty, and Microsoft Teams alerts with per-model thresholds and cooldown dedup |
| **Real-time dashboard** | 10-section Streamlit UI — reads SQLite or PostgreSQL directly, no API server required |

---

## Dashboard Preview

![LLM Observability Dashboard](docs/screenshot.png)

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        User / Client                          │
└──────────────┬──────────────────────────────┬────────────────┘
               │ POST /api/v1/generate         │  Browser
               ▼                               ▼
┌──────────────────────┐       ┌───────────────────────────────┐
│   FastAPI  :8000     │       │   Streamlit Dashboard  :8501   │
└──────────┬───────────┘       └──────────┬────────────────────┘
           │                              │ SQLAlchemy sync engine
           ▼                              │
┌──────────────────────────────────┐      │
│   GuardrailsService  [INPUT]     │      │
│   · Presidio PII scan / regex    │      │
│   · Jailbreak regex (10 patterns) │      │
│   · NeMo self_check_input [opt]  │      │
│   · Block / Redact / Log         │      │
└──────────┬───────────────────────┘      │
           │                              │
           ▼                              │
┌──────────────────────────────────┐      │
│   ObservedLLM  (llm_wrapper.py)  │      │
│   · Auto-detect provider         │      │
│   · Time request end-to-end      │      │
│   · Extract token usage & cost   │      │
│   · LLM-as-Judge auto-scoring    │      │
│   · Emit OpenTelemetry spans     │      │
│   · Fire webhook alerts          │      │
└──────────┬───────────────────────┘      │
           │                              │
           ▼  [routes to one of:]         │
┌──────────────────────────────────────────────────────────┐
│  Anthropic SDK   OpenAI SDK   Google GenAI   Mistral SDK │
│  (claude-*)      (gpt-*, o*)  (gemini-*)     (mistral-*) │
└──────────┬───────────────────────────────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│   GuardrailsService  [OUTPUT]    │
│   · NeMo self_check_output [opt] │
│   · Guardrails AI schema check   │
│   · Presidio PII redaction       │
│   · Log violations to DB         │
└──────────┬───────────────────────┘
           │
  ┌────────┴────────────────────────────┐
  ▼                                     ▼
┌────────────────────┐     ┌──────────────────────────┐
│  SQLite / Postgres │     │  Arize Phoenix  :6006     │
│  llm_requests      │     │  (OTel trace viewer)      │
│  guardrail_logs    │     └──────────────────────────┘
│  prompt_templates  │
└────────────────────┘
           │
           ▼
┌──────────────────────────────────┐
│  AlertingService                 │
│  · Slack  · Discord              │
│  · PagerDuty  · Teams            │
│  · Per-type cooldown dedup       │
└──────────────────────────────────┘
```

**Design decisions**
- The Streamlit dashboard reads SQLite **directly** — no FastAPI dependency for viewing data.
- All four providers write to the same `llm_requests` table with a `provider` column.
- Guardrails are enabled by default and degrade gracefully — Presidio, Guardrails AI, and NeMo are optional installs; the service falls back to compiled regex and length checks if they're absent.
- Schema migrations are applied automatically on startup — no migration tool needed.

---

## Project Structure

```
LLM-Observability-Dashboard/
├── llm_observability/
│   ├── main.py                     # FastAPI app entry point + lifespan
│   ├── core/
│   │   ├── config.py               # Pydantic Settings — all env-driven
│   │   ├── pricing.py              # Token cost table (Anthropic, OpenAI, Gemini, Mistral)
│   │   └── llm_wrapper.py          # ObservedLLM — multi-provider + full instrumentation
│   ├── db/
│   │   ├── database.py             # Async SQLAlchemy engine + incremental migrations
│   │   ├── models.py               # LLMRequest + GuardrailLog ORM models
│   │   └── crud.py                 # Async CRUD + analytics queries
│   ├── services/
│   │   ├── tracing_service.py      # OpenTelemetry + Arize Phoenix integration
│   │   ├── metrics_service.py      # Time-series bucketing
│   │   ├── alerting_service.py     # Slack / Discord / PagerDuty / Teams alerting
│   │   ├── judge_service.py        # LLM-as-judge auto quality scoring
│   │   └── guardrails_service.py   # PII detection, jailbreak scan, output validation
│   ├── api/
│   │   ├── schemas.py              # Pydantic request/response models
│   │   └── routes.py               # FastAPI router — all endpoints
│   └── dashboard/
│       └── app.py                  # Streamlit dashboard (10 sections)
├── scripts/
│   └── seed_data.py                # Seed 500 synthetic request records
├── requirements.txt
├── .env.example
├── Makefile
└── README.md
```

---

## Quick Start

```bash
# 1. Clone
git clone https://github.com/KazukiNoSuzaku/LLM-Observability-Dashboard.git
cd LLM-Observability-Dashboard

# 2. Install
pip install -r requirements.txt

# 3. Configure
cp .env.example .env
# Add at minimum: ANTHROPIC_API_KEY=sk-ant-...

# 4. Seed 500 sample records
python scripts/seed_data.py

# 5. Open the dashboard (no API server needed)
streamlit run llm_observability/dashboard/app.py
```

Visit **http://localhost:8501**

To also run the REST API:
```bash
uvicorn llm_observability.main:app --host 0.0.0.0 --port 8000 --reload
# API docs: http://localhost:8000/docs
```

---

## Multi-Provider Support

`ObservedLLM` auto-detects the provider from the model name prefix. No config changes needed — just set the right API key.

| Model prefix | Provider | SDK | API key env var |
|---|---|---|---|
| `claude-*` | Anthropic | `anthropic` | `ANTHROPIC_API_KEY` |
| `gpt-*`, `o1-*`, `o3-*`, `o4-*` | OpenAI | `openai` | `OPENAI_API_KEY` |
| `gemini-*` | Google | `google-genai` | `GOOGLE_API_KEY` |
| `mistral-*`, `mixtral-*`, `codestral-*`, `pixtral-*` | Mistral AI | `mistralai` | `MISTRAL_API_KEY` |

```python
from llm_observability.core.llm_wrapper import ObservedLLM

# Anthropic (default)
result = await ObservedLLM().generate("Explain transformers.")

# OpenAI
result = await ObservedLLM(model="gpt-4o-mini").generate("Explain transformers.")

# Google Gemini
result = await ObservedLLM(model="gemini-2.0-flash").generate("Explain transformers.")

# Mistral AI
result = await ObservedLLM(model="mistral-large-latest").generate("Explain transformers.")
```

Every call — regardless of provider — writes to the same `llm_requests` table, appears in the same dashboard charts, and passes through the same guardrail middleware.

### Supported Mistral models

| Model | Input / 1M tokens | Output / 1M tokens |
|---|---|---|
| `mistral-large-latest` | $2.00 | $6.00 |
| `mistral-small-latest` | $0.10 | $0.30 |
| `mistral-nemo` | $0.15 | $0.15 |
| `codestral-latest` | $0.20 | $0.60 |
| `pixtral-large-latest` | $2.00 | $6.00 |
| `mixtral-8x7b-instruct` | $0.70 | $0.70 |
| `mixtral-8x22b-instruct` | $2.00 | $6.00 |

---

## Safety & Guardrails

Every LLM call passes through a four-layer validation middleware. Layers 1–3 are zero-config. Layer 4 (NeMo) is optional and adds LLM-as-judge dialogue-flow enforcement.

```
User Prompt
    │
    ▼  INPUT GUARDRAILS  (scan_input — async)
    ├─ Layer 1: PII scan (Presidio or regex)  ──→  block or redact
    ├─ Layer 2: Jailbreak detection (10 regex)  ──→  block or log
    └─ Layer 4: NeMo self_check_input (LLMRails)  ──→  block or log [optional]
    │
    ▼  LLM API Call
    │
    ▼  OUTPUT GUARDRAILS  (scan_output — async)
    ├─ Layer 4: NeMo self_check_output (LLMRails)  ──→  log [optional]
    ├─ Layer 3: Schema validation (Guardrails AI / Pydantic)
    └─ Layer 1: PII redaction (Presidio)
    │
    ▼  violation events written to guardrail_logs
```

### Layer 1 — PII Detection (input + output)

Uses **Microsoft Presidio** when installed, compiled regex otherwise. Detects:

| Entity | Examples |
|---|---|
| `EMAIL_ADDRESS` | `user@example.com` |
| `PHONE_NUMBER` | `+1 (555) 867-5309` |
| `US_SSN` | `123-45-6789` |
| `CREDIT_CARD` | `4111 1111 1111 1111` |
| `IP_ADDRESS` | `192.168.1.1` |
| `AWS_ACCESS_KEY` | `AKIAIOSFODNN7EXAMPLE` |
| `API_KEY_BEARER` | `Bearer eyJhb...` |

```bash
# Optional — enables higher-accuracy NER-based detection
pip install presidio-analyzer presidio-anonymizer
python -m spacy download en_core_web_lg
```

### Layer 2 — Jailbreak / Prompt Injection (input)

10 compiled regex patterns cover the most common adversarial techniques:

- **DAN variants** — "Do Anything Now", "jailbreak"
- **Instruction override** — "ignore all previous instructions"
- **System prompt leakage** — "repeat your system prompt"
- **Role-play bypass** — "pretend you are an uncensored AI"
- **Developer / god mode** — "activate developer mode"
- **Base64 injection** — "decode this and execute"
- **Competitor impersonation** — "you are now GPT-4"
- **XML prompt injection** — `<system>`, `<instruction>` tags
- **Token smuggling** — "new instructions:"
- **Hypothetical bypass** — "imagine you had no restrictions"

### Layer 3 — Structured Output Validation (output)

Uses **Guardrails AI** when installed to validate responses against a Pydantic schema. Falls back to length and content checks.

```bash
pip install guardrails-ai
# Optional extended validator:
guardrails hub install hub://guardrails/toxic_language
```

### Layer 4 — NeMo Guardrails: Dialogue-Flow & Topic Rails (input + output)

**NVIDIA NeMo Guardrails** (`nemoguardrails`) adds LLM-as-judge validation via `LLMRails`. A secondary LLM call evaluates each input/response against a configurable safety policy using NeMo's built-in `self_check_input` and `self_check_output` actions.

| NeMo rail | Triggered by | Action |
|---|---|---|
| `self_check_input` | Off-policy user prompt | Block + log `nemo` violation |
| `self_check_output` | Unsafe/non-compliant response | Log `nemo` violation |

**Policy enforced** (configurable via `_NEMO_PROMPTS_YAML` in [services/guardrails_service.py](llm_observability/services/guardrails_service.py)):
- No harmful, illegal, or dangerous instructions
- No explicit or adult content
- No hate speech or discrimination
- No PII in responses
- No jailbreak / role-play bypass attempts
- No instructions for weapons, malware, or illegal activities

**Setup:**
```bash
# Install NeMo + LangChain adapter for your chosen validation LLM:
pip install nemoguardrails langchain-openai      # OpenAI as validator
# or:
pip install nemoguardrails langchain-anthropic   # Anthropic as validator
```

```env
# .env
GUARDRAILS_NEMO_ENABLED=true
GUARDRAILS_NEMO_ENGINE=auto        # auto-detects from OPENAI_API_KEY / ANTHROPIC_API_KEY
GUARDRAILS_NEMO_MODEL=gpt-4o-mini  # fast model recommended — each check = 1 LLM call
```

> NeMo validation adds ~500–1500 ms latency per request (one extra LLM call). Use a small, fast model (`gpt-4o-mini`, `claude-haiku`) to minimise overhead. The NeMo rails singleton is cached after first initialisation.

**Architecture note**: Both `scan_input()` and `scan_output()` are `async def` to support `await rails.generate_async(...)`. The NeMo config is built dynamically from app settings — no static config files required.

### Violation events

Every trigger is persisted to `guardrail_logs`:

| Field | Values |
|---|---|
| `stage` | `input` / `output` |
| `violation_type` | `pii` / `jailbreak` / `output_invalid` / `nemo` |
| `severity` | `low` / `medium` / `high` / `critical` |
| `action_taken` | `pass` / `block` / `redact` / `log` |
| `latency_ms` | guardrail check overhead |
| `snippet` | truncated prompt/response (200 chars) |

### Dashboard — Safety & Guardrails section

- **5 KPI cards** — total violations, blocked, PII detections, jailbreak attempts, avg guard latency
- **Pass/Fail ratio donut** — action distribution across pass / block / redact / log
- **Latency impact chart** — guardrail overhead vs raw LLM latency per time bucket
- **Violations by type** — stacked time-series bar (PII / jailbreak / output_invalid)
- **Input vs Output split** — donut showing where violations occur
- **Violation log table** — filterable by type, downloadable as CSV
- **Policy Manager** — sidebar expander showing live guardrail config flags

### Guardrail API

```bash
# Paginated violation log
curl "http://localhost:8000/api/v1/guardrails/logs?hours=24&violation_type=jailbreak"

# Aggregate stats
curl "http://localhost:8000/api/v1/guardrails/stats?hours=24"
```

```json
{
  "hours": 24,
  "total_violations": 12,
  "avg_guardrail_latency_ms": 3.4,
  "total_blocked": 2,
  "total_redacted": 7,
  "by_type": { "pii": 8, "jailbreak": 2, "output_invalid": 2 },
  "by_stage": { "input": 9, "output": 3 }
}
```

---

## Dashboard Sections

| Section | Description |
|---|---|
| **Key Metrics** | 5 KPI cards — total requests, avg/p95 latency, total cost, error rate — with live sparklines and threshold badges |
| **Time Series** | Latency chart (avg + p95 + Z-score anomaly markers) and cost chart (per-min bars + cumulative + linear regression forecast) |
| **Token & Volume** | Stacked prompt/completion token chart and requests-per-minute area chart |
| **Distribution & Breakdown** | Latency histogram, requests-by-model donut, requests-by-provider donut |
| **Percentile Stats** | p50/p99 latency, avg tokens, avg quality score KPI cards |
| **Recent Requests** | Searchable, filterable request table with prompt/response preview + CSV export |
| **Anomaly Detection** | Z-score flagging of latency and cost spikes — KPI cards + flagged request table |
| **Prompt Version Control** | Per-version latency/cost/feedback bar charts, summary table, and template content viewer |
| **A/B Experiment** | Head-to-head comparison of two template versions with WIN badges and grouped bar chart |
| **Safety & Guardrails** | Violation KPIs, pass/fail donut, latency impact chart, violation log + CSV export |

Sidebar controls: time window (1h–7d), model filter, alert threshold sliders, per-model overrides, guardrails Policy Manager, auto-refresh toggle.

---

## Configuration Reference

### Core

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Anthropic API key |
| `OPENAI_API_KEY` | — | OpenAI API key |
| `GOOGLE_API_KEY` | — | Google Gemini API key |
| `MISTRAL_API_KEY` | — | Mistral AI API key |
| `DATABASE_URL` | `sqlite+aiosqlite:///./llm_observability.db` | SQLAlchemy async DB URL (SQLite or `postgresql+asyncpg://...`) |
| `SUPABASE_URL` | — | Supabase project URL (optional — only needed for the `supabase-py` client) |
| `SUPABASE_ANON_KEY` | — | Supabase anon key (optional — SQLAlchemy uses `DATABASE_URL` directly) |
| `DEFAULT_MODEL` | `claude-haiku-4-5-20251001` | Default model |
| `MAX_TOKENS` | `1024` | Max completion tokens |

### Alerting

Four channels are supported — enable any combination by setting the relevant variable.

| Variable | Default | Description |
|---|---|---|
| `SLACK_WEBHOOK_URL` | — | Slack Incoming Webhook URL |
| `DISCORD_WEBHOOK_URL` | — | Discord Webhook URL |
| `PAGERDUTY_ROUTING_KEY` | — | PagerDuty Events API v2 integration routing key (32 chars) |
| `TEAMS_WEBHOOK_URL` | — | Microsoft Teams Incoming Webhook connector URL |
| `ALERT_COOLDOWN_SECONDS` | `300` | Min seconds between repeated alerts of the same type |
| `LATENCY_ALERT_THRESHOLD_MS` | `5000` | Latency threshold in ms |
| `COST_ALERT_THRESHOLD_USD` | `0.10` | Cost threshold in USD |
| `MODEL_ALERT_THRESHOLDS_JSON` | `{}` | Per-model overrides: `{"gpt-4o": {"latency_ms": 3000}}` |

**Channel details:**

| Channel | Payload format | Dedup |
|---|---|---|
| Slack | Block Kit message | cooldown by `alert_type` |
| Discord | Embed | cooldown by `alert_type` |
| PagerDuty | Events API v2 trigger | `dedup_key = alert_type` (updates open incident) |
| Microsoft Teams | Adaptive Card (v1.4) | cooldown by `alert_type` |

**PagerDuty setup:**
1. Go to **Services → \<your service\> → Integrations → Add integration**
2. Choose **Events API v2** and copy the 32-character routing key
3. Set `PAGERDUTY_ROUTING_KEY=<key>` in `.env`

Severity mapping: `color="danger"` → `critical`, `color="warning"` → `warning`, `color="info"` → `info`.

**Teams setup:**
1. In Teams open the channel → **… → Connectors → Incoming Webhook → Configure**
2. Name the webhook and copy the generated URL
3. Set `TEAMS_WEBHOOK_URL=<url>` in `.env`

### LLM-as-Judge

| Variable | Default | Description |
|---|---|---|
| `JUDGE_ENABLED` | `false` | Auto-score responses after every generation |
| `JUDGE_MODEL` | `claude-haiku-4-5-20251001` | Model used for scoring |

### Guardrails

| Variable | Default | Description |
|---|---|---|
| `GUARDRAILS_ENABLED` | `true` | Master on/off switch |
| `GUARDRAILS_BLOCK_ON_PII` | `false` | Block requests with PII (`false` = redact instead) |
| `GUARDRAILS_BLOCK_ON_JAILBREAK` | `true` | Hard-block jailbreak attempts |
| `GUARDRAILS_REDACT_OUTPUT_PII` | `true` | Replace PII in responses with `[REDACTED:TYPE]` |
| `GUARDRAILS_USE_PRESIDIO` | `true` | Use Presidio NER (falls back to regex if not installed) |
| `GUARDRAILS_NEMO_ENABLED` | `false` | Enable NeMo Guardrails LLMRails (Layer 4) |
| `GUARDRAILS_NEMO_ENGINE` | `auto` | NeMo LLM engine: `auto` \| `openai` \| `anthropic` |
| `GUARDRAILS_NEMO_MODEL` | `gpt-4o-mini` | Model for NeMo secondary validation calls |

### Tracing

| Variable | Default | Description |
|---|---|---|
| `PHOENIX_ENDPOINT` | `http://localhost:6006/v1/traces` | OTLP trace export endpoint |
| `PHOENIX_ENABLED` | `true` | Enable Phoenix/OTel tracing |

---

## Authentication

Auth is **disabled by default** — every request is accepted as `anonymous`. Set `AUTH_ENABLED=true` to require credentials.

### Two mechanisms (use either or both)

| Mechanism | How to use | Set up |
|---|---|---|
| Bearer token (JWT) | `POST /auth/token` → get token → `Authorization: Bearer <token>` | `AUTH_USERNAME`, `AUTH_PASSWORD` |
| API Key (static) | `X-API-Key: <key>` header on every request | `AUTH_API_KEY` |

### Quick start

```bash
# 1. Enable auth in .env
AUTH_ENABLED=true
AUTH_PASSWORD=changeme
AUTH_API_KEY=my-static-key       # optional

# 2a. Bearer token flow
TOKEN=$(curl -sX POST http://localhost:8000/auth/token \
  -d "username=admin&password=changeme" \
  -H "Content-Type: application/x-www-form-urlencoded" | jq -r .access_token)

curl http://localhost:8000/api/v1/metrics/summary \
  -H "Authorization: Bearer $TOKEN"

# 2b. API key flow
curl http://localhost:8000/api/v1/metrics/summary \
  -H "X-API-Key: my-static-key"
```

### Auth endpoints

| Method | Path | Description |
|---|---|---|
| `POST` | `/auth/token` | Exchange username + password for a JWT (OAuth2 Password Flow) |
| `GET` | `/auth/me` | Returns caller identity (`username`, `auth_method`, `authenticated`) |

> **Production note**: Set `AUTH_SECRET_KEY` to a random 32-char secret so JWTs survive server restarts. Install `PyJWT>=2.8.0` for standard JWT encoding (the module falls back to an HMAC-signed token otherwise).

### Social login (Google + GitHub)

OAuth2 social login is built on [Authlib](https://docs.authlib.org). Users are auto-provisioned in the `oauth_users` table on first login and receive the same JWT used by all other auth methods.

| Provider | Login URL | Callback URL |
|---|---|---|
| Google | `GET /auth/google/login` | `GET /auth/google/callback` |
| GitHub | `GET /auth/github/login` | `GET /auth/github/callback` |
| (meta) | `GET /auth/providers` | Lists which providers are configured |

**Google setup**
1. [Google Cloud Console](https://console.cloud.google.com/apis/credentials) → Create OAuth 2.0 Client ID (Web application)
2. Add Authorised redirect URI: `{OAUTH_REDIRECT_BASE_URL}/auth/google/callback`
3. Set `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in `.env`

**GitHub setup**
1. [GitHub → Settings → Developer settings → OAuth Apps](https://github.com/settings/developers) → New OAuth App
2. Set Callback URL: `{OAUTH_REDIRECT_BASE_URL}/auth/github/callback`
3. Set `GITHUB_CLIENT_ID` and `GITHUB_CLIENT_SECRET` in `.env`

```bash
# Point a browser at the login URL — you'll be redirected to the provider,
# then back to /callback which returns {"access_token": "...", "token_type": "bearer"}
curl http://localhost:8000/auth/google/login        # → 302 to Google
curl http://localhost:8000/auth/providers           # → {"google": true, "github": false}

# Use the returned token exactly like a password-flow token
curl http://localhost:8000/api/v1/metrics/summary \
  -H "Authorization: Bearer <token_from_callback>"
```

> `OAUTH_SESSION_SECRET` must be set to a random 32-char value in production — it signs the CSRF state cookie used during the OAuth handshake.

---

## API Reference

All endpoints prefixed with `/api/v1`. Interactive docs at **http://localhost:8000/docs**.

### Generation

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/generate` | Generate a completion — multi-provider, fully tracked, guardrails applied |

```bash
# Anthropic
curl -X POST http://localhost:8000/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is observability?"}'

# Mistral
curl -X POST http://localhost:8000/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is observability?", "model": "mistral-large-latest"}'
```

### Metrics

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/metrics/summary` | Aggregate metrics (latency, cost, tokens, error rate) |
| `GET` | `/api/v1/metrics/requests` | Paginated request log |
| `POST` | `/api/v1/metrics/requests/{id}/feedback` | Attach a quality score |
| `GET` | `/api/v1/metrics/timeseries` | Time-bucketed series data |
| `GET` | `/api/v1/metrics/models` | Per-model breakdown |

### Prompt Templates

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/v1/prompts` | Create a new template version |
| `GET` | `/api/v1/prompts` | List all active templates |
| `GET` | `/api/v1/prompts/{name}` | All versions of a template |
| `GET` | `/api/v1/prompts/{name}/compare` | Per-version metric comparison |
| `POST` | `/api/v1/prompts/{name}/ab-generate` | Run A/B test across two versions (parallel) |
| `DELETE` | `/api/v1/prompts/{name}/{version}` | Soft-delete a version |

### Guardrails

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/v1/guardrails/logs` | Paginated violation log — filter by type/stage/hours |
| `GET` | `/api/v1/guardrails/stats` | Aggregate counts, latency overhead, breakdown by type and stage |

---

## Database Schema

```sql
-- Every LLM API call
CREATE TABLE llm_requests (
    id                      INTEGER  PRIMARY KEY AUTOINCREMENT,
    timestamp               DATETIME NOT NULL,
    prompt                  TEXT     NOT NULL,
    response                TEXT,
    model_name              VARCHAR(100) NOT NULL,
    provider                VARCHAR(50),          -- anthropic | openai | google | mistral
    latency_ms              FLOAT,
    prompt_tokens           INTEGER,
    completion_tokens       INTEGER,
    total_tokens            INTEGER,
    estimated_cost          FLOAT,
    error                   TEXT,
    is_error                BOOLEAN  NOT NULL DEFAULT 0,
    feedback_score          FLOAT,                -- 0.0–1.0, human or judge
    response_length         INTEGER,
    trace_id                VARCHAR(100),
    prompt_template_id      INTEGER,
    prompt_template_name    VARCHAR(100),
    prompt_template_version INTEGER,
    prompt_variables        TEXT                  -- JSON
);

-- Guardrail violation events
CREATE TABLE guardrail_logs (
    id               INTEGER  PRIMARY KEY AUTOINCREMENT,
    request_id       INTEGER  REFERENCES llm_requests(id) ON DELETE SET NULL,
    timestamp        DATETIME NOT NULL,
    stage            VARCHAR(20) NOT NULL,    -- input | output
    violation_type   VARCHAR(50) NOT NULL,    -- pii | jailbreak | output_invalid | nemo
    severity         VARCHAR(20) NOT NULL,    -- low | medium | high | critical
    action_taken     VARCHAR(20) NOT NULL,    -- pass | block | redact | log
    latency_ms       FLOAT,
    snippet          TEXT,                    -- first 200 chars of prompt/response
    metadata_json    TEXT                     -- JSON: pii_types, patterns, reasons
);

-- Versioned prompt templates
CREATE TABLE prompt_templates (
    id           INTEGER  PRIMARY KEY AUTOINCREMENT,
    name         VARCHAR(100) NOT NULL,
    version      INTEGER  NOT NULL,
    content      TEXT     NOT NULL,
    system_prompt TEXT,
    description  VARCHAR(500),
    created_at   DATETIME NOT NULL,
    is_active    BOOLEAN  NOT NULL DEFAULT 1
);
```

Both tables are created automatically on startup. New columns are added via `ALTER TABLE` on each boot — no migration tool needed.

---

## Supabase / PostgreSQL Setup

The system supports **SQLite** (default, zero-config) and **PostgreSQL** (production-ready, including [Supabase](https://supabase.com)).

### Quick Supabase Setup

1. **Create a project** at [supabase.com](https://supabase.com) (free tier available).

2. **Get your connection string**: Project Settings → Database → Connection string → URI tab.

3. **Set `DATABASE_URL`** in your `.env` file:
   ```env
   # Session pooler — recommended for serverless / short-lived connections
   DATABASE_URL=postgresql+asyncpg://postgres.[ref]:[password]@aws-0-us-east-1.pooler.supabase.com:6543/postgres

   # Direct connection — for long-lived processes (FastAPI, seed script)
   # DATABASE_URL=postgresql+asyncpg://postgres:[password]@db.[ref].supabase.co:5432/postgres
   ```

4. **Install PostgreSQL drivers**:
   ```bash
   pip install asyncpg psycopg2-binary
   ```

5. **Run the app** — tables are created automatically on first startup:
   ```bash
   make run-api          # FastAPI (uses asyncpg)
   make run-dashboard    # Streamlit (uses psycopg2 via SQLAlchemy sync engine)
   ```

### What Changes Between SQLite and Supabase

| Component | SQLite | Supabase / PostgreSQL |
|---|---|---|
| Driver (async) | `aiosqlite` | `asyncpg` |
| Driver (sync dashboard) | `sqlite3` → `sqlalchemy` | `psycopg2-binary` → `sqlalchemy` |
| Time bucketing | `strftime` + `printf` | `date_bin` (PG 14+) |
| Schema migrations | `ALTER TABLE … ADD COLUMN` (ignore error) | `ALTER TABLE … ADD COLUMN IF NOT EXISTS` |
| Seed data | `make seed` | `make seed` (same script) |

> **Note**: The Streamlit dashboard automatically detects the database type from `DATABASE_URL` and switches drivers — no code changes needed.

---

## Arize Phoenix Tracing (Optional)

Every `ObservedLLM.generate()` call emits an OpenTelemetry span when `PHOENIX_ENABLED=true`.

```bash
# Start Phoenix
python -c "import phoenix as px; session = px.launch_app(); import time; time.sleep(86400)"
# Open http://localhost:6006
```

Each span includes `llm.model`, `llm.provider`, `llm.prompt_tokens`, `llm.completion_tokens`, `llm.latency_ms`, `llm.estimated_cost_usd`, and `llm.trace_id`.

---

## Extending the Project

- **Add a new LLM provider**: Add `_call_<provider>()` to `ObservedLLM` in [core/llm_wrapper.py](llm_observability/core/llm_wrapper.py) and extend `_detect_provider()` with the new model prefix.
- **Supabase / PostgreSQL**: See the [Supabase Setup](#supabase--postgresql-setup) section above — change `DATABASE_URL` and `pip install asyncpg psycopg2-binary`.
- **Custom guardrail patterns**: Add to `_JAILBREAK_PATTERNS` or `_REGEX_PII` in [services/guardrails_service.py](llm_observability/services/guardrails_service.py).
- **Presidio custom recognisers**: Extend `_presidio_scan_pii()` with a `PatternRecognizer` for domain entities (e.g. employee IDs, medical record numbers).
- **NeMo custom topics**: Extend `_NEMO_PROMPTS_YAML` or `_NEMO_COLANG_CONTENT` in [services/guardrails_service.py](llm_observability/services/guardrails_service.py) to add domain-specific topic restrictions or dialogue flows. Enable with `GUARDRAILS_NEMO_ENABLED=true`.
- **Custom alert channels**: Add a `_send_<channel>()` classmethod to [services/alerting_service.py](llm_observability/services/alerting_service.py) following the Slack/Discord/PagerDuty/Teams pattern, then call it in `send_alert()`.
- **Custom judge prompts**: Edit `_SYSTEM_PROMPT` in [services/judge_service.py](llm_observability/services/judge_service.py).
- **LangSmith tracing**: Replace `TracingService` with a LangSmith callback handler.
- **Multi-user auth with roles**: Swap the single-user config for `fastapi-users` with a `users` table; add `admin`/`viewer` role enforcement per endpoint.
- **Rate limiting**: Add `slowapi` middleware on `/api/v1/generate` (per-IP or per-authenticated-user).
- **Docker + CI**: Containerise API + Streamlit + Phoenix; add GitHub Actions for lint/type-check/test on push.
