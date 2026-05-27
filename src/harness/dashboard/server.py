"""Programmatic uvicorn runner for the dashboard."""

from __future__ import annotations

import uvicorn

from harness._constants import DASHBOARD_BIND_ADDRESS, DASHBOARD_PORT
from harness.dashboard.app import create_app

# P4 audit fix (2026-05-27): only loopback addresses are accepted.  The
# dashboard exposes /api/state, /api/cost, /api/queue, /api/l5-events,
# /ws and similar endpoints UNAUTHENTICATED — exactly the surface an
# attacker would target on a shared network.  Until token-gating is
# wired into every endpoint (the way keys_ui.py does), force loopback.
LOOPBACK_HOSTS: frozenset[str] = frozenset({
    "127.0.0.1",
    "::1",
    "localhost",
})


class NonLoopbackBindRefused(ValueError):
    """Raised when ``serve`` is asked to bind to a non-loopback address.

    The dashboard has no authentication; binding to ``0.0.0.0`` (or any
    LAN-visible address) would expose operational state — engine
    activity, cost, observer flags, L5 events — to every process on the
    network.  Until per-endpoint auth is wired in, only loopback binds
    are accepted.
    """


def serve(host: str = DASHBOARD_BIND_ADDRESS, port: int = DASHBOARD_PORT) -> None:
    """Run the dashboard with uvicorn.

    Args:
        host: bind address.  MUST be a loopback host (127.0.0.1 / ::1 /
            localhost).  Non-loopback values raise
            :class:`NonLoopbackBindRefused` because the dashboard
            endpoints are unauthenticated.
        port: TCP port.

    Raises:
        NonLoopbackBindRefused: when ``host`` is anything other than a
            recognised loopback address.  P4 audit fix 2026-05-27.
    """
    if host not in LOOPBACK_HOSTS:
        raise NonLoopbackBindRefused(
            f"dashboard host {host!r} is not a loopback address; the "
            f"dashboard's /api/* and /ws endpoints have no "
            f"authentication, so a non-loopback bind exposes "
            f"operational state to your LAN.  Allowed hosts: "
            f"{sorted(LOOPBACK_HOSTS)}."
        )
    app = create_app()
    uvicorn.run(app, host=host, port=port, log_level="warning")
