"""Streamlit LLM Observability Dashboard — premium dark analytics UI.

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
_PACKAGE_DIR   = os.path.dirname(_DASHBOARD_DIR)
_PROJECT_ROOT  = os.path.dirname(_PACKAGE_DIR)
DB_PATH = os.path.join(_PROJECT_ROOT, "llm_observability.db")

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="LLM Observability",
    page_icon="⬡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# CSS — Premium dark analytics theme
# ---------------------------------------------------------------------------
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:ital,wght@0,300;0,400;0,500;0,600;0,700;0,800;0,900&display=swap');

/* ── Variables ───────────────────────────────────────────────────────────── */
:root {
  --bg:         #000000;
  --bg-2:       #0a0a0a;
  --bg-card:    rgba(12,12,12,0.90);
  --border:     rgba(255,255,255,0.055);
  --border-hi:  rgba(99,102,241,0.30);

  --indigo:     #6366f1;
  --violet:     #8b5cf6;
  --cyan:       #06b6d4;
  --emerald:    #10b981;
  --amber:      #f59e0b;
  --rose:       #f43f5e;
  --sky:        #38bdf8;
  --pink:       #ec4899;

  --i-dim:  rgba(99,102,241,0.14);
  --v-dim:  rgba(139,92,246,0.14);
  --c-dim:  rgba(6,182,212,0.14);
  --e-dim:  rgba(16,185,129,0.14);
  --a-dim:  rgba(245,158,11,0.14);
  --r-dim:  rgba(244,63,94,0.14);

  --t1: #f1f5f9;
  --t2: #94a3b8;
  --t3: #64748b;
  --t4: #475569;
}

/* ── Shell ───────────────────────────────────────────────────────────────── */
html, body,
[data-testid="stApp"],
[data-testid="stAppViewContainer"],
[data-testid="stMain"], .main { background: var(--bg) !important; }

[data-testid="stAppViewContainer"] {
  background: #000000 !important;
}

/* ── Typography ──────────────────────────────────────────────────────────── */
*, *::before, *::after { box-sizing: border-box; }
html { font-family: 'Inter', sans-serif !important; }
p, span, label { color: var(--t2) !important; font-family: 'Inter', sans-serif !important; }
div  { font-family: 'Inter', sans-serif !important; }
h1, h2, h3, h4 { color: var(--t1) !important; font-family: 'Inter', sans-serif !important; }

/* ── Chrome ──────────────────────────────────────────────────────────────── */
#MainMenu { visibility: hidden !important; }
footer    { visibility: hidden !important; }
[data-testid="stToolbar"]      { display: none !important; }
.stDeployButton                { display: none !important; }
[data-testid="stStatusWidget"] { display: none !important; }
[data-testid="stHeader"] {
  background: transparent !important;
  border-bottom: none !important;
}

/* ── Sidebar ─────────────────────────────────────────────────────────────── */
[data-testid="stSidebar"] {
  background: #0a0a0a !important;
  border-right: 1px solid rgba(255,255,255,0.06) !important;
}
[data-testid="stSidebar"] .stMarkdown p { color: var(--t2) !important; }
[data-testid="stSidebar"] h1,
[data-testid="stSidebar"] h2,
[data-testid="stSidebar"] h3 { color: var(--t1) !important; }

/* ── Inputs ──────────────────────────────────────────────────────────────── */
[data-testid="stSelectbox"] > div > div,
[data-testid="stTextInput"] > div > div > input {
  background: rgba(13,13,30,0.95) !important;
  border: 1px solid rgba(99,102,241,0.18) !important;
  border-radius: 10px !important;
  color: var(--t1) !important;
}
[data-testid="stSelectbox"] > div > div:focus-within,
[data-testid="stTextInput"] > div > div:focus-within {
  border-color: var(--indigo) !important;
  box-shadow: 0 0 0 3px var(--i-dim) !important;
}
[data-testid="stCheckbox"] label span  { color: var(--t2) !important; }
[data-testid="stSlider"] [class*="thumb"]          { background: var(--indigo) !important; }
[data-testid="stSlider"] [class*="track"]:first-child { background: var(--indigo) !important; }

/* ── Buttons ─────────────────────────────────────────────────────────────── */
[data-testid="baseButton-secondary"] {
  background: var(--i-dim) !important;
  border: 1px solid rgba(99,102,241,0.28) !important;
  color: var(--t1) !important;
  border-radius: 10px !important;
  font-weight: 500 !important;
  transition: all 0.2s ease !important;
}
[data-testid="baseButton-secondary"]:hover {
  background: rgba(99,102,241,0.22) !important;
  border-color: var(--indigo) !important;
  transform: translateY(-1px) !important;
  box-shadow: 0 4px 16px rgba(99,102,241,0.15) !important;
}

/* ── Misc ────────────────────────────────────────────────────────────────── */
hr {
  border: none !important;
  border-top: 1px solid var(--border) !important;
  margin: 10px 0 !important;
}
[data-testid="stDataFrame"] {
  border: 1px solid var(--border) !important;
  border-radius: 14px !important;
  overflow: hidden !important;
}
[data-testid="stDataFrame"] th {
  background: rgba(13,13,30,0.98) !important;
  color: var(--t3) !important;
  font-size: 0.68rem !important;
  font-weight: 700 !important;
  letter-spacing: 0.08em !important;
  text-transform: uppercase !important;
}
code, pre {
  background: rgba(13,13,30,0.95) !important;
  border: 1px solid rgba(99,102,241,0.15) !important;
  border-radius: 8px !important;
  color: var(--cyan) !important;
  font-size: 0.77rem !important;
}
[data-testid="stExpander"] {
  background: var(--bg-card) !important;
  border: 1px solid var(--border) !important;
  border-radius: 12px !important;
}
[data-testid="stAlert"] {
  background: var(--bg-card) !important;
  border: 1px solid rgba(99,102,241,0.20) !important;
  border-radius: 12px !important;
}

/* =========================================================================
   KEYFRAMES
   ========================================================================= */
@keyframes fadeUp {
  from { opacity: 0; transform: translateY(20px); }
  to   { opacity: 1; transform: translateY(0);    }
}
@keyframes shimmer {
  0%   { background-position: 0%   50%; }
  50%  { background-position: 100% 50%; }
  100% { background-position: 0%   50%; }
}
@keyframes ping {
  0%, 100% { opacity: 1;   transform: scale(1);    }
  50%       { opacity: 0.4; transform: scale(0.85); }
}
@keyframes sectionReveal {
  from { opacity: 0; transform: translateX(-10px); }
  to   { opacity: 1; transform: translateX(0);     }
}
@keyframes haloBreath {
  0%, 100% { box-shadow: 0 0 0   0 rgba(99,102,241,0);    }
  50%       { box-shadow: 0 0 24px 0 rgba(99,102,241,0.14);}
}

/* =========================================================================
   KPI CARDS
   ========================================================================= */
/* Equal-height columns */
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] > [data-testid="stVerticalBlock"],
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] .stMarkdown,
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] .stMarkdown > div,
[data-testid="stHorizontalBlock"] > [data-testid="stColumn"] .kpi-card { height: 100%; }

.kpi-card {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 22px 22px 18px;
  backdrop-filter: blur(24px);
  -webkit-backdrop-filter: blur(24px);
  position: relative;
  overflow: hidden;
  min-height: 158px;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  transition: border-color 0.3s, transform 0.3s, box-shadow 0.3s;
  animation: fadeUp 0.55s cubic-bezier(0.16,1,0.3,1) both;
}
.kpi-card:hover {
  transform: translateY(-4px);
  border-color: rgba(99,102,241,0.28);
  box-shadow:
    0 16px 50px rgba(0,0,0,0.45),
    0 0 28px rgba(99,102,241,0.08);
}
/* Animated top gradient bar */
.kpi-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0; height: 2px;
  border-radius: 20px 20px 0 0;
  background-size: 300% 300%;
  animation: shimmer 6s ease infinite;
}
/* Soft corner glow */
.kpi-card::after {
  content: '';
  position: absolute;
  top: -30%; right: -10%;
  width: 110px; height: 110px;
  border-radius: 50%;
  opacity: 0.07;
  filter: blur(28px);
}
/* Stagger */
.k1 { animation-delay: 0.05s; }
.k2 { animation-delay: 0.11s; }
.k3 { animation-delay: 0.17s; }
.k4 { animation-delay: 0.23s; }
.k5 { animation-delay: 0.29s; }

/* Color skins */
.ci::before { background-image: linear-gradient(90deg,#6366f1,#8b5cf6,#06b6d4,#6366f1); }
.ci::after  { background: #6366f1; }
.cc::before { background-image: linear-gradient(90deg,#06b6d4,#38bdf8,#06b6d4); }
.cc::after  { background: #06b6d4; }
.ce::before { background-image: linear-gradient(90deg,#10b981,#34d399,#10b981); }
.ce::after  { background: #10b981; }
.ca::before { background-image: linear-gradient(90deg,#f59e0b,#fbbf24,#f59e0b); }
.ca::after  { background: #f59e0b; }
.cr::before { background-image: linear-gradient(90deg,#f43f5e,#fb7185,#f43f5e); }
.cr::after  { background: #f43f5e; }
.cv::before { background-image: linear-gradient(90deg,#8b5cf6,#a78bfa,#8b5cf6); }
.cv::after  { background: #8b5cf6; }

.kpi-label {
  font-size: 0.65rem;
  font-weight: 700;
  letter-spacing: 0.11em;
  text-transform: uppercase;
  color: var(--t4) !important;
  margin-bottom: 5px;
}
.kpi-value {
  font-size: 2.6rem;
  font-weight: 800;
  color: var(--t1) !important;
  line-height: 1;
  letter-spacing: -0.04em;
  font-variant-numeric: tabular-nums;
  margin-bottom: 2px;
}
.kpi-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-top: 8px;
}
.kpi-badge {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.63rem;
  font-weight: 700;
  padding: 3px 9px;
  border-radius: 20px;
  letter-spacing: 0.04em;
}
.bok  { background: var(--e-dim); color: var(--emerald) !important; }
.bwarn{ background: var(--a-dim); color: var(--amber)   !important; }
.berr { background: var(--r-dim); color: var(--rose)    !important; }
.binf { background: var(--i-dim); color: var(--indigo)  !important; }
.bvio { background: var(--v-dim); color: var(--violet)  !important; }
.bcyn { background: var(--c-dim); color: var(--cyan)    !important; }

.kpi-sub {
  font-size: 0.63rem;
  color: var(--t4) !important;
  margin-top: 1px;
}

/* =========================================================================
   SECTION HEADERS
   ========================================================================= */
.sec {
  font-size: 0.63rem;
  font-weight: 700;
  letter-spacing: 0.13em;
  text-transform: uppercase;
  color: var(--t3) !important;
  margin: 30px 0 16px;
  display: flex;
  align-items: center;
  gap: 10px;
  animation: sectionReveal 0.4s ease both;
}
.sec::before {
  content: '';
  width: 3px; height: 15px;
  background: linear-gradient(to bottom, var(--indigo), var(--violet));
  border-radius: 3px;
  flex-shrink: 0;
}
.sec::after {
  content: '';
  flex: 1; height: 1px;
  background: linear-gradient(to right, rgba(99,102,241,0.18), transparent);
}

/* =========================================================================
   PAGE HEADER
   ========================================================================= */
.ph {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  padding: 8px 0 24px;
}
.ph-title {
  font-size: 1.95rem;
  font-weight: 900;
  line-height: 1;
  letter-spacing: -0.045em;
  color: var(--t1) !important;
}
.ph-title .g {
  background: linear-gradient(130deg, #6366f1 0%, #8b5cf6 40%, #06b6d4 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}
.ph-sub { font-size: 0.72rem; color: var(--t4) !important; margin-top: 6px; }
.pills  { display: flex; gap: 8px; align-items: center; }
.pill {
  display: inline-flex; align-items: center; gap: 6px;
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 5px 14px;
  font-size: 0.67rem;
  color: var(--t2) !important;
  backdrop-filter: blur(12px);
}
.live {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--emerald);
  display: inline-block;
  animation: ping 2.2s ease-in-out infinite;
}

/* =========================================================================
   CHART CARDS
   ========================================================================= */
.cc-wrap {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 18px;
  padding: 18px 16px 4px;
  backdrop-filter: blur(18px);
  margin-bottom: 14px;
  transition: border-color 0.3s, box-shadow 0.3s;
  animation: fadeUp 0.5s cubic-bezier(0.16,1,0.3,1) both;
}
.cc-wrap:hover {
  border-color: rgba(99,102,241,0.22);
  box-shadow: 0 10px 36px rgba(0,0,0,0.38);
}
.cc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 4px;
}
.cc-title { font-size: 0.75rem; font-weight: 600; color: var(--t2) !important; }
.cc-tag {
  font-size: 0.60rem; font-weight: 700;
  background: var(--i-dim);
  border: 1px solid rgba(99,102,241,0.22);
  border-radius: 6px;
  padding: 2px 7px;
  color: var(--indigo) !important;
  letter-spacing: 0.05em;
}

/* =========================================================================
   VERSION CONTROL
   ========================================================================= */
.delta-row {
  background: var(--bg-card);
  border: 1px solid var(--border);
  border-radius: 12px;
  padding: 14px 22px;
  display: flex; gap: 28px; align-items: center; flex-wrap: wrap;
  margin: 12px 0;
  animation: fadeUp 0.4s ease both;
}
.delta-item { font-size: 0.77rem; color: var(--t2) !important; }
.delta-item .lbl {
  color: var(--t4) !important;
  font-size: 0.62rem; font-weight: 700;
  text-transform: uppercase; letter-spacing: 0.08em;
  display: block; margin-bottom: 2px;
}
.dup  { color: var(--rose)    !important; font-weight: 700; }
.ddown{ color: var(--emerald) !important; font-weight: 700; }
.ver-chip {
  display: inline-block;
  background: var(--v-dim); color: var(--violet) !important;
  border-radius: 6px; padding: 2px 8px;
  font-size: 0.67rem; font-weight: 700; margin-right: 4px;
}
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spark(values: list, color: str = "#6366f1") -> str:
    """Return a tiny inline SVG sparkline from a list of floats."""
    vals = [v for v in values if v is not None and not (isinstance(v, float) and (v != v))]
    if len(vals) < 3:
        return ""
    W, H = 72, 28
    mn, mx = min(vals), max(vals)
    if mx == mn:
        mn -= 1; mx += 1
    pts = [
        f"{i / (len(vals)-1) * W:.1f},{H - (v - mn) / (mx - mn) * H:.1f}"
        for i, v in enumerate(vals)
    ]
    path = "M" + " L".join(pts)
    return (
        f'<svg width="{W}" height="{H}" viewBox="0 0 {W} {H}" fill="none" '
        f'xmlns="http://www.w3.org/2000/svg">'
        f'<path d="{path}" stroke="{color}" stroke-width="1.8" '
        f'stroke-linecap="round" stroke-linejoin="round"/>'
        f'</svg>'
    )


def _kpi(
    label: str,
    value: str,
    badge: str,
    bcls: str,
    sub: str,
    skin: str,
    stagger: int = 1,
    spark_vals: list | None = None,
    spark_color: str = "#6366f1",
) -> str:
    spark_html = (
        f'<div class="spark-wrap">{_spark(spark_vals, spark_color)}</div>'
        if spark_vals else ""
    )
    badge_html = f'<span class="kpi-badge {bcls}">{badge}</span>' if badge else ""
    sub_html   = f'<div class="kpi-sub">{sub}</div>' if sub else ""
    return f"""
    <div class="kpi-card {skin} k{stagger}">
      <div>
        <div class="kpi-label">{label}</div>
        <div class="kpi-value">{value}</div>
        {sub_html}
      </div>
      <div class="kpi-footer">
        {badge_html}
        {spark_html}
      </div>
    </div>"""


def _sec(text: str) -> str:
    return f'<div class="sec">{text}</div>'


def _cc(title: str, tag: str = "") -> str:
    tag_html = f'<span class="cc-tag">{tag}</span>' if tag else ""
    return f'<div class="cc-wrap"><div class="cc-head"><span class="cc-title">{title}</span>{tag_html}</div>'


CHART_H = 292

# Indigo-to-violet gradient fill helper
def _grad_fill(color_hex: str, opacity: float = 0.18) -> str:
    r = int(color_hex[1:3], 16)
    g = int(color_hex[3:5], 16)
    b = int(color_hex[5:7], 16)
    return f"rgba({r},{g},{b},{opacity})"


def _layout(h: int = CHART_H, **kw) -> dict:
    base = dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Inter,sans-serif", color="#64748b", size=11),
        height=h,
        margin=dict(l=8, r=8, t=8, b=8),
        xaxis=dict(
            showgrid=True, gridcolor="rgba(255,255,255,0.04)", gridwidth=1,
            zeroline=False, tickfont=dict(size=10, color="#475569"),
            linecolor="rgba(255,255,255,0.05)",
        ),
        yaxis=dict(
            showgrid=True, gridcolor="rgba(255,255,255,0.04)", gridwidth=1,
            zeroline=False, tickfont=dict(size=10, color="#475569"),
            linecolor="rgba(255,255,255,0.05)",
        ),
        legend=dict(
            orientation="h", y=1.12, x=0,
            font=dict(size=10, color="#64748b"), bgcolor="rgba(0,0,0,0)",
        ),
        hoverlabel=dict(
            bgcolor="#0d0d1f",
            font=dict(family="Inter,sans-serif", size=11, color="#f1f5f9"),
            bordercolor="rgba(99,102,241,0.30)",
        ),
    )
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

@st.cache_data(ttl=10, show_spinner=False)
def load_data(hours: int, model_filter: str) -> pd.DataFrame:
    if not os.path.exists(DB_PATH):
        return pd.DataFrame()
    since = (datetime.utcnow() - timedelta(hours=hours)).isoformat()
    mc = "AND model_name = ?" if model_filter != "All" else ""
    params: list = [since] + ([model_filter] if model_filter != "All" else [])
    q = f"""
        SELECT id, timestamp, model_name, latency_ms,
               prompt_tokens, completion_tokens, total_tokens,
               estimated_cost, is_error, feedback_score, response_length,
               SUBSTR(prompt,   1, 120) AS prompt_preview,
               SUBSTR(response, 1, 200) AS response_preview
        FROM llm_requests
        WHERE timestamp >= ? {mc}
        ORDER BY timestamp DESC
    """
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(q, conn, params=params)
    conn.close()
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["is_error"]  = df["is_error"].astype(bool)
    return df


@st.cache_data(ttl=30, show_spinner=False)
def get_available_models() -> list:
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


@st.cache_data(ttl=30, show_spinner=False)
def get_template_names() -> list:
    if not os.path.exists(DB_PATH):
        return []
    conn = sqlite3.connect(DB_PATH)
    try:
        df = pd.read_sql_query(
            "SELECT DISTINCT name FROM prompt_templates WHERE is_active=1 ORDER BY name", conn
        )
        return df["name"].tolist()
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
        return pd.read_sql_query(
            """
            SELECT
                prompt_template_version                                AS version,
                COUNT(*)                                               AS request_count,
                AVG(CASE WHEN is_error=0 THEN latency_ms END)         AS avg_latency_ms,
                SUM(COALESCE(estimated_cost,0))                        AS total_cost,
                AVG(COALESCE(estimated_cost,0))                        AS avg_cost,
                AVG(feedback_score)                                    AS avg_feedback,
                SUM(CASE WHEN is_error=1 THEN 1 ELSE 0 END)           AS errors,
                SUM(COALESCE(total_tokens,0))                          AS total_tokens
            FROM llm_requests
            WHERE prompt_template_name=? AND timestamp>=?
              AND prompt_template_version IS NOT NULL
            GROUP BY prompt_template_version
            ORDER BY prompt_template_version
            """,
            conn, params=[template_name, since],
        )
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
               FROM prompt_templates WHERE name=? ORDER BY version""",
            conn, params=[template_name],
        )
    except Exception:
        return pd.DataFrame()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sidebar
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown(
        """
        <div style='padding:12px 0 8px'>
          <div style='font-size:1.3rem;font-weight:900;color:#f1f5f9;letter-spacing:-0.03em;line-height:1'>
            ⬡ LLM Observe
          </div>
          <div style='font-size:0.68rem;color:#475569;margin-top:4px'>
            Production monitoring dashboard
          </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("<hr/>", unsafe_allow_html=True)

    st.markdown(
        "<div style='font-size:0.62rem;font-weight:700;letter-spacing:0.12em;"
        "text-transform:uppercase;color:#64748b;margin-bottom:10px'>Filters</div>",
        unsafe_allow_html=True,
    )
    time_range = st.selectbox(
        "Time window",
        options=[1, 6, 24, 48, 168],
        index=2,
        format_func=lambda x: {
            1: "Last 1 hour", 6: "Last 6 hours", 24: "Last 24 hours",
            48: "Last 48 hours", 168: "Last 7 days",
        }[x],
    )
    models = get_available_models()
    model_filter = st.selectbox("Model", models)

    st.markdown("<hr/>", unsafe_allow_html=True)
    st.markdown(
        "<div style='font-size:0.62rem;font-weight:700;letter-spacing:0.12em;"
        "text-transform:uppercase;color:#64748b;margin-bottom:10px'>Alert Thresholds</div>",
        unsafe_allow_html=True,
    )
    latency_threshold = st.slider("Latency (ms)", 500, 30_000, 5_000, 500)
    cost_threshold    = st.slider("Cost (USD)",   0.01, 1.00,  0.10,  0.01)

    st.markdown("<hr/>", unsafe_allow_html=True)
    auto_refresh = st.checkbox("Auto-refresh (10 s)", value=False)
    if st.button("Refresh now"):
        st.cache_data.clear()
        st.rerun()

    st.markdown(
        f"<div style='font-size:0.65rem;color:#475569;margin-top:14px'>"
        f"<code style='color:#64748b;font-size:0.60rem'>{os.path.basename(DB_PATH)}</code>"
        f"</div>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Load data
# ---------------------------------------------------------------------------
df = load_data(time_range, model_filter)

# ---------------------------------------------------------------------------
# Page header
# ---------------------------------------------------------------------------
st.markdown(
    f"""
    <div class="ph">
      <div>
        <div class="ph-title">LLM <span class="g">Observability</span></div>
        <div class="ph-sub">
          Window: last {time_range}h &nbsp;·&nbsp; Model: {model_filter}
          &nbsp;·&nbsp; {datetime.now().strftime('%H:%M:%S')}
        </div>
      </div>
      <div class="pills">
        <div class="pill"><span class="live"></span>&thinsp;Live</div>
        <div class="pill">{os.path.basename(DB_PATH)}</div>
      </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------
if df.empty:
    st.warning("No data. Run `make seed` to populate sample records.")
    st.code("make seed\nstreamlit run llm_observability/dashboard/app.py", language="bash")
    st.stop()

# ---------------------------------------------------------------------------
# Derived metrics
# ---------------------------------------------------------------------------
ok         = df[~df["is_error"]]
total_req  = len(df)
avg_lat    = ok["latency_ms"].mean()   or 0.0
p50_lat    = ok["latency_ms"].quantile(0.50) if not ok.empty else 0.0
p95_lat    = ok["latency_ms"].quantile(0.95) if not ok.empty else 0.0
p99_lat    = ok["latency_ms"].quantile(0.99) if not ok.empty else 0.0
total_cost = df["estimated_cost"].sum()
err_count  = int(df["is_error"].sum())
err_rate   = (err_count / total_req * 100) if total_req else 0.0
avg_tokens = df["total_tokens"].mean() or 0.0
avg_fb     = df["feedback_score"].dropna().mean()

# Sparkline series (30 one-minute buckets)
def _spark_series(series: pd.Series, resample: str = "1min") -> list:
    try:
        return (
            series.set_axis(df["timestamp"])
            .resample(resample)
            .mean()
            .dropna()
            .tail(30)
            .tolist()
        )
    except Exception:
        return []

spark_lat  = _spark_series(ok["latency_ms"].reset_index(drop=True) if not ok.empty else pd.Series(dtype=float))
spark_cost = _spark_series(df["estimated_cost"].reset_index(drop=True))
spark_tok  = _spark_series(df["total_tokens"].reset_index(drop=True))

req_spark = (
    df.set_index("timestamp")
    .resample("1min")
    .size()
    .tail(30)
    .tolist()
)

# ---------------------------------------------------------------------------
# KPI row
# ---------------------------------------------------------------------------
st.markdown(_sec("Key Metrics"), unsafe_allow_html=True)
c1, c2, c3, c4, c5 = st.columns(5)

with c1:
    st.markdown(
        _kpi("Total Requests", f"{total_req:,}", "Live", "binf", "", "ci k1",
             1, req_spark, "#6366f1"),
        unsafe_allow_html=True,
    )
with c2:
    hi = avg_lat > latency_threshold
    st.markdown(
        _kpi("Avg Latency", f"{avg_lat:,.0f}",
             "HIGH" if hi else "Normal", "berr" if hi else "bok",
             "milliseconds", "cr k2" if hi else "cc k2",
             2, spark_lat, "#f43f5e" if hi else "#06b6d4"),
        unsafe_allow_html=True,
    )
with c3:
    st.markdown(
        _kpi("p95 Latency", f"{p95_lat:,.0f}", "95th pct", "bvio", "ms",
             "cv k3", 3, spark_lat, "#8b5cf6"),
        unsafe_allow_html=True,
    )
with c4:
    hi = total_cost > cost_threshold
    st.markdown(
        _kpi("Total Cost", f"${total_cost:.4f}",
             "HIGH" if hi else "Normal", "berr" if hi else "bok",
             "USD", "cr k4" if hi else "ce k4",
             4, spark_cost, "#f43f5e" if hi else "#10b981"),
        unsafe_allow_html=True,
    )
with c5:
    hi = err_rate > 5
    st.markdown(
        _kpi("Error Rate", f"{err_rate:.1f}%",
             "HIGH" if hi else "Healthy", "berr" if hi else "bok",
             f"{err_count} of {total_req}", "cr k5" if hi else "ci k5",
             5),
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Time Series — Latency & Cost
# ---------------------------------------------------------------------------
st.markdown(_sec("Time Series"), unsafe_allow_html=True)
col1, col2 = st.columns(2)

with col1:
    st.markdown(_cc("Latency Over Time", "1-min"), unsafe_allow_html=True)
    df_lat = (
        ok.set_index("timestamp")
        .resample("1min")["latency_ms"]
        .agg(avg="mean", p95=lambda x: x.quantile(0.95))
        .reset_index().dropna()
    )
    if not df_lat.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_lat["timestamp"], y=df_lat["avg"],
            name="Avg latency",
            line=dict(color="#6366f1", width=2.5, shape="spline"),
            fill="tozeroy",
            fillcolor=_grad_fill("#6366f1", 0.10),
        ))
        fig.add_trace(go.Scatter(
            x=df_lat["timestamp"], y=df_lat["p95"],
            name="p95",
            line=dict(color="#8b5cf6", width=1.5, dash="dot", shape="spline"),
        ))
        fig.add_hline(
            y=latency_threshold, line_dash="dash", line_color="#f59e0b",
            annotation_text=f"Alert  {latency_threshold}ms",
            annotation_font_color="#f59e0b", annotation_font_size=10,
        )
        fig.update_layout(**_layout(CHART_H, yaxis_title="ms"))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Not enough data.")
    st.markdown("</div>", unsafe_allow_html=True)

