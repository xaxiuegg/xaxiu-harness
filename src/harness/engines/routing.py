"""W14-DISPATCH-HEALTH-AWARE-FALLBACK 2026-05-25.

Routing helpers that filter the dispatch fallback chain based on three
real-time signals:

  1. **Keys-present**: skip engines whose API key env var is empty or
     missing.  Previously the dispatcher would still try them and waste
     a round-trip producing "no api key" failures.

  2. **Probe-terminated**: skip engines whose most-recent live-probe
     (from ``state/engine_health_probes.jsonl``) categorized as
     ``terminated``.  Surface as a routing-skip rather than burning a
     real dispatch on Kimi-class account-terminated state.

  3. **Over budget cap**: skip engines whose per-engine monthly spend
     has exceeded the configured cap from
     ``coord/dev_loop/budget_cap.json`` (W14-BUDGET-METER-PER-ENGINE).

The filter is centralized here so it composes deterministically with
the dispatcher's existing priority + LOCK + BURST resolution.  Callers
opt out via the ``HARNESS_DISPATCH_SKIP_HEALTH_FILTER`` env var (set to
``1``, ``true``, ``yes`` to disable).

Force-dispatched engines (``force_engine=...``) are NOT filtered — the
operator's explicit choice always wins.  The filter applies to:

  - Default-priority selection in ``_pick_initial_engine``
  - The ``remaining`` engine list in the fallback loop
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Final


# Default window for "recently terminated" detection.  A probe more than
# this old is ignored — the engine could have been restored since.
_TERMINATED_WINDOW_HOURS: Final[int] = 24


def _filter_disabled() -> bool:
    """Return True when health-aware filtering is explicitly disabled."""
    val = os.environ.get(
        "HARNESS_DISPATCH_SKIP_HEALTH_FILTER", "",
    ).strip().lower()
    return val in {"1", "true", "yes", "on"}


def _keys_present() -> dict[str, bool]:
    """Return {engine: has_key} for each supported engine.

    Reads the env vars listed in ``harness._constants.API_KEY_ENV_VARS``.
    A key is considered present if the env var exists and is non-empty
    after stripping whitespace.
    """
    from harness._constants import API_KEY_ENV_VARS
    return {
        engine: bool((os.environ.get(env_var) or "").strip())
        for engine, env_var in API_KEY_ENV_VARS.items()
    }


def _recently_terminated_engines(
    *,
    log_path: Path | None = None,
    window_hours: int = _TERMINATED_WINDOW_HOURS,
) -> set[str]:
    """Return engines whose most-recent live-probe within the window was
    ``category=terminated``.

    Reads ``state/engine_health_probes.jsonl`` (W13-ENGINE-FAILURE-VISIBILITY
    write target).  For each engine, only the latest probe within the
    window is considered — a single ``up`` probe after a ``terminated``
    one will un-mark the engine.
    """
    if log_path is None:
        log_path = Path.cwd() / "state" / "engine_health_probes.jsonl"
    if not log_path.exists():
        return set()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    latest_per_engine: dict[str, dict] = {}
    try:
        for line in log_path.read_text(
            encoding="utf-8", errors="replace",
        ).splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("timestamp")
            engine = rec.get("engine")
            if not ts or not engine:
                continue
            try:
                rec_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                continue
            if rec_dt < cutoff:
                continue
            existing = latest_per_engine.get(engine)
            if existing is None or existing["timestamp"] < ts:
                latest_per_engine[engine] = rec
    except OSError:
        return set()

    return {
        engine for engine, rec in latest_per_engine.items()
        if rec.get("category") == "terminated"
    }


def filter_eligible_engines(
    engines: list[str],
    *,
    skip_no_key: bool = True,
    skip_terminated: bool = True,
    skip_over_budget: bool = True,
    health_probe_log_path: Path | None = None,
    budget_ledger_path: Path | None = None,
    budget_caps_config: dict | None = None,
) -> tuple[list[str], dict[str, str]]:
    """Filter ``engines`` down to those eligible for live dispatch.

    Returns ``(eligible, skip_reasons)``:
      - ``eligible`` preserves input ordering, contains only engines
        that pass all enabled filters.
      - ``skip_reasons`` maps each excluded engine name to a string
        explaining why it was excluded (``no-key``, ``terminated``,
        or ``over-cap (${spent} of ${cap})``).

    When ``HARNESS_DISPATCH_SKIP_HEALTH_FILTER=1`` is set in the env,
    all filters are disabled and the input list is returned unchanged
    (with an empty ``skip_reasons``).  This is the escape hatch for
    tests + operator overrides.

    Force-dispatched engines should NOT be passed through this filter —
    callers pre-validate operator intent before invoking us.
    """
    if _filter_disabled():
        return list(engines), {}

    keys_present = _keys_present() if skip_no_key else {}
    terminated = (
        _recently_terminated_engines(log_path=health_probe_log_path)
        if skip_terminated else set()
    )

    # Read budget config once (avoid re-reading per engine)
    caps_config_resolved = None
    if skip_over_budget:
        if budget_caps_config is not None:
            caps_config_resolved = budget_caps_config
        else:
            from harness.budget import read_caps_config
            caps_config_resolved = read_caps_config()

    eligible: list[str] = []
    skip_reasons: dict[str, str] = {}

    for engine in engines:
        if skip_no_key and not keys_present.get(engine, True):
            # keys_present default True keeps engines we don't have an
            # env var configured for (e.g. ``mock``) eligible.
            skip_reasons[engine] = "no-key"
            continue
        if skip_terminated and engine in terminated:
            skip_reasons[engine] = "terminated"
            continue
        if skip_over_budget and caps_config_resolved is not None:
            from harness.budget import check_engine_cap
            status = check_engine_cap(
                engine,
                ledger_path=budget_ledger_path,
                caps_config=caps_config_resolved,
            )
            if not status.within_cap:
                skip_reasons[engine] = (
                    f"over-cap (${status.spent_usd:.2f} of "
                    f"${status.cap_usd:.2f})"
                )
                continue
        eligible.append(engine)

    return eligible, skip_reasons


def describe_fallback_policy(
    engines: list[str] | None = None,
    *,
    health_probe_log_path: Path | None = None,
    budget_ledger_path: Path | None = None,
    budget_caps_config: dict | None = None,
) -> dict:
    """Return a structured description of the current routing policy.

    Used by ``harness engines fallback-policy`` (CLI verb) and any
    callers that want a JSON-serializable snapshot.

    Returns:
      {
        "filter_disabled": bool,
        "all_engines": [...],
        "eligible": [...],
        "skipped": {engine: reason, ...},
      }
    """
    if engines is None:
        from harness._constants import SUPPORTED_BACKENDS
        engines = [b for b in SUPPORTED_BACKENDS if b != "mock"]

    eligible, reasons = filter_eligible_engines(
        engines,
        health_probe_log_path=health_probe_log_path,
        budget_ledger_path=budget_ledger_path,
        budget_caps_config=budget_caps_config,
    )

    return {
        "filter_disabled": _filter_disabled(),
        "all_engines": list(engines),
        "eligible": eligible,
        "skipped": reasons,
    }
