"""Master prompt generator for session handoff."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

from harness._constants import _REPO_ROOT
from harness.state.inspect import summarize_active_dispatches
from harness.status import read_status, summary as status_summary

DEFAULT_STATE_PATH: Path = Path("coord/dev_loop/state.json")
DEFAULT_STATUS_PATH: Path = Path("coord/STATUS.csv")
_BOOTSTRAP_FALLBACKS = [
    _REPO_ROOT / "coord" / "SESSION_BOOTSTRAP.md",
    _REPO_ROOT / "CLAUDE.md",
]


def _load_state(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _last_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "log", "-1", "--format=%H %s"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "(unknown)"


def _status_summary_text(path: Path) -> str:
    try:
        counts = status_summary(path)
        parts = [f"{count} {status.value}" for status, count in counts.items() if count]
        return ", ".join(parts) if parts else "(none)"
    except Exception:
        return "(error)"


def generate_master_prompt(
    reason: str = "",
    state_path: Path = DEFAULT_STATE_PATH,
    status_path: Path = DEFAULT_STATUS_PATH,
) -> str:
    """Produce a 5-section markdown handoff prompt."""
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    lines: list[str] = []
    lines.append(f"# Session handoff — {now}")
    lines.append("")
    lines.append("## 1. Base bootstrap (durable, project-invariant)")
    bootstrap_text = ""
    for p in _BOOTSTRAP_FALLBACKS:
        if p.exists():
            bootstrap_text = p.read_text(encoding="utf-8")
            break
    if not bootstrap_text:
        bootstrap_text = "(No bootstrap file found; please paste project context.)"
    lines.append(bootstrap_text)
    lines.append("")
    lines.append("## 2. Session state snapshot (frozen at handoff time)")
    lines.append(f"- last commit: {_last_commit()}")
    lines.append(f"- STATUS.csv summary: {_status_summary_text(status_path)}")
    state = _load_state(state_path)
    active = state.get("active_dispatches") or []
    lines.append(f"- active dispatches: {len(active)}")
    if active:
        lines.append("```")
        lines.append(summarize_active_dispatches(active))
        lines.append("```")
    escs = state.get("escalations") or []
    lines.append(f"- recent escalations: {len(escs)}")
    if escs:
        for e in escs[-3:]:
            lines.append(
                f"  - {e.get('id', '?')} {e.get('tag', '?')}: {e.get('diagnostic', '')[:80]}"
            )
    cooldowns = state.get("engine_cooldowns") or {}
    if cooldowns:
        lines.append("- engine cooldowns:")
        for eng, cd in cooldowns.items():
            until = cd.get("cooldown_until")
            lines.append(f"  - {eng}: {until or 'none'}")
    else:
        lines.append("- engine cooldowns: none")
    lines.append("")
    lines.append("## 3. Wave plan delta (what's changed since the original boot)")
    wave_plan = state.get("wave_plan") or []
    done_waves = [w for w in wave_plan if w.get("status") == "done"]
    lines.append(
        f"- newly shipped: {', '.join(str(w.get('id', '?')) for w in done_waves) or '(none)'}"
    )
    status_rows = read_status(status_path)
    lines.append(
        f"- newly added rows: {', '.join(r.id for r in status_rows) or '(none)'}"
    )
    lines.append(
        f"- now in flight: {', '.join(str(d.get('task_id', '?')) for d in active) or '(none)'}"
    )
    lines.append("")
    lines.append("## 4. Next-action queue (what the new session should do first)")
    lines.append(reason or "(No explicit reason provided.)")
    lines.append("")
    lines.append("## 5. Memory pointers (so the new session loads the right context)")
    lines.append(
        "- (No explicit memory pointer tracking in v1 — operator should load relevant memory entries manually.)"
    )
    return "\n".join(lines)
