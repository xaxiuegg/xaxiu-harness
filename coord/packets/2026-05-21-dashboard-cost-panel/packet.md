# DASHBOARD-COST-PANEL — live per-engine spend + budget cap progress

## Goal

Operators currently learn about engine spend only when `harness budget show`
runs (or when a kill_condition fires).  Surface live spend in the
dashboard so the operator sees runaway cost as it accumulates.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New helper in `src/harness/dashboard/v2_routes.py`

Add a new top-level helper next to the existing list_runs/list_workers
helpers (DO NOT touch them):

```python
def cost_panel() -> dict[str, Any]:
    """Return a tiny dict of per-engine spend + cap progress for the dashboard.

    Shape:
        {
            "total_usd": 1.23,
            "cap_usd": 5.00 | None,
            "cap_pct": 24.6 | None,
            "by_engine": [
                {"engine": "kimi", "usd": 0.80, "calls": 12},
                ...
            ],
        }
    """
    from harness.budget import read_ledger, summary as budget_summary
    try:
        summary = budget_summary()
    except Exception:
        summary = {"total_usd": 0.0, "by_engine": []}

    cap_usd = None
    cap_pct = None
    try:
        from harness.budget import DEFAULT_CAP_PATH
        from pathlib import Path
        if Path(DEFAULT_CAP_PATH).exists():
            import json as _json
            cap_data = _json.loads(Path(DEFAULT_CAP_PATH).read_text(encoding="utf-8"))
            cap_usd = float(cap_data.get("monthly_cap_usd", 0)) or None
    except Exception:
        cap_usd = None
    if cap_usd:
        cap_pct = round(100.0 * float(summary.get("total_usd", 0)) / cap_usd, 1)

    return {
        "total_usd": float(summary.get("total_usd", 0.0)),
        "cap_usd": cap_usd,
        "cap_pct": cap_pct,
        "by_engine": list(summary.get("by_engine") or []),
    }
```

### 2. Wire into make_router()

Add a NEW route to make_router (without disturbing existing routes):

```python
    @router.get("/cost-panel")
    def _cost_panel() -> dict[str, Any]:
        return cost_panel()
```

### 3. Embed in WS snapshot

In `src/harness/dashboard/app.py`, find the `_snapshot()` function that
currently embeds `v2.runs` + `v2.top_run_workers`.  Add a `cost` key:

```python
from harness.dashboard.v2_routes import cost_panel as _cost_panel
# ...inside _snapshot, before return:
snapshot["v2"]["cost"] = _cost_panel()
```

If `summary` from harness.budget doesn't already have the exact shape
above, do a tiny adapter to map it; do NOT modify harness.budget.

### 4. Tests

New file `tests/test_dashboard_cost_panel.py`:

```python
"""Tests for DASHBOARD-COST-PANEL — cost_panel() + /v2/cost-panel."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harness.dashboard.v2_routes import cost_panel, make_router


def test_cost_panel_empty_returns_zero_total(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    with patch("harness.budget.summary") as mock_sum:
        mock_sum.return_value = {"total_usd": 0.0, "by_engine": []}
        result = cost_panel()
    assert result["total_usd"] == 0.0
    assert result["by_engine"] == []
    assert result["cap_usd"] is None


def test_cost_panel_with_cap_and_engines(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    # Write a cap file at the default path
    from harness.budget import DEFAULT_CAP_PATH
    cap_path = Path(DEFAULT_CAP_PATH)
    cap_path.parent.mkdir(parents=True, exist_ok=True)
    cap_path.write_text(json.dumps({"monthly_cap_usd": 10.0}), encoding="utf-8")
    with patch("harness.budget.summary") as mock_sum:
        mock_sum.return_value = {
            "total_usd": 2.50,
            "by_engine": [
                {"engine": "kimi", "usd": 1.80, "calls": 12},
                {"engine": "deepseek", "usd": 0.70, "calls": 3},
            ],
        }
        result = cost_panel()
    assert result["total_usd"] == 2.50
    assert result["cap_usd"] == 10.0
    assert result["cap_pct"] == 25.0
    assert len(result["by_engine"]) == 2


def test_cost_panel_swallows_summary_error(monkeypatch) -> None:
    """If budget.summary raises, cost_panel still returns a safe default dict."""
    with patch("harness.budget.summary", side_effect=RuntimeError("db locked")):
        result = cost_panel()
    assert result["total_usd"] == 0.0


def test_cost_panel_route_http() -> None:
    app = FastAPI()
    app.include_router(make_router())
    with patch("harness.budget.summary") as mock_sum:
        mock_sum.return_value = {"total_usd": 0.0, "by_engine": []}
        client = TestClient(app)
        r = client.get("/v2/cost-panel")
    assert r.status_code == 200
    body = r.json()
    assert "total_usd" in body
    assert "by_engine" in body


def test_snapshot_embeds_cost_panel(monkeypatch, tmp_path: Path) -> None:
    """_snapshot() includes v2.cost so the WS stream carries cost telemetry."""
    monkeypatch.chdir(tmp_path)
    with patch("harness.budget.summary") as mock_sum:
        mock_sum.return_value = {"total_usd": 0.5, "by_engine": []}
        from harness.dashboard.app import _snapshot
        snap = _snapshot()
    assert "cost" in snap["v2"]
    assert snap["v2"]["cost"]["total_usd"] == 0.5
```

## Acceptance

- `python -m pytest tests/test_dashboard_cost_panel.py` — green.
- Full suite stays green.
- `GET /v2/cost-panel` returns JSON with `total_usd`, `cap_usd` (or null),
  `cap_pct` (or null), `by_engine` (list).

## Constraints

- DO NOT modify `src/harness/budget.py`.
- DO NOT add a dependency on numpy / pandas — stdlib + fastapi only.
- Keep `cost_panel()` under 50 LOC.
- Existing v2_routes tests must stay green.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