with col2:
    st.markdown(_cc("Cost Over Time", "1-min"), unsafe_allow_html=True)
    df_cost = (
        df.set_index("timestamp")
        .resample("1min")["estimated_cost"]
        .sum().reset_index()
    )
    df_cost["cum"] = df_cost["estimated_cost"].cumsum()
    if not df_cost.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_cost["timestamp"], y=df_cost["estimated_cost"],
            name="Per min",
            marker=dict(color="#06b6d4", opacity=0.65,
                        line=dict(width=0)),
        ))
        fig.add_trace(go.Scatter(
            x=df_cost["timestamp"], y=df_cost["cum"],
            name="Cumulative",
            line=dict(color="#f59e0b", width=2, shape="spline"),
            yaxis="y2",
        ))
        fig.add_hline(
            y=cost_threshold, line_dash="dash", line_color="#f43f5e",
            annotation_text=f"Alert  ${cost_threshold:.2f}",
            annotation_font_color="#f43f5e", annotation_font_size=10,
        )
        layout = _layout(
            CHART_H, yaxis_title="USD",
            yaxis2=dict(
                title="Cumulative", overlaying="y", side="right",
                showgrid=False, tickfont=dict(size=10, color="#475569"),
            ),
            barmode="overlay",
        )
        fig.update_layout(**layout)
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Not enough data.")
    st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Token usage & Requests per minute
