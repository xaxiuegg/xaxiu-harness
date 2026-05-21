# COORD-NOTIFY-ON-INTEGRATE — post-integrate notify hook

## Goal

When a coord run finishes integration, write a small notify.json file
and optionally POST to a webhook so external dashboards / Slack etc. can
react.  Operator-modes already has webhook fields unused; this wave wires
the end-of-run signal.

## Scope (kimi-cli OR kimi-api with FIND/REPLACE)

### 1. New module `src/harness/coord/notify.py`

```python
"""Post-integration notification — write notify.json + optional webhook POST."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def write_notify(run_dir: Path, report: dict[str, Any]) -> Path:
    """Write notify.json atomically inside run_dir.  Returns the path."""
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / "notify.json"
    tmp = target.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(report, indent=2), encoding="utf-8")
    tmp.replace(target)
    return target


def post_webhook(url: str, payload: dict[str, Any], timeout: float = 5.0) -> bool:
    """POST *payload* (JSON) to *url*; return True on 2xx, False otherwise.

    Best-effort — silently swallows network errors so the integrator never
    fails because of a flaky webhook.
    """
    if not url:
        return False
    try:
        body = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except (urllib.error.URLError, OSError, ValueError):
        return False


def notify(run_dir: Path, report: dict[str, Any], webhook_url: str | None = None) -> tuple[Path, bool]:
    """Write notify.json and optionally POST a webhook.

    Returns ``(notify_path, webhook_ok)``.  ``webhook_ok`` is False when
    no URL was given OR the POST failed.
    """
    p = write_notify(run_dir, report)
    posted = post_webhook(webhook_url or "", report)
    return p, posted
```

### 2. Wire into integrator.py

Find the END of `integrate()` (the spot where it returns the success
report).  Right BEFORE the final `return` of the success path, add:

```python
        # Best-effort post-integrate notify (COORD-NOTIFY-ON-INTEGRATE)
        try:
            from harness.coord.notify import notify as _notify
            webhook = os.environ.get("HARNESS_INTEGRATOR_WEBHOOK_URL", "")
            _notify(run_dir, {
                "run_id": state.run_id,
                "success": True,
                "commit_sha": sha,
                "pushed": pushed,
                "test_summary": test_summary,
                "workers_merged": merged,
                "workers_skipped": skipped,
            }, webhook_url=webhook)
        except Exception:
            pass
```

Do the SAME on the all-other return paths inside integrate() that report
success.  For the conflicted path (where `workers_conflicted` is non-empty),
fire with `"success": False, "diagnostic": "merge_conflict"` instead.

### 3. Tests

`tests/test_coord_notify.py`:

```python
"""Tests for harness.coord.notify."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from harness.coord.notify import notify, write_notify, post_webhook


def test_write_notify_creates_json_file(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    p = write_notify(run_dir, {"run_id": "r1", "success": True})
    assert p.exists()
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data == {"run_id": "r1", "success": True}


def test_write_notify_atomic_replaces_existing(tmp_path: Path) -> None:
    run_dir = tmp_path / "runs" / "r1"
    write_notify(run_dir, {"version": 1})
    write_notify(run_dir, {"version": 2})
    data = json.loads((run_dir / "notify.json").read_text())
    assert data["version"] == 2


def test_post_webhook_returns_false_on_empty_url() -> None:
    assert post_webhook("", {"x": 1}) is False


def test_post_webhook_swallows_url_error() -> None:
    with patch("harness.coord.notify.urllib.request.urlopen",
               side_effect=OSError("connection refused")):
        assert post_webhook("http://invalid", {"x": 1}) is False


def test_post_webhook_success() -> None:
    mock_resp = MagicMock()
    mock_resp.__enter__.return_value.status = 200
    with patch("harness.coord.notify.urllib.request.urlopen", return_value=mock_resp):
        assert post_webhook("http://ok", {"x": 1}) is True


def test_notify_writes_file_and_returns_tuple(tmp_path: Path) -> None:
    p, posted = notify(tmp_path / "runs" / "r1", {"x": 1})
    assert p.exists()
    assert posted is False  # no webhook url


def test_integrator_writes_notify_on_success(tmp_path: Path, monkeypatch) -> None:
    """integrate() best-effort writes notify.json on the success path."""
    from harness.coord.integrator import integrate
    from harness.coord.run_state import write_run_state
    from harness.coord.schemas import IntegratorStatus, RunState, RunStateLiteral

    run_dir = tmp_path / "runs" / "r1"
    run_dir.mkdir(parents=True)
    write_run_state(run_dir / "run_state.json", RunState(
        schema_version=1, run_id="r1", spec_path="s.md",
        state=RunStateLiteral.INTEGRATING, plan_path=str(run_dir / "plan.json"),
        started_at="2026-05-21T00:00:00Z", last_tick_at="2026-05-21T00:00:00Z",
        workers={}, integrator_status=IntegratorStatus(state="pending"),
        escalations=[],
    ))

    # Stub subprocess so pytest invocation doesn't actually run pytest
    with patch("harness.coord.integrator.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(stdout="0 passed in 0.01s", returncode=0)
        integrate(run_dir)

    # notify.json should exist now
    notify_path = run_dir / "notify.json"
    assert notify_path.exists()
```

## Acceptance

- `python -m pytest tests/test_coord_notify.py` — green.
- Full suite stays green.

## Constraints

- DO NOT modify integrator's existing return shape — only ADD the
  best-effort notify call inside try/except.
- Stdlib only (urllib).
- Keep notify.py under 80 LOC.

## Engine

swarm/kimi or swarm/kimi-api; timeout 420s.
