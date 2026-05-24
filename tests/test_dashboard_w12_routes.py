"""W12-DASHBOARD-WIRE-V2-ROUTES: tests for the new dashboard endpoints.

The 20-agent operator-review panel found these endpoints returning 404,
leaving Wave 11 work invisible on the dashboard.  Wired through to the
existing backend modules (cost_widget, preflight_latency, l5_escalation,
observer.state).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from harness.dashboard.app import create_app


@pytest.fixture
def client():
    return TestClient(create_app())


# -- /api/loop ----------------------------------------------------------


def test_loop_endpoint_returns_required_keys(client):
    r = client.get("/api/loop")
    assert r.status_code == 200
    body = r.json()
    required = {"status", "tick", "last_tick_at",
                "minutes_since_last_tick", "is_stale"}
    assert required <= set(body.keys()), (
        f"missing keys: {required - set(body.keys())}"
    )


def test_loop_endpoint_is_stale_false_when_no_tick(client):
    """No last_tick_at → is_stale=False (uninitialized, not stale)."""
    r = client.get("/api/loop")
    body = r.json()
    if body["last_tick_at"] is None:
        assert body["is_stale"] is False


# -- /api/cost ----------------------------------------------------------


def test_cost_endpoint_returns_widget_shape(client):
    r = client.get("/api/cost")
    assert r.status_code == 200
    body = r.json()
    required = {"spent_usd", "budget_usd", "remaining_usd",
                "pct_of_budget_used", "offload_ratio", "dispatches",
                "subscription_dispatches", "paid_dispatches",
                "window_label", "status"}
    assert required <= set(body.keys())
    assert body["budget_usd"] > 0
    assert body["status"] in ("ok", "warn", "exhausted", "error")


# -- /api/preflight-latency ---------------------------------------------


def test_preflight_latency_endpoint_returns_summary(client):
    r = client.get("/api/preflight-latency")
    assert r.status_code == 200
    body = r.json()
    required = {"count", "p50", "p95", "p99", "per_check"}
    assert required <= set(body.keys())
    assert isinstance(body["per_check"], dict)


# -- /api/l5-events -----------------------------------------------------


def test_l5_events_endpoint_returns_events_list(client):
    r = client.get("/api/l5-events")
    assert r.status_code == 200
    body = r.json()
    assert "count" in body
    assert "events" in body
    assert isinstance(body["events"], list)
    assert body["count"] == len(body["events"])


def test_l5_events_event_shape_when_present(client):
    """When an event is present, it has source/code/summary/action."""
    r = client.get("/api/l5-events")
    body = r.json()
    for ev in body["events"]:
        assert "source" in ev
        assert "code" in ev
        assert "summary" in ev
        assert "action" in ev


# -- regression: NO endpoint returns 404 -------------------------------


@pytest.mark.parametrize("endpoint", [
    "/api/loop",
    "/api/cost",
    "/api/preflight-latency",
    "/api/l5-events",
])
def test_w12_endpoints_do_not_return_404(client, endpoint):
    """The exact regression the operator-review panel caught."""
    r = client.get(endpoint)
    assert r.status_code != 404, (
        f"{endpoint} returned 404 — Wave 11 work is invisible"
    )