# ---------------------------------------------------------------------------
col1, col2 = st.columns(2)

with col1:
    st.markdown(_cc("Token Usage", "stacked"), unsafe_allow_html=True)
    df_tok = (
        df.set_index("timestamp")
        .resample("1min")[["prompt_tokens", "completion_tokens"]]
        .sum().reset_index()
    )
    if not df_tok.empty:
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=df_tok["timestamp"], y=df_tok["prompt_tokens"],
            name="Prompt", marker_color="#6366f1", marker_opacity=0.85,
        ))
        fig.add_trace(go.Bar(
            x=df_tok["timestamp"], y=df_tok["completion_tokens"],
            name="Completion", marker_color="#06b6d4", marker_opacity=0.85,
        ))
        fig.update_layout(**_layout(CHART_H, barmode="stack", yaxis_title="Tokens"))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Not enough data.")
    st.markdown("</div>", unsafe_allow_html=True)

with col2:
    st.markdown(_cc("Requests / Minute", "volume"), unsafe_allow_html=True)
    df_rpm = (
        df.set_index("timestamp").resample("1min").size().reset_index(name="count")
    )
    if not df_rpm.empty:
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_rpm["timestamp"], y=df_rpm["count"],
            fill="tozeroy",
            line=dict(color="#8b5cf6", width=2.5, shape="spline"),
            fillcolor=_grad_fill("#8b5cf6", 0.10),
            name="req/min",
        ))
        fig.update_layout(**_layout(CHART_H, yaxis_title="req / min", showlegend=False))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Not enough data.")
    st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Distribution & Model breakdown
