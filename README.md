# LLM Observability Dashboard

A production-grade observability system for LLM applications built with FastAPI, Streamlit, Arize Phoenix, and Anthropic's Claude API.

Tracks every LLM request and surfaces latency, cost, token usage, error rates, and quality metrics in a real-time dashboard.

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     User / Client                        │
└──────────────┬─────────────────────────┬────────────────┘
               │ POST /api/v1/generate    │  Browser
               ▼                          ▼
┌──────────────────────┐     ┌───────────────────────────┐
│   FastAPI Backend    │     │  Streamlit Dashboard       │
│   :8000              │     │  :8501                     │
└──────────┬───────────┘     └──────────┬────────────────┘
           │                             │ direct SQLite read
           ▼                             │
┌──────────────────────┐                 │
│   ObservedLLM        │                 │
│   llm_wrapper.py     │                 │
│  · time request      │                 │
│  · extract tokens    │                 │
│  · calculate cost    │                 │
│  · emit OTel spans   │                 │
└──────┬───────────────┘                 │
       │                                 │
  ┌────┴─────────────────────────────────┤
  ▼                                      ▼
┌──────────────────┐     ┌──────────────────────────┐
│  SQLite / Postgres│     │  Arize Phoenix :6006     │
│  llm_requests    │     │  (OTel trace viewer)     │
└──────────────────┘     └──────────────────────────┘
```

**Design decisions**
- The Streamlit dashboard reads SQLite **directly** — it does not need the FastAPI server running.
- FastAPI exposes the REST API for external consumers and live generation.
- Arize Phoenix is **optional** — the app degrades gracefully to a console exporter.

---

## Project Structure

```
LLM-Observability-Dashboard/
├── llm_observability/
│   ├── main.py                    # FastAPI app entry point
│   ├── core/
│   │   ├── config.py              # Pydantic Settings (env-driven)
│   │   ├── pricing.py             # Token cost calculator
│   │   └── llm_wrapper.py        # ObservedLLM instrumented wrapper
│   ├── db/
│   │   ├── database.py            # Async SQLAlchemy engine
│   │   ├── models.py              # LLMRequest ORM model
│   │   └── crud.py                # Async CRUD + aggregate queries
│   ├── services/
│   │   ├── tracing_service.py     # OTel + Phoenix integration
│   │   └── metrics_service.py    # Time-series aggregation
│   ├── api/
│   │   ├── schemas.py             # Pydantic request/response models
│   │   └── routes.py              # FastAPI router
│   └── dashboard/
│       └── app.py                 # Streamlit dashboard
├── scripts/
│   └── seed_data.py               # Generate 500 synthetic records
├── requirements.txt
├── .env.example
├── Makefile
└── README.md
```

---

## Prerequisites

- Python 3.11+
- An Anthropic API key (only required for live generation — not needed to view seeded data)

---

## Quick Start (5 steps)

```bash
# 1. Clone and enter the project
git clone https://github.com/KazukiNoSuzaku/LLM-Observability-Dashboard.git
cd LLM-Observability-Dashboard

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env and add your ANTHROPIC_API_KEY

# 4. Seed the database with 500 sample records
python scripts/seed_data.py

# 5. Open the dashboard
streamlit run llm_observability/dashboard/app.py
```

Visit **http://localhost:8501** to see the dashboard.

---

## Running the Full Stack

### Option A — Makefile (recommended)

```bash
# Terminal 1: API backend
make run-api

# Terminal 2: Streamlit dashboard
make run-dashboard

# Terminal 3 (optional): Arize Phoenix trace UI
make run-phoenix
```

### Option B — Manual commands

```bash
# Backend (FastAPI)
uvicorn llm_observability.main:app --host 0.0.0.0 --port 8000 --reload

# Dashboard (Streamlit)
streamlit run llm_observability/dashboard/app.py

# Phoenix (optional)
python -c "import phoenix as px; session = px.launch_app(); print(session.url); import time; time.sleep(86400)"
```

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Anthropic API key (required for live generation) |
| `DATABASE_URL` | `sqlite+aiosqlite:///./llm_observability.db` | SQLAlchemy async DB URL |
| `PHOENIX_ENDPOINT` | `http://localhost:6006/v1/traces` | OTLP trace export endpoint |
| `PHOENIX_ENABLED` | `true` | Enable/disable Phoenix tracing |
| `DEFAULT_MODEL` | `claude-haiku-4-5-20251001` | Default Anthropic model |
| `MAX_TOKENS` | `1024` | Max completion tokens |
| `API_HOST` | `0.0.0.0` | FastAPI bind address |
| `API_PORT` | `8000` | FastAPI port |
| `LATENCY_ALERT_THRESHOLD_MS` | `5000` | Log WARNING above this latency |
| `COST_ALERT_THRESHOLD_USD` | `0.10` | Log WARNING above this per-request cost |

