"""Streamlit LLM Observability Dashboard.

Reads directly from the SQLite database (no FastAPI dependency required).

Run:
    streamlit run llm_observability/dashboard/app.py
"""

import os
import sqlite3
import time
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------
_DASHBOARD_DIR = os.path.dirname(os.path.abspath(__file__))
_PACKAGE_DIR = os.path.dirname(_DASHBOARD_DIR)
_PROJECT_ROOT = os.path.dirname(_PACKAGE_DIR)
DB_PATH = os.path.join(_PROJECT_ROOT, "llm_observability.db")

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="LLM Observability Dashboard",
    page_icon="🔭",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Minimal dark-theme accent styles
st.markdown(
    """
    <style>
    [data-testid="stMetricValue"] { font-size: 1.6rem; font-weight: 700; }
    [data-testid="stMetricDelta"] { font-size: 0.85rem; }
    .section-header { font-size: 1.1rem; font-weight: 600; color: #a0aec0;
                      text-transform: uppercase; letter-spacing: 0.06em;
                      margin-top: 0.5rem; }
    </style>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Data loading (cached with short TTL for near-real-time feel)
# ---------------------------------------------------------------------------

PLOTLY_TEMPLATE = "plotly_dark"
CHART_MARGIN = dict(l=10, r=10, t=10, b=10)
CHART_HEIGHT = 300


@st.cache_data(ttl=10, show_spinner=False)
def load_data(hours: int, model_filter: str) -> pd.DataFrame:
    """Load raw request rows from SQLite into a DataFrame."""
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()

    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    model_clause = "AND model_name = ?" if model_filter != "All" else ""
    params: list = [since]
    if model_filter != "All":
        params.append(model_filter)

    query = f"""
        SELECT
            id,
            timestamp,
            model_name,
            latency_ms,
            prompt_tokens,
            completion_tokens,
            total_tokens,
            estimated_cost,
            is_error,
            feedback_score,
            response_length,
            SUBSTR(prompt, 1, 120)   AS prompt_preview,
            SUBSTR(response, 1, 200) AS response_preview
        FROM llm_requests
        WHERE timestamp >= ?
        {model_clause}
        ORDER BY timestamp DESC
    """

    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()

    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["is_error"] = df["is_error"].astype(bool)

    return df


@st.cache_data(ttl=30, show_spinner=False)
def get_available_models() -> list[str]:
    if not os.path.exists(DB_PATH):
        return ["All"]
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(
            "SELECT DISTINCT model_name FROM llm_requests ORDER BY model_name", conn
        )
        return ["All"] + df["model_name"].tolist()
    except Exception:
        return ["All"]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("🔭 LLM Observability")
    st.caption("Production monitoring dashboard")
    st.divider()

    st.subheader("Filters")
    time_range = st.selectbox(
        "Time window",
        options=[1, 6, 24, 48, 168],
        index=2,
        format_func=lambda x: {
            1: "Last 1 hour",
            6: "Last 6 hours",
            24: "Last 24 hours",
            48: "Last 48 hours",
            168: "Last 7 days",
        }[x],
    )

    models = get_available_models()
    model_filter = st.selectbox("Model", models)

    st.divider()
    st.subheader("Alert Thresholds")
    latency_threshold = st.slider(
        "Latency alert (ms)", min_value=500, max_value=30_000, value=5_000, step=500
    )
    cost_threshold = st.slider(
        "Cost alert (USD)", min_value=0.01, max_value=1.00, value=0.10, step=0.01
    )

    st.divider()
    auto_refresh = st.checkbox("Auto-refresh (10 s)", value=False)

    st.divider()
    st.caption(f"DB: `{os.path.basename(DB_PATH)}`")
    if st.button("🔄 Refresh now"):
        st.cache_data.clear()
        st.rerun()

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------

df = load_data(time_range, model_filter)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------

st.title("🔭 LLM Observability Dashboard")
st.caption(
    f"Window: last **{time_range}h** · Model: **{model_filter}** · "
    f"Updated: {datetime.now().strftime('%H:%M:%S')}"
)

# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------

if df.empty:
    st.warning(
        "No data found. Run `make seed` to populate sample data, "
        "or start the API and call `POST /api/v1/generate`."
    )
    st.code(
        "# Quick start\n"
        "make seed                  # populate 500 sample records\n"
        "streamlit run llm_observability/dashboard/app.py\n\n"
        "# Or generate live requests:\n"
        "make run-api               # terminal 1\n"
        'curl -s -X POST http://localhost:8000/api/v1/generate \\\n'
        '  -H "Content-Type: application/json" \\\n'
        "  -d '{\"prompt\": \"What is 2+2?\"}'\n",
        language="bash",
    )
    st.stop()

# ---------------------------------------------------------------------------
# Derived metrics
# ---------------------------------------------------------------------------

successful = df[~df["is_error"]]
total_requests = len(df)
avg_latency = successful["latency_ms"].mean() or 0.0
p95_latency = successful["latency_ms"].quantile(0.95) if not successful.empty else 0.0
p50_latency = successful["latency_ms"].quantile(0.50) if not successful.empty else 0.0
p99_latency = successful["latency_ms"].quantile(0.99) if not successful.empty else 0.0
total_cost = df["estimated_cost"].sum()
error_count = df["is_error"].sum()
error_rate = (error_count / total_requests * 100) if total_requests else 0.0
avg_tokens = df["total_tokens"].mean() or 0.0

# ---------------------------------------------------------------------------
# KPI cards
# ---------------------------------------------------------------------------

st.markdown('<div class="section-header">Key Metrics</div>', unsafe_allow_html=True)
col1, col2, col3, col4, col5 = st.columns(5)

with col1:
    st.metric("Total Requests", f"{total_requests:,}")

with col2:
    lat_status = "🔴 HIGH" if avg_latency > latency_threshold else "🟢 OK"
    st.metric("Avg Latency", f"{avg_latency:,.0f} ms", lat_status)

with col3:
    st.metric("p95 Latency", f"{p95_latency:,.0f} ms")

with col4:
    cost_status = "🔴 HIGH" if total_cost > cost_threshold else "🟢 OK"
    st.metric("Total Cost", f"${total_cost:.4f}", cost_status)

with col5:
    err_status = "🔴 HIGH" if error_rate > 5 else "🟢 OK"
    st.metric("Error Rate", f"{error_rate:.1f}%", err_status)

st.divider()

# ---------------------------------------------------------------------------
# Charts — row 1: Latency & Cost over time
# ---------------------------------------------------------------------------

st.markdown('<div class="section-header">Time Series</div>', unsafe_allow_html=True)
col_left, col_right = st.columns(2)

with col_left:
    st.markdown("**Latency Over Time**")
    df_lat = (
        successful.set_index("timestamp")
        .resample("1min")["latency_ms"]
        .agg(avg="mean", maximum="max")
        .reset_index()
        .dropna()
    )

    if not df_lat.empty:
        fig = go.Figure()
        fig.add_trace(
            go.Scatter(
                x=df_lat["timestamp"],
                y=df_lat["avg"],
                name="Avg latency",
                line=dict(color="#4ade80", width=2),
                fill="tozeroy",
                fillcolor="rgba(74,222,128,0.08)",
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df_lat["timestamp"],
                y=df_lat["maximum"],
                name="Max latency",
                line=dict(color="#f87171", width=1.5, dash="dot"),
            )
        )
        fig.add_hline(
            y=latency_threshold,
            line_dash="dash",
            line_color="orange",
            annotation_text=f"Alert ({latency_threshold} ms)",
            annotation_position="top right",
        )
        fig.update_layout(
            template=PLOTLY_TEMPLATE,
            height=CHART_HEIGHT,
            margin=CHART_MARGIN,
            xaxis_title=None,
            yaxis_title="ms",
            legend=dict(orientation="h", y=1.1),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Not enough data to render latency chart.")

with col_right:
    st.markdown("**Cost Over Time**")
    df_cost = (
        df.set_index("timestamp")
        .resample("1min")["estimated_cost"]
        .sum()
        .reset_index()
    )
    df_cost["cumulative"] = df_cost["estimated_cost"].cumsum()

    if not df_cost.empty:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=df_cost["timestamp"],
                y=df_cost["estimated_cost"],
                name="Per minute",
                marker_color="#60a5fa",
                opacity=0.8,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df_cost["timestamp"],
                y=df_cost["cumulative"],
                name="Cumulative",
                line=dict(color="#f59e0b", width=2),
                yaxis="y2",
            )
        )
        fig.add_hline(
            y=cost_threshold,
            line_dash="dash",
            line_color="orange",
            annotation_text=f"Alert (${cost_threshold:.2f})",
            annotation_position="top right",
        )
        fig.update_layout(
            template=PLOTLY_TEMPLATE,
            height=CHART_HEIGHT,
            margin=CHART_MARGIN,
            xaxis_title=None,
            yaxis_title="USD",
            yaxis2=dict(
                title="Cumulative USD",
                overlaying="y",
                side="right",
                showgrid=False,
            ),
            legend=dict(orientation="h", y=1.1),
            barmode="overlay",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Not enough data to render cost chart.")

# ---------------------------------------------------------------------------
# Charts — row 2: Token usage & Requests per minute
# ---------------------------------------------------------------------------

col_left, col_right = st.columns(2)

with col_left:
    st.markdown("**Token Usage Over Time**")
    df_tok = (
        df.set_index("timestamp")
        .resample("1min")[["prompt_tokens", "completion_tokens"]]
        .sum()
        .reset_index()
    )

    if not df_tok.empty:
        fig = go.Figure()
        fig.add_trace(
            go.Bar(
                x=df_tok["timestamp"],
                y=df_tok["prompt_tokens"],
                name="Prompt",
                marker_color="#818cf8",
            )
        )
        fig.add_trace(
            go.Bar(
                x=df_tok["timestamp"],
                y=df_tok["completion_tokens"],
                name="Completion",
                marker_color="#34d399",
            )
        )
        fig.update_layout(
            barmode="stack",
            template=PLOTLY_TEMPLATE,
            height=CHART_HEIGHT,
            margin=CHART_MARGIN,
            xaxis_title=None,
            yaxis_title="Tokens",
            legend=dict(orientation="h", y=1.1),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Not enough data to render token chart.")

with col_right:
    st.markdown("**Requests Per Minute**")
    df_rpm = (
        df.set_index("timestamp")
        .resample("1min")
        .size()
        .reset_index(name="count")
    )

    if not df_rpm.empty:
        fig = px.area(
            df_rpm,
            x="timestamp",
            y="count",
            color_discrete_sequence=["#a78bfa"],
            template=PLOTLY_TEMPLATE,
        )
        fig.update_layout(
            height=CHART_HEIGHT,
            margin=CHART_MARGIN,
            xaxis_title=None,
            yaxis_title="req / min",
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Not enough data to render RPM chart.")

# ---------------------------------------------------------------------------
# Charts — row 3: Latency distribution & Model breakdown
# ---------------------------------------------------------------------------

st.divider()
col_left, col_right = st.columns(2)

with col_left:
    st.markdown("**Latency Distribution**")
    df_valid = successful[successful["latency_ms"].notna()]

    if not df_valid.empty:
        fig = px.histogram(
            df_valid,
            x="latency_ms",
            nbins=40,
            color_discrete_sequence=["#4ade80"],
            template=PLOTLY_TEMPLATE,
        )
        fig.add_vline(
            x=avg_latency,
            line_dash="dash",
            line_color="white",
            annotation_text=f"avg {avg_latency:.0f}ms",
        )
        fig.add_vline(
            x=p95_latency,
            line_dash="dash",
            line_color="#f87171",
            annotation_text=f"p95 {p95_latency:.0f}ms",
        )
        fig.update_layout(
            height=CHART_HEIGHT,
            margin=CHART_MARGIN,
            xaxis_title="Latency (ms)",
            yaxis_title="Count",
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No successful requests to show distribution.")

with col_right:
    st.markdown("**Requests by Model**")
    model_counts = (
        df.groupby("model_name")
        .agg(requests=("id", "count"))
        .reset_index()
    )

    if not model_counts.empty:
        fig = px.pie(
            model_counts,
            values="requests",
            names="model_name",
            color_discrete_sequence=px.colors.qualitative.Set3,
            template=PLOTLY_TEMPLATE,
            hole=0.4,
        )
        fig.update_layout(height=CHART_HEIGHT, margin=CHART_MARGIN)
        fig.update_traces(textposition="inside", textinfo="percent+label")
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No model data available.")

# ---------------------------------------------------------------------------
# Additional KPIs (p50 / p99 / avg tokens)
# ---------------------------------------------------------------------------

st.divider()
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.metric("p50 Latency", f"{p50_latency:,.0f} ms")
with col2:
    st.metric("p99 Latency", f"{p99_latency:,.0f} ms")
with col3:
    st.metric("Avg Tokens / Request", f"{avg_tokens:,.0f}")
with col4:
    avg_feedback = df["feedback_score"].dropna().mean()
    feedback_str = f"{avg_feedback:.2f}" if not pd.isna(avg_feedback) else "—"
    st.metric("Avg Feedback Score", feedback_str)

# ---------------------------------------------------------------------------
# Recent requests table
# ---------------------------------------------------------------------------

st.divider()
st.markdown('<div class="section-header">Recent Requests</div>', unsafe_allow_html=True)

table_col1, table_col2, table_col3 = st.columns([2, 1, 1])
with table_col1:
    show_errors_only = st.checkbox("Errors only")
with table_col2:
    n_rows = st.selectbox("Show rows", [10, 25, 50, 100], index=0, key="n_rows")
with table_col3:
    search_prompt = st.text_input("Search prompt", placeholder="keyword …")

display_df = df.copy()
if show_errors_only:
    display_df = display_df[display_df["is_error"]]
if search_prompt:
    mask = display_df["prompt_preview"].str.contains(
        search_prompt, case=False, na=False
    )
    display_df = display_df[mask]

display_df = display_df.head(n_rows)[
    [
        "timestamp",
        "model_name",
        "latency_ms",
        "total_tokens",
        "estimated_cost",
        "is_error",
        "feedback_score",
        "prompt_preview",
        "response_preview",
    ]
].copy()

display_df.columns = [
    "Timestamp",
    "Model",
    "Latency (ms)",
    "Tokens",
    "Cost (USD)",
    "Error",
    "Feedback",
    "Prompt",
    "Response",
]

display_df["Timestamp"] = display_df["Timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
display_df["Latency (ms)"] = display_df["Latency (ms)"].apply(
    lambda x: f"{x:,.0f}" if pd.notna(x) else "—"
)
display_df["Cost (USD)"] = display_df["Cost (USD)"].apply(
    lambda x: f"${x:.6f}" if pd.notna(x) else "—"
)
display_df["Feedback"] = display_df["Feedback"].apply(
    lambda x: f"{x:.2f}" if pd.notna(x) else "—"
)

st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    column_config={
        "Prompt": st.column_config.TextColumn(width="large"),
        "Response": st.column_config.TextColumn(width="large"),
        "Error": st.column_config.CheckboxColumn(),
    },
)

# ===========================================================================
# Prompt Version Control — A/B comparison panel
# ===========================================================================

st.divider()
st.markdown("## 🔀 Prompt Version Control")
st.caption(
    "Compare latency, cost, and quality across versions of the same prompt template. "
    "Create templates via `POST /api/v1/prompts` or run `make seed`."
)


@st.cache_data(ttl=30, show_spinner=False)
def get_template_names() -> list:
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
    try:
        df_t = pd.read_sql_query(
            "SELECT DISTINCT name FROM prompt_templates WHERE is_active = 1 ORDER BY name",
            conn,
        )
        return df_t["name"].tolist()
    except Exception:
        return []
    finally:
        conn.close()


@st.cache_data(ttl=10, show_spinner=False)
def load_version_metrics(template_name: str, hours: int) -> pd.DataFrame:
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    conn = sqlite3.connect(DB_PATH)
    try:
        query = """
            SELECT
                prompt_template_version                                AS version,
                COUNT(*)                                               AS request_count,
                AVG(CASE WHEN is_error = 0 THEN latency_ms END)       AS avg_latency_ms,
                SUM(COALESCE(estimated_cost, 0))                       AS total_cost,
                AVG(COALESCE(estimated_cost, 0))                       AS avg_cost,
                AVG(feedback_score)                                    AS avg_feedback,
                SUM(CASE WHEN is_error = 1 THEN 1 ELSE 0 END)         AS errors,
                SUM(COALESCE(total_tokens, 0))                         AS total_tokens
            FROM llm_requests
            WHERE prompt_template_name = ?
              AND timestamp >= ?
              AND prompt_template_version IS NOT NULL
            GROUP BY prompt_template_version
            ORDER BY prompt_template_version
        """
        return pd.read_sql_query(query, conn, params=[template_name, since])
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()


@st.cache_data(ttl=60, show_spinner=False)
def load_template_definitions(template_name: str) -> pd.DataFrame:
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    conn = sqlite3.connect(DB_PATH)
    try:
        return pd.read_sql_query(
            """SELECT version, content, system_prompt, description, created_at, is_active
               FROM prompt_templates WHERE name = ? ORDER BY version""",
            conn,
            params=[template_name],
        )
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()


template_names = get_template_names()

if not template_names:
    st.info(
        "No prompt templates yet. "
        "Run `python scripts/seed_data.py` to generate sample templates, "
        "or create one via `POST /api/v1/prompts`."
    )
else:
    pvc_col1, pvc_col2 = st.columns([2, 1])
    with pvc_col1:
        selected_template = st.selectbox("Template to compare", template_names)
    with pvc_col2:
        pvc_hours = st.selectbox(
            "Window",
            [1, 6, 24, 48, 168],
            index=2,
            format_func=lambda x: {1: "1h", 6: "6h", 24: "24h", 48: "48h", 168: "7d"}[x],
            key="pvc_hours",
        )

    comp_df = load_version_metrics(selected_template, pvc_hours)
    defs_df = load_template_definitions(selected_template)

    if comp_df.empty:
        st.info(
            f"No requests recorded for **{selected_template}** in the last {pvc_hours}h. "
            "Seed data includes template-linked requests — run `make seed` to populate."
        )
    else:
        comp_df["error_rate_pct"] = (
            comp_df["errors"] / comp_df["request_count"] * 100
        ).round(2)
        comp_df["version_label"] = comp_df["version"].apply(lambda v: f"v{int(v)}")

        # ---- KPI delta row -------------------------------------------- #
        if len(comp_df) >= 2:
            first = comp_df.iloc[0]
            last = comp_df.iloc[-1]
            d_lat = last["avg_latency_ms"] - first["avg_latency_ms"]
            d_cost = last["avg_cost"] - first["avg_cost"]
            d_fb = (
                (last["avg_feedback"] - first["avg_feedback"])
                if pd.notna(last["avg_feedback"]) and pd.notna(first["avg_feedback"])
                else None
            )
            st.markdown(
                f"**v1 → v{int(last['version'])} delta** — "
                f"Latency: `{d_lat:+.0f}ms` · "
                f"Avg cost: `${d_cost:+.8f}` · "
                f"Feedback: `{d_fb:+.3f}`" if d_fb is not None else
                f"**v1 → v{int(last['version'])} delta** — "
                f"Latency: `{d_lat:+.0f}ms` · "
                f"Avg cost: `${d_cost:+.8f}`"
            )

        # ---- bar charts ------------------------------------------------ #
        vc1, vc2, vc3 = st.columns(3)
        bar_colors = px.colors.qualitative.Set2

        with vc1:
            fig = px.bar(
                comp_df,
                x="version_label",
                y="avg_latency_ms",
                color="version_label",
                color_discrete_sequence=bar_colors,
                template=PLOTLY_TEMPLATE,
                text=comp_df["avg_latency_ms"].round(0).astype(int).astype(str) + "ms",
            )
            fig.update_traces(textposition="outside")
            fig.update_layout(
                title="Avg Latency (ms)",
                height=280,
                margin=CHART_MARGIN,
                showlegend=False,
                xaxis_title=None,
                yaxis_title="ms",
            )
            st.plotly_chart(fig, use_container_width=True)

        with vc2:
            fig = px.bar(
                comp_df,
                x="version_label",
                y="avg_cost",
                color="version_label",
                color_discrete_sequence=bar_colors,
                template=PLOTLY_TEMPLATE,
            )
            fig.update_layout(
                title="Avg Cost / Request (USD)",
                height=280,
                margin=CHART_MARGIN,
                showlegend=False,
                xaxis_title=None,
                yaxis_title="USD",
                yaxis_tickformat=".8f",
            )
            st.plotly_chart(fig, use_container_width=True)

        with vc3:
            fb_data = comp_df.dropna(subset=["avg_feedback"])
            if not fb_data.empty:
                fig = px.bar(
                    fb_data,
                    x="version_label",
                    y="avg_feedback",
                    color="version_label",
                    color_discrete_sequence=bar_colors,
                    template=PLOTLY_TEMPLATE,
                    text=fb_data["avg_feedback"].round(3).astype(str),
                )
                fig.update_traces(textposition="outside")
                fig.update_layout(
                    title="Avg Feedback Score",
                    height=280,
                    margin=CHART_MARGIN,
                    showlegend=False,
                    xaxis_title=None,
                    yaxis=dict(title="score", range=[0, 1.1]),
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.markdown("**Avg Feedback Score**")
                st.info("No feedback scores for this template.")

        # ---- summary table -------------------------------------------- #
        st.markdown("**Version Summary**")
        tbl = comp_df[
            [
                "version_label",
                "request_count",
                "avg_latency_ms",
                "total_cost",
                "avg_feedback",
                "errors",
                "error_rate_pct",
                "total_tokens",
            ]
        ].copy()
        tbl.columns = [
            "Version",
            "Requests",
            "Avg Latency (ms)",
            "Total Cost",
            "Avg Feedback",
            "Errors",
            "Error Rate (%)",
            "Total Tokens",
        ]
        tbl["Avg Latency (ms)"] = tbl["Avg Latency (ms)"].apply(
            lambda x: f"{x:.0f}" if pd.notna(x) else "—"
        )
        tbl["Total Cost"] = tbl["Total Cost"].apply(
            lambda x: f"${x:.6f}" if pd.notna(x) else "—"
        )
        tbl["Avg Feedback"] = tbl["Avg Feedback"].apply(
            lambda x: f"{x:.3f}" if pd.notna(x) else "—"
        )
        st.dataframe(tbl, use_container_width=True, hide_index=True)

        # ---- template content expanders ------------------------------- #
        if not defs_df.empty:
            st.markdown("**Template Content by Version**")
            for _, row in defs_df.iterrows():
                status = "" if row["is_active"] else " 🔴 inactive"
                label = f"v{int(row['version'])}{status}"
                if row["description"]:
                    label += f"  —  {row['description']}"
                with st.expander(label):
                    if row["system_prompt"]:
                        st.markdown("*System prompt:*")
                        st.code(row["system_prompt"], language="text")
                    st.markdown("*User template:*")
                    st.code(row["content"], language="text")
                    st.caption(f"Created: {row['created_at']}")

# ---------------------------------------------------------------------------
# Footer / Phoenix link
# ---------------------------------------------------------------------------

st.divider()
phoenix_url = os.getenv("PHOENIX_ENDPOINT", "http://localhost:6006").replace(
    "/v1/traces", ""
)

col1, col2 = st.columns([3, 1])
with col1:
    st.caption(
        f"Total requests shown: **{len(df):,}** · "
        f"Total cost: **${total_cost:.4f}** · "
        f"DB: `{DB_PATH}`"
    )
with col2:
    st.markdown(
        f"[🔗 Open Phoenix traces]({phoenix_url})",
        help="View distributed traces in Arize Phoenix (must be running)",
    )

# ---------------------------------------------------------------------------
# Auto-refresh (must be last — reruns the whole script after sleep)
# ---------------------------------------------------------------------------

if auto_refresh:
    time.sleep(10)
    st.cache_data.clear()
    st.rerun()