# ---------------------------------------------------------------------------
st.markdown(_sec("Distribution & Breakdown"), unsafe_allow_html=True)
col1, col2 = st.columns(2)

with col1:
    st.markdown(_cc("Latency Distribution", "histogram"), unsafe_allow_html=True)
    df_v = ok[ok["latency_ms"].notna()]
    if not df_v.empty:
        fig = px.histogram(
            df_v, x="latency_ms", nbins=40,
            color_discrete_sequence=["#6366f1"],
        )
        fig.update_traces(marker_opacity=0.75, marker_line_width=0)
        fig.add_vline(x=avg_lat, line_dash="dash", line_color="#10b981",
                      annotation_text=f"avg {avg_lat:.0f}ms",
                      annotation_font_color="#10b981", annotation_font_size=10)
        fig.add_vline(x=p95_lat, line_dash="dash", line_color="#f43f5e",
                      annotation_text=f"p95 {p95_lat:.0f}ms",
                      annotation_font_color="#f43f5e", annotation_font_size=10)
        fig.update_layout(**_layout(CHART_H, xaxis_title="Latency (ms)",
                                    yaxis_title="Count", showlegend=False))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No successful requests.")
    st.markdown("</div>", unsafe_allow_html=True)

with col2:
    st.markdown(_cc("Requests by Model", "donut"), unsafe_allow_html=True)
    mc = df.groupby("model_name").agg(requests=("id", "count")).reset_index()
    if not mc.empty:
        fig = px.pie(
            mc, values="requests", names="model_name", hole=0.58,
            color_discrete_sequence=["#6366f1", "#8b5cf6", "#06b6d4", "#10b981", "#f59e0b"],
        )
        fig.update_traces(
            textposition="inside", textinfo="percent",
            textfont=dict(size=11, color="#f1f5f9"),
            marker=dict(line=dict(color="rgba(0,0,0,0)", width=0)),
            pull=[0.03] * len(mc),
        )
        fig.update_layout(**_layout(
            CHART_H,
            legend=dict(
                orientation="v", x=0.78, y=0.5,
                font=dict(size=10, color="#64748b"),
                bgcolor="rgba(0,0,0,0)",
            ),
        ))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("No model data.")
    st.markdown("</div>", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Secondary KPIs
# ---------------------------------------------------------------------------
st.markdown(_sec("Percentile Stats"), unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)

with c1:
    st.markdown(
        _kpi("p50 Latency", f"{p50_lat:,.0f}", "median", "binf", "ms", "ci k1",
             1, spark_lat, "#6366f1"),
        unsafe_allow_html=True,
    )
with c2:
    st.markdown(
        _kpi("p99 Latency", f"{p99_lat:,.0f}", "99th pct", "bvio", "ms", "cv k2",
             2, spark_lat, "#8b5cf6"),
        unsafe_allow_html=True,
    )
with c3:
    st.markdown(
        _kpi("Avg Tokens / Req", f"{avg_tokens:,.0f}", "total", "bcyn", "tokens", "cc k3",
             3, spark_tok, "#06b6d4"),
        unsafe_allow_html=True,
    )
with c4:
    fb_str = f"{avg_fb:.2f}" if not pd.isna(avg_fb) else "—"
    st.markdown(
        _kpi("Avg Feedback", fb_str, "quality", "bok", "0 – 1.0 scale", "ce k4", 4),
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Recent requests table
# ---------------------------------------------------------------------------
st.markdown(_sec("Recent Requests"), unsafe_allow_html=True)

f1, f2, f3 = st.columns([2, 1, 1])
with f1:
    show_errors_only = st.checkbox("Errors only")
with f2:
    n_rows = st.selectbox("Show rows", [10, 25, 50, 100], index=0, key="n_rows")
with f3:
    search = st.text_input("Search prompt", placeholder="keyword …")

disp = df.copy()
if show_errors_only:
    disp = disp[disp["is_error"]]
if search:
    disp = disp[disp["prompt_preview"].str.contains(search, case=False, na=False)]

disp = disp.head(n_rows)[
    ["timestamp", "model_name", "latency_ms", "total_tokens",
     "estimated_cost", "is_error", "feedback_score",
     "prompt_preview", "response_preview"]
].copy()

disp.columns = ["Timestamp", "Model", "Latency (ms)", "Tokens",
                "Cost (USD)", "Error", "Feedback", "Prompt", "Response"]
disp["Timestamp"]    = disp["Timestamp"].dt.strftime("%Y-%m-%d %H:%M:%S")
disp["Latency (ms)"] = disp["Latency (ms)"].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else "—")
disp["Cost (USD)"]   = disp["Cost (USD)"].apply(lambda x: f"${x:.6f}" if pd.notna(x) else "—")
disp["Feedback"]     = disp["Feedback"].apply(lambda x: f"{x:.2f}" if pd.notna(x) else "—")

st.dataframe(
    disp, use_container_width=True, hide_index=True,
    column_config={
        "Prompt":   st.column_config.TextColumn(width="large"),
        "Response": st.column_config.TextColumn(width="large"),
        "Error":    st.column_config.CheckboxColumn(),
    },
)

# ===========================================================================
# Prompt Version Control
# ===========================================================================
st.markdown(_sec("Prompt Version Control"), unsafe_allow_html=True)
st.markdown(
    "<div style='font-size:0.74rem;color:#475569;margin-bottom:16px'>"
    "Compare latency, cost, and quality across versions of the same prompt template.</div>",
    unsafe_allow_html=True,
)

template_names = get_template_names()

if not template_names:
    st.info("No prompt templates. Run `python scripts/seed_data.py` to generate samples.")
else:
    pvc1, pvc2 = st.columns([3, 1])
    with pvc1:
        selected_tpl = st.selectbox("Template to compare", template_names)
    with pvc2:
        pvc_hours = st.selectbox(
            "Window", [1, 6, 24, 48, 168], index=2,
            format_func=lambda x: {1:"1h",6:"6h",24:"24h",48:"48h",168:"7d"}[x],
            key="pvc_hours",
        )

    comp_df = load_version_metrics(selected_tpl, pvc_hours)
    defs_df = load_template_definitions(selected_tpl)

    if comp_df.empty:
        st.info(f"No requests for **{selected_tpl}** in the last {pvc_hours}h.")
    else:
        comp_df["error_rate_pct"] = (comp_df["errors"] / comp_df["request_count"] * 100).round(2)
        comp_df["version_label"]  = comp_df["version"].apply(lambda v: f"v{int(v)}")

        if len(comp_df) >= 2:
            first, last = comp_df.iloc[0], comp_df.iloc[-1]
            d_lat  = last["avg_latency_ms"] - first["avg_latency_ms"]
            d_cost = last["avg_cost"]        - first["avg_cost"]
            d_fb   = (
                (last["avg_feedback"] - first["avg_feedback"])
                if pd.notna(last["avg_feedback"]) and pd.notna(first["avg_feedback"]) else None
            )
            fb_html = (
                f'<div class="delta-item"><span class="lbl">Feedback delta</span>'
                f'<span class="{"ddown" if d_fb and d_fb > 0 else "dup"}">'
                f'{d_fb:+.3f}</span></div>' if d_fb is not None else ""
            )
            st.markdown(
                f"""<div class="delta-row">
                <div class="delta-item" style="font-size:0.70rem;color:#475569">
                  <span class="ver-chip">v1</span> → <span class="ver-chip">v{int(last['version'])}</span>
                </div>
                <div class="delta-item">
                  <span class="lbl">Latency delta</span>
                  <span class="{"dup" if d_lat > 0 else "ddown"}">{d_lat:+.0f} ms</span>
                </div>
                <div class="delta-item">
                  <span class="lbl">Cost delta</span>
                  <span class="{"dup" if d_cost > 0 else "ddown"}">${d_cost:+.8f}</span>
                </div>
                {fb_html}
                </div>""",
                unsafe_allow_html=True,
            )

        # Bar charts
        vc1, vc2, vc3 = st.columns(3)
        BCOLS = ["#6366f1", "#8b5cf6", "#06b6d4", "#10b981"]

        with vc1:
            st.markdown(_cc("Avg Latency"), unsafe_allow_html=True)
            fig = px.bar(comp_df, x="version_label", y="avg_latency_ms",
                         color="version_label", color_discrete_sequence=BCOLS,
                         text=comp_df["avg_latency_ms"].round(0).astype(int).astype(str)+"ms")
            fig.update_traces(textposition="outside", textfont_size=10, marker_line_width=0)
            fig.update_layout(**_layout(260, xaxis_title=None, yaxis_title="ms", showlegend=False))
            st.plotly_chart(fig, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

        with vc2:
            st.markdown(_cc("Avg Cost / Req"), unsafe_allow_html=True)
            fig = px.bar(comp_df, x="version_label", y="avg_cost",
                         color="version_label", color_discrete_sequence=BCOLS)
            fig.update_traces(marker_line_width=0)
            fig.update_layout(**_layout(260, xaxis_title=None, yaxis_title="USD",
                                        yaxis_tickformat=".8f", showlegend=False))
            st.plotly_chart(fig, use_container_width=True)
            st.markdown("</div>", unsafe_allow_html=True)

        with vc3:
            st.markdown(_cc("Avg Feedback Score"), unsafe_allow_html=True)
            fb_d = comp_df.dropna(subset=["avg_feedback"])
            if not fb_d.empty:
                fig = px.bar(fb_d, x="version_label", y="avg_feedback",
                             color="version_label", color_discrete_sequence=BCOLS,
                             text=fb_d["avg_feedback"].round(3).astype(str))
                fig.update_traces(textposition="outside", textfont_size=10, marker_line_width=0)
                fig.update_layout(**_layout(
                    260, xaxis_title=None, showlegend=False,
                    yaxis=dict(title="score", range=[0, 1.15],
                               showgrid=True, gridcolor="rgba(255,255,255,0.04)"),
                ))
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("No feedback scores.")
            st.markdown("</div>", unsafe_allow_html=True)

        # Summary table
        st.markdown(
            "<div style='font-size:0.68rem;font-weight:700;color:#64748b;"
            "letter-spacing:0.05em;margin:18px 0 8px'>Version Summary</div>",
            unsafe_allow_html=True,
        )
        tbl = comp_df[
            ["version_label","request_count","avg_latency_ms","total_cost",
             "avg_feedback","errors","error_rate_pct","total_tokens"]
        ].copy()
        tbl.columns = ["Version","Requests","Avg Latency (ms)","Total Cost",
                        "Avg Feedback","Errors","Error Rate (%)","Total Tokens"]
        tbl["Avg Latency (ms)"] = tbl["Avg Latency (ms)"].apply(lambda x: f"{x:.0f}" if pd.notna(x) else "—")
        tbl["Total Cost"]       = tbl["Total Cost"].apply(lambda x: f"${x:.6f}" if pd.notna(x) else "—")
        tbl["Avg Feedback"]     = tbl["Avg Feedback"].apply(lambda x: f"{x:.3f}" if pd.notna(x) else "—")
        st.dataframe(tbl, use_container_width=True, hide_index=True)

        if not defs_df.empty:
            st.markdown(
                "<div style='font-size:0.68rem;font-weight:700;color:#64748b;"
                "letter-spacing:0.05em;margin:18px 0 8px'>Template Content</div>",
                unsafe_allow_html=True,
            )
            for _, row in defs_df.iterrows():
                status = "" if row["is_active"] else " — inactive"
                label  = f"v{int(row['version'])}{status}"
                if row["description"]:
                    label += f"  ·  {row['description']}"
                with st.expander(label):
                    if row["system_prompt"]:
                        st.caption("System prompt")
                        st.code(row["system_prompt"], language="text")
                    st.caption("User template")
                    st.code(row["content"], language="text")
                    st.caption(f"Created: {row['created_at']}")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("<hr/>", unsafe_allow_html=True)
phoenix_url = os.getenv("PHOENIX_ENDPOINT", "http://localhost:6006").replace("/v1/traces", "")
fc1, fc2 = st.columns([3, 1])
with fc1:
    st.markdown(
        f"<div style='font-size:0.68rem;color:#475569'>"
        f"Requests shown: <strong style='color:#94a3b8'>{len(df):,}</strong>"
        f" &nbsp;·&nbsp; Total cost: <strong style='color:#94a3b8'>${total_cost:.4f}</strong>"
        f" &nbsp;·&nbsp; <code style='font-size:0.62rem'>{DB_PATH}</code></div>",
        unsafe_allow_html=True,
    )
with fc2:
    st.markdown(
        f"<a href='{phoenix_url}' target='_blank' "
        f"style='font-size:0.68rem;color:#6366f1;text-decoration:none'>"
        f"Open Phoenix traces →</a>",
        unsafe_allow_html=True,
    )

# ---------------------------------------------------------------------------
# Auto-refresh
# ---------------------------------------------------------------------------
if auto_refresh:
    time.sleep(10)
    st.cache_data.clear()
    st.rerun()
