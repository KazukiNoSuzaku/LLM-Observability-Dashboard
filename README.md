# LLM Observability Dashboard

> Production-grade monitoring, safety, and analytics for LLM applications — built with FastAPI, Streamlit, and SQLite.

Track every LLM request across **four providers** (Anthropic, OpenAI, Google Gemini, Mistral AI), surface real-time latency/cost/quality metrics, detect anomalies, run A/B prompt tests, and enforce active input/output safety guardrails — all in one self-hosted stack.

---

## What's Inside

| Layer | What it does |
|---|---|
| **Multi-provider routing** | Auto-detect provider from model name — Claude, GPT, Gemini, Mistral — zero config changes |
| **Full request tracing** | Latency, token usage, cost, error tracking, and OTel spans on every call |
| **Safety & Guardrails** | PII detection (Presidio), jailbreak blocking (10 patterns), output validation (Guardrails AI) |
| **LLM-as-Judge scoring** | Auto-score responses 0–1 via a cheap judge model after every generation |
| **Anomaly detection** | Z-score flagging of latency and cost spikes with per-bucket analysis |
| **Cost forecasting** | Linear regression on cumulative cost trend with a forward projection |
| **A/B prompt testing** | Run two template versions in parallel and get a head-to-head verdict |
| **Webhook alerting** | Slack + Discord alerts with per-model thresholds and cooldown dedup |
| **Real-time dashboard** | 10-section Streamlit UI reading SQLite directly — no API server required |

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
           │                              │ direct SQLite read
           ▼                              │
┌──────────────────────────────────┐      │
│   GuardrailsService  [INPUT]     │      │
│   · Presidio PII scan / regex    │      │
│   · Jailbreak pattern matching   │      │
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
│   · Fire Slack/Discord alerts    │      │
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
│   · Presidio PII redaction       │
│   · Guardrails AI schema check   │
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
│  · Slack + Discord webhooks      │
│  · Per-model cooldown dedup      │
└──────────────────────────────────┘
```

**Design decisions**
- The Streamlit dashboard reads SQLite **directly** — no FastAPI dependency for viewing data.
- All four providers write to the same `llm_requests` table with a `provider` column.
- Guardrails are enabled by default and degrade gracefully — Presidio and Guardrails AI are optional installs; the service falls back to compiled regex and length checks if they're absent.
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
│   │   ├── alerting_service.py     # Slack / Discord webhook alerting
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

Every LLM call passes through a two-stage validation middleware — no extra API keys required.

```
User Prompt
    │
    ▼  INPUT GUARDRAILS
    ├─ PII scan (Presidio or regex)  ──→  block or redact
    └─ Jailbreak detection (10 patterns)  ──→  block or log
    │
    ▼  LLM API Call
    │
    ▼  OUTPUT GUARDRAILS
    ├─ PII redaction (Presidio)
    └─ Schema validation (Guardrails AI / Pydantic)
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

### Violation events

Every trigger is persisted to `guardrail_logs`:

| Field | Values |
|---|---|
| `stage` | `input` / `output` |
| `violation_type` | `pii` / `jailbreak` / `output_invalid` |
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
| `MISTRAL_API_KEY` | — | Mistral AI API key |
| `DATABASE_URL` | `sqlite+aiosqlite:///./llm_observability.db` | SQLAlchemy async DB URL |
| `DEFAULT_MODEL` | `claude-haiku-4-5-20251001` | Default model |
| `MAX_TOKENS` | `1024` | Max completion tokens |

### Alerting

| Variable | Default | Description |
|---|---|---|
| `SLACK_WEBHOOK_URL` | — | Slack Incoming Webhook URL |
| `DISCORD_WEBHOOK_URL` | — | Discord Webhook URL |
| `ALERT_COOLDOWN_SECONDS` | `300` | Min seconds between repeated alerts of the same type |
| `LATENCY_ALERT_THRESHOLD_MS` | `5000` | Latency threshold in ms |
| `COST_ALERT_THRESHOLD_USD` | `0.10` | Cost threshold in USD |
| `MODEL_ALERT_THRESHOLDS_JSON` | `{}` | Per-model overrides: `{"gpt-4o": {"latency_ms": 3000}}` |

### LLM-as-Judge

| Variable | Default | Description |
|---|---|---|
| `JUDGE_ENABLED` | `false` | Auto-score responses after every generation |
| `JUDGE_MODEL` | `claude-haiku-4-5-20251001` | Model used for scoring |

### Guardrails

| Variable | Default | Description |
|---|---|---|
| `GUARDRAILS_ENABLED` | `true` | Master on/off switch |
| `GUARDRAILS_BLOCK_ON_PII` | `false` | Block requests with PII (false = redact instead) |
| `GUARDRAILS_BLOCK_ON_JAILBREAK` | `true` | Hard-block jailbreak attempts |
| `GUARDRAILS_REDACT_OUTPUT_PII` | `true` | Replace PII in responses with `[REDACTED:TYPE]` |
| `GUARDRAILS_USE_PRESIDIO` | `true` | Use Presidio (falls back to regex if not installed) |

### Tracing

| Variable | Default | Description |
|---|---|---|
| `PHOENIX_ENDPOINT` | `http://localhost:6006/v1/traces` | OTLP trace export endpoint |
| `PHOENIX_ENABLED` | `true` | Enable Phoenix/OTel tracing |

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
    violation_type   VARCHAR(50) NOT NULL,    -- pii | jailbreak | output_invalid
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
- **NeMo Guardrails**: Replace `_guardrails_validate_output()` with an `LLMRails` call for dialogue-flow and topic guardrails.
- **PagerDuty / Teams alerting**: Add a handler to [services/alerting_service.py](llm_observability/services/alerting_service.py).
- **Custom judge prompts**: Edit `_SYSTEM_PROMPT` in [services/judge_service.py](llm_observability/services/judge_service.py).
- **LangSmith tracing**: Replace `TracingService` with a LangSmith callback handler.
- **Authentication**: Add `fastapi-users` or OAuth2 middleware to `main.py`.
