"""W6-C2: dispatch-layer dead-engine alarm.

Tracks per-engine consecutive failure counts from
``state/engine_performance_log.jsonl`` and emits an L4 warning plus a
Windows toast when an engine hits 5+ consecutive failures.

The threshold is conservative on purpose:

  - 1-2 failures may be transient (network blip, rate-limit retry)
  - 5 consecutive failures from the same engine indicates a structural
    problem (key revoked, endpoint changed, model deprecated) that
    needs operator attention but does NOT halt the loop — the harness
    fallback chain still routes traffic to healthy engines.

Operator-facing surfaces:
  - ``harness preflight`` reports dead engines
  - Toast banner fires once per transition into the dead state (debounced
    via ``state/engine_alarms.json``)
  - Per-engine row in ``coord/dev_loop/state.json`` for dashboard view

This module is read-only against engine_performance_log.jsonl — it
never modifies the log.  The alarm-fired flag lives in a separate
state file so resetting alarms doesn't touch dispatch history.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parents[2]
PERF_LOG = REPO_ROOT / "state" / "engine_performance_log.jsonl"
ALARM_STATE = REPO_ROOT / "state" / "engine_alarms.json"

# Consecutive failures required to fire the alarm.  Per W6 plan + the
# 5-MiMo session review (Operator Advocate: "after 5 consecutive
# failures, emit L4 warning + fire Windows toast").
DEFAULT_THRESHOLD = 5


def _load_perf_entries(log_path: Path = PERF_LOG, max_tail: int = 1000) -> list[dict]:
    """Read the last ``max_tail`` entries from the performance log.

    Returns an empty list when the log is missing or unreadable.
    Bounded read keeps the tail check O(1) regardless of log size.
    """
    if not log_path.exists():
        return []
    try:
        # Read whole file then take tail; the log is jsonl so we can't
        # seek by lines without scanning, but 1000 entries is small.
        lines = log_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    entries: list[dict] = []
    for line in lines[-max_tail:]:
        line = line.strip()
        if not line:
            continue
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return entries


def consecutive_failures(
    engine: str,
    *,
    log_path: Path = PERF_LOG,
    max_tail: int = 1000,
) -> int:
    """Return the number of consecutive failures for *engine* at the tail.

    Walks the perf log from the tail backward, counting entries with
    ``outcome != "success"`` for the given engine.  Stops at the first
    success entry or when other-engine entries break the streak.

    The streak is per-engine: a kimi success between deepseek failures
    does NOT reset deepseek's streak.  Other-engine entries are
    ignored for the engine in question.
    """
    entries = _load_perf_entries(log_path, max_tail=max_tail)
    streak = 0
    for entry in reversed(entries):
        if entry.get("backend") != engine:
            continue
        if entry.get("outcome") == "success":
            break
        streak += 1
    return streak


def _read_alarm_state(path: Path = ALARM_STATE) -> dict[str, dict]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _write_alarm_state(state: dict[str, dict], path: Path = ALARM_STATE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def check_engine_alarm(
    engine: str,
    *,
    threshold: int = DEFAULT_THRESHOLD,
    log_path: Path = PERF_LOG,
    alarm_path: Path = ALARM_STATE,
) -> tuple[bool, int, bool]:
    """Probe an engine's failure streak and update the alarm state.

    Returns ``(is_dead, streak, transition)``:
      - is_dead: True iff streak >= threshold
      - streak: current consecutive failure count
      - transition: True iff this call flipped the engine into a dead
        state (i.e. the toast should fire NOW).  Already-dead engines
        return transition=False until they recover (a success entry
        clears the alarm flag in state).
    """
    streak = consecutive_failures(engine, log_path=log_path)
    is_dead = streak >= threshold
    state = _read_alarm_state(alarm_path)
    prev = state.get(engine, {})
    prev_dead = bool(prev.get("dead", False))
    transition = False
    if is_dead and not prev_dead:
        transition = True
        state[engine] = {
            "dead": True,
            "streak_at_alarm": streak,
            "fired_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_alarm_state(state, alarm_path)
    elif not is_dead and prev_dead:
        # Engine recovered — clear the alarm so a future death will
        # fire a fresh toast.
        state[engine] = {
            "dead": False,
            "recovered_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_alarm_state(state, alarm_path)
    return (is_dead, streak, transition)


def fire_dead_engine_alarm(engine: str, streak: int) -> None:
    """Emit the L4 warning + Windows toast for a newly-dead engine.

    Both channels are best-effort.  L4 warning prints to stderr (so
    `harness queue execute` and other dispatchers surface it
    operator-side).  Toast uses the existing W5-PP infrastructure.
    """
    import sys
    msg = (
        f"L4.engines.E_DEAD_ENGINE: {engine} hit {streak} consecutive "
        f"failures.  Other engines in the fallback chain will pick up "
        f"the load, but {engine} needs investigation (key revoked? "
        f"endpoint changed?  rate limit?).  Inspect via "
        f"`harness preflight` and `state/engine_performance_log.jsonl`."
    )
    print(f"[L4] {msg}", file=sys.stderr)
    try:
        from harness.errors import fire_windows_toast
        fire_windows_toast(
            title=f"xaxiu-harness: {engine} engine dead",
            body=f"{streak} consecutive failures — check `harness preflight`.",
        )
    except Exception:
        pass  # toast is bonus, never block on its failure


def dead_engines(
    engines: Optional[list[str]] = None,
    *,
    threshold: int = DEFAULT_THRESHOLD,
    log_path: Path = PERF_LOG,
) -> dict[str, int]:
    """Return ``{engine: streak}`` for every engine currently above the
    threshold.  Useful for the preflight check + dashboard summary."""
    if engines is None:
        engines = ["deepseek", "kimi", "mimo", "anthropic", "gemini"]
    out: dict[str, int] = {}
    for e in engines:
        streak = consecutive_failures(e, log_path=log_path)
        if streak >= threshold:
            out[e] = streak
    return out
