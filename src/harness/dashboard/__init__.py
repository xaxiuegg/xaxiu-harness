"""Operator-facing real-time dashboard (FastAPI + WebSocket)."""

from __future__ import annotations

from harness.dashboard.app import create_app
from harness.dashboard.server import serve

__all__ = ["create_app", "serve"]