---

## API Endpoints

All endpoints are prefixed with `/api/v1`.
Interactive docs: **http://localhost:8000/docs**

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `POST` | `/api/v1/generate` | Generate a completion (tracked) |
| `GET` | `/api/v1/metrics/summary` | Aggregate summary metrics |
| `GET` | `/api/v1/metrics/requests` | Paginated request log |
| `POST` | `/api/v1/metrics/requests/{id}/feedback` | Attach feedback score |
| `GET` | `/api/v1/metrics/timeseries` | Time-bucketed series data |
| `GET` | `/api/v1/metrics/models` | Per-model breakdown |

### Example: generate a completion

```bash
curl -s -X POST http://localhost:8000/api/v1/generate \
  -H "Content-Type: application/json" \
  -d '{"prompt": "What is observability in software engineering?"}' | jq .
```

```json
{
  "response": "Observability is the ability to understand ...",
  "model": "claude-haiku-4-5-20251001",
  "latency_ms": 847.3,
  "prompt_tokens": 12,
  "completion_tokens": 94,
  "total_tokens": 106,
  "estimated_cost": 0.0000001445,
  "trace_id": "a3f8c21d-...",
  "error": null
}
```

### Example: view summary metrics

```bash
curl http://localhost:8000/api/v1/metrics/summary?hours=24 | jq .
```

```json
{
  "total_requests": 487,
  "avg_latency_ms": 934.12,
  "p50_latency_ms": 812.4,
  "p95_latency_ms": 2341.7,
  "total_cost_usd": 0.00312,
  "total_tokens": 54892,
  "avg_tokens": 112.7,
  "error_count": 14,
  "error_rate_pct": 2.87,
  "hours": 24
}
```

---

## Dashboard Features

| Section | What you see |
|---|---|
| KPI cards | Total requests, avg/p95 latency, total cost, error rate with 🟢/🔴 status |
| Latency chart | Avg + max latency over time with configurable alert threshold line |
| Cost chart | Per-minute cost bars + cumulative cost overlay |
| Token chart | Stacked prompt + completion tokens per minute |
| RPM chart | Requests per minute area chart |
| Latency histogram | Distribution with avg and p95 markers |
| Model pie chart | Request share by model |
| Footer KPIs | p50 / p99 latency, avg tokens, avg feedback score |
| Request table | Searchable, filterable, truncated prompt/response preview |
| Auto-refresh | 10-second refresh toggle in sidebar |
| Phoenix link | One-click link to trace viewer |

---

## Arize Phoenix Tracing (Optional)

Phoenix provides a visual distributed trace explorer showing individual LLM spans with full attributes (latency, tokens, cost, prompt/response).

```bash
# Start Phoenix
make run-phoenix
# Open http://localhost:6006

# Or embed in a Python script:
import phoenix as px
session = px.launch_app()
print(session.url)  # → http://localhost:6006
```

Every call to `ObservedLLM.generate()` automatically emits a span to Phoenix when `PHOENIX_ENABLED=true`. Each span includes:
- `llm.model`
- `llm.prompt_tokens` / `llm.completion_tokens`
- `llm.latency_ms`
- `llm.estimated_cost_usd`
- `llm.trace_id`

---

## Database Schema

```sql
CREATE TABLE llm_requests (
    id               INTEGER  PRIMARY KEY AUTOINCREMENT,
    timestamp        DATETIME NOT NULL,          -- UTC
    prompt           TEXT     NOT NULL,
    response         TEXT,
    model_name       VARCHAR(100) NOT NULL,
    latency_ms       FLOAT,                      -- NULL on error
    prompt_tokens    INTEGER,
    completion_tokens INTEGER,
    total_tokens     INTEGER,
    estimated_cost   FLOAT,                      -- USD
    error            TEXT,
    is_error         BOOLEAN  NOT NULL DEFAULT 0,
    feedback_score   FLOAT,                      -- 0.0 – 1.0, nullable
    response_length  INTEGER,
    trace_id         VARCHAR(100)               -- links to OTel span
);
```

---

## Extending the Project

- **Add a new LLM provider**: Subclass `ObservedLLM` or add an adapter in `core/llm_wrapper.py`.
- **PostgreSQL**: Change `DATABASE_URL` to `postgresql+asyncpg://...` and `pip install asyncpg`.
- **LangSmith tracing**: Replace `TracingService` with a LangSmith callback handler and `@traceable` decorator.
- **Alerting webhook**: Add a `_send_alert()` method in `llm_wrapper.py` that POSTs to Slack/PagerDuty.
- **Authentication**: Add `fastapi-users` or OAuth2 middleware to `main.py`.
