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
