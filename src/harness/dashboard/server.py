"""Programmatic uvicorn runner for the dashboard."""

from __future__ import annotations

import uvicorn

from harness._constants import DASHBOARD_BIND_ADDRESS, DASHBOARD_PORT
from harness.dashboard.app import create_app


def serve(host: str = DASHBOARD_BIND_ADDRESS, port: int = DASHBOARD_PORT) -> None:
    """Run the dashboard with uvicorn."""
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="warning")
