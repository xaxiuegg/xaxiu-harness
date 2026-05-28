"""Uvicorn runner for the proxy application."""

from __future__ import annotations

import uvicorn

from harness.proxy.app import create_app


def serve(
    host: str = "127.0.0.1",
    port: int = 7879,
    upstream: str = "kimi-http",
) -> None:
    """Serve the proxy.

    ``upstream`` selects which upstream to route to (see
    ``harness.proxy.upstreams``).  Defaults to ``"kimi-http"`` for
    backward compatibility with pre-v0.5.1 callers.
    """
    app = create_app(upstream=upstream)
    uvicorn.run(app, host=host, port=port, log_level="warning")
