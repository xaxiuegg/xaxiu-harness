"""Uvicorn runner for the proxy application."""

from __future__ import annotations

import uvicorn

from harness.proxy.app import create_app


def serve(host: str = "127.0.0.1", port: int = 7879) -> None:
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="warning")
