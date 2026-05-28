"""W14-BUDGET-METER-PER-ENGINE 2026-05-28: cheap, local budget watcher
that emits observer flags when per-engine spend crosses the alert
threshold OR the cap.

Unlike the heavy ``cycle.run_cycle`` (which dispatches to an LLM auditor
for transcript analysis), this watcher is **read-only + local + zero-
cost** — it inspects the per-engine ledger + caps config that already
live on disk under ``coord/dev_loop/`` and emits ``Flag`` objects
without making any network calls.

Designed to run as a fast hook (every ~30 min via cron-scheduler).
The threshold (default 80% — same as the budget caps config's
``alert_threshold_pct``) is configurable; an engine that crosses it
gets a MED flag the first time it crosses + a HIGH flag at 100%.

Idempotent — re-running with no state change emits zero new flags
(the dedup logic checks pending flags + already-handled flags so we
don't spam the operator's HIGH_FLAG_PENDING.md every cron tick).
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from harness._constants import _REPO_ROOT
from harness.observer.flags import (
    Flag,
    FlagSeverity,
    _next_flag_id,
    ensure_flag_dirs,
    write_pending_flags,
)

logger = logging.getLogger(__name__)


DEFAULT_OBSERVER_DIR: Path = _REPO_ROOT / "coord" / "observer"


def _existing_flag_signatures(observer_dir: Path) -> set[str]:
    """Return signatures of already-raised budget flags so we don't
    re-raise.  Signature is ``f"{category}::{engine}::{threshold}"``."""
    sigs: set[str] = set()
    for sub in ("flags", "cycles/handled"):
        d = observer_dir / sub
        if not d.exists():
            continue
        for f in d.glob("FLAG-*.json"):
            try:
                import json
                data = json.loads(f.read_text(encoding="utf-8"))
                if "category" not in data or "engine" not in data.get("detail", ""):
                    continue
                # Try to extract engine + threshold from the detail string
                # (we wrote them in a stable format)
                sigs.add(_signature_from_flag_dict(data))
            except (OSError, ValueError):
                continue
    # Also scan the pending markdown files for current-month signatures.
    # We embed the signature in the flag's detail string as
    # `# sig::<category>::<engine>::<threshold>`.  Regex extracts it
    # cleanly regardless of surrounding JSON / markdown / quoting.
    import re
    sig_pattern = re.compile(
        r"sig::(budget_cap_[a-z_]+::[\w.-]+::\d+)"
    )
    for sev in ("MED", "HIGH"):
        pending = observer_dir / f"{sev}_FLAG_PENDING.md"
        if not pending.exists():
            continue
        try:
            text = pending.read_text(encoding="utf-8")
            for match in sig_pattern.finditer(text):
                sigs.add(match.group(1))
        except OSError:
            continue
    return sigs


def _signature_from_flag_dict(data: dict) -> str:
    """Best-effort: reconstruct the dedup signature from a Flag dict."""
    category = data.get("category", "")
    # Detail is "engine={x} ..."; parse the engine field
    detail = data.get("detail") or ""
    engine = ""
    for tok in detail.split():
        if tok.startswith("engine="):
            engine = tok.split("=", 1)[1].strip(",")
            break
    threshold = "0"
    for tok in detail.split():
        if tok.startswith("threshold="):
            threshold = tok.split("=", 1)[1].rstrip("%").strip(",")
            break
    return f"{category}::{engine}::{threshold}"


def check_budget_caps(
    *,
    observer_dir: Path | None = None,
    cap_path: Path | None = None,
    ledger_path: Path | None = None,
    skip_dedup: bool = False,
) -> list[Flag]:
    """Check every engine with a configured cap or recorded spend.

    Returns a list of Flag objects (MED for crossing alert threshold,
    HIGH for crossing the cap itself).  Caller is responsible for
    writing the flags via ``write_pending_flags`` — or use
    ``run_budget_watch()`` which does both.

    Dedup: a flag for ``budget_cap_alert::{engine}::80`` is raised at
    most ONCE per month (signature persists across cron ticks).
    """
    from harness.budget import all_engines_status, read_caps_config
    base = observer_dir or DEFAULT_OBSERVER_DIR
    ensure_flag_dirs(base)

    caps_config = read_caps_config(cap_path=cap_path)
    alert_threshold_pct = float(caps_config.get("alert_threshold_pct", 80))

    existing = set() if skip_dedup else _existing_flag_signatures(base)
    now_iso = datetime.now(timezone.utc).isoformat()
    cycle_id = "budget-watch-" + datetime.now(timezone.utc).strftime(
        "%Y-%m-%dT%H%M%SZ",
    )

    new_flags: list[Flag] = []
    statuses = all_engines_status(
        caps_config=caps_config, ledger_path=ledger_path,
    )
    for status in statuses:
        if status.cap_usd <= 0.0:
            continue  # uncapped — nothing to alert on
        # OVER-CAP: HIGH flag
        if not status.within_cap:
            sig = f"budget_cap_exceeded::{status.engine}::100"
            if sig not in existing:
                new_flags.append(_build_flag(
                    severity=FlagSeverity.HIGH,
                    category="budget_cap_exceeded",
                    engine=status.engine,
                    spent_usd=status.spent_usd,
                    cap_usd=status.cap_usd,
                    pct=status.pct_used,
                    threshold_pct=100.0,
                    now_iso=now_iso,
                    cycle_id=cycle_id,
                    observer_dir=base,
                ))
            continue
        # ALERT THRESHOLD: MED flag
        if status.alert_threshold_reached:
            sig = f"budget_cap_alert::{status.engine}::{int(alert_threshold_pct)}"
            if sig not in existing:
                new_flags.append(_build_flag(
                    severity=FlagSeverity.MED,
                    category="budget_cap_alert",
                    engine=status.engine,
                    spent_usd=status.spent_usd,
                    cap_usd=status.cap_usd,
                    pct=status.pct_used,
                    threshold_pct=alert_threshold_pct,
                    now_iso=now_iso,
                    cycle_id=cycle_id,
                    observer_dir=base,
                ))
    return new_flags


def _build_flag(
    *,
    severity: FlagSeverity,
    category: str,
    engine: str,
    spent_usd: float,
    cap_usd: float,
    pct: float,
    threshold_pct: float,
    now_iso: str,
    cycle_id: str,
    observer_dir: Path,
) -> Flag:
    sig = f"{category}::{engine}::{int(threshold_pct)}"
    summary = (
        f"{engine} spent ${spent_usd:.2f} of ${cap_usd:.2f} "
        f"({pct:.1f}%); crossed {int(threshold_pct)}% threshold"
    )
    detail = (
        f"engine={engine} spent=${spent_usd:.4f} cap=${cap_usd:.2f} "
        f"pct={pct:.1f}% threshold={int(threshold_pct)}% "
        f"# sig::{sig}"
    )
    evidence = [
        f"per-engine ledger spend: ${spent_usd:.4f}",
        f"configured cap: ${cap_usd:.2f}",
        f"alert threshold: {int(threshold_pct)}%",
        f"check time: {now_iso}",
    ]
    return Flag(
        id=_next_flag_id(observer_dir),
        severity=severity,
        category=category,
        summary=summary,
        detail=detail,
        evidence=evidence,
        raised_at=now_iso,
        cycle_id=cycle_id,
    )


def run_budget_watch(
    *,
    observer_dir: Path | None = None,
    cap_path: Path | None = None,
    ledger_path: Path | None = None,
) -> list[Flag]:
    """Convenience: check caps + write new flags to pending files.

    Returns the list of NEW flags raised this run (may be empty if
    everything is under threshold OR all flags already raised this
    month).
    """
    base = observer_dir or DEFAULT_OBSERVER_DIR
    new_flags = check_budget_caps(
        observer_dir=base,
        cap_path=cap_path,
        ledger_path=ledger_path,
    )
    if new_flags:
        write_pending_flags(new_flags, observer_dir=base)
    return new_flags
