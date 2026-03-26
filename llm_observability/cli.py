"""CLI entry points for llm-observability package.

Installed commands:
    llm-obs-api        — Start the FastAPI server
    llm-obs-dashboard  — Start the Streamlit dashboard
    llm-obs-seed       — Populate the database with synthetic data
"""

import os
import sys


def run_api() -> None:
    """Start the FastAPI/Uvicorn server."""
    import uvicorn

    host = os.getenv("API_HOST", "0.0.0.0")
    port = int(os.getenv("API_PORT", "8000"))
    reload = "--reload" in sys.argv

    uvicorn.run(
        "llm_observability.main:app",
        host=host,
        port=port,
        reload=reload,
    )


def run_dashboard() -> None:
    """Start the Streamlit dashboard."""
    from streamlit.web.cli import main as st_main

    dashboard_path = os.path.join(
        os.path.dirname(__file__), "dashboard", "app.py"
    )
    sys.argv = [
        "streamlit", "run", dashboard_path,
        "--server.port", os.getenv("DASHBOARD_PORT", "8501"),
        "--server.address", "0.0.0.0",
        "--server.headless", "true",
        "--browser.gatherUsageStats", "false",
    ]
    st_main()


def run_seed() -> None:
    """Run the seed data script."""
    import asyncio

    # Add project root to path so the script can import the package
    root = os.path.dirname(os.path.dirname(__file__))
    if root not in sys.path:
        sys.path.insert(0, root)

    from scripts.seed_data import seed

    asyncio.run(seed())
