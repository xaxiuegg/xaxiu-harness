"""W5-SS 2026-05-23: orchestrator picker for `harness start`.

Defines the 4 selectable orchestrators with metadata, connection
probes, and a uniform connection-status enum.  Lets `harness start`
render a Claude-Code-style picker without baking engine internals into
the CLI verb itself.

The four orchestrators map 1:1 to the engines in `concrete.py` plus
the OAuth-backed Claude Code path:

  claude    — `claude -p` subprocess (no API key, OAuth in keychain).
              Cannot run inside another Claude Code session (anti-recursion).
  mimo      — MiMo Pro v2.5 HTTP API (Token Plan tp- key, flat-rate).
  deepseek  — DeepSeek v4-flash HTTP API (pay-per-token sk- key).
  kimi      — Kimi K2.6 HTTP API (Token Plan tp- key, flat-rate).

Brainstorm consensus 2026-05-23 (18/20 agents): MiMo is the
brainstorm-recommended primary for production workloads.  Claude is
best for strategic planning where its multi-step reasoning shines.
DeepSeek + Kimi are specialists.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from enum import Enum
from typing import Callable


class ConnectionStatus(str, Enum):
    """Light-touch reachability indicator for an orchestrator."""
    READY = "ready"           # all preconditions met
    MISSING_KEY = "missing_key"   # env var unset
    BLOCKED = "blocked"           # e.g. anti-recursion inside Claude Code
    NOT_INSTALLED = "not_installed"  # claude binary missing


@dataclass(frozen=True)
class Orchestrator:
    """Metadata for one selectable orchestrator."""
    key: str
    label: str
    best_for: str
    cost: str
    notes: str = ""

    def env_var(self) -> str | None:
        """Env-var name the engine requires; None for OAuth-based engines."""
        return {
            "claude": None,  # OAuth, no env var
            "mimo": "MIMO_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
            "kimi": "KIMI_API_KEY_1",  # accepts KIMI_API_KEY too — see probe
        }.get(self.key)

    def probe(self) -> ConnectionStatus:
        """Best-effort reachability probe.  No network call — local checks only."""
        if self.key == "claude":
            # Refuse when running inside another Claude Code session (anti-recursion).
            if os.environ.get("CLAUDE_CODE_SSE_PORT") or os.environ.get("CLAUDECODE"):
                return ConnectionStatus.BLOCKED
            if shutil.which("claude") is None:
                return ConnectionStatus.NOT_INSTALLED
            return ConnectionStatus.READY
        env = self.env_var()
        if env is None:
            return ConnectionStatus.READY
        # Kimi accepts either KIMI_API_KEY_1 or legacy KIMI_API_KEY
        if self.key == "kimi":
            if os.environ.get("KIMI_API_KEY_1") or os.environ.get("KIMI_API_KEY"):
                return ConnectionStatus.READY
            return ConnectionStatus.MISSING_KEY
        if os.environ.get(env):
            return ConnectionStatus.READY
        return ConnectionStatus.MISSING_KEY


# Brainstorm-ordered: MiMo first (default primary), then specialists.
ORCHESTRATORS: list[Orchestrator] = [
    Orchestrator(
        key="mimo",
        label="MiMo Pro v2.5",
        best_for="spec composition, file edits, production workload",
        cost="$0 (Token Plan flat-rate)",
        notes="brainstorm-recommended primary (18/20 agents)",
    ),
    Orchestrator(
        key="claude",
        label="Claude (Code OAuth)",
        best_for="strategic planning, multi-file reasoning",
        cost="$0 (Claude Code subscription)",
        notes="OAuth in Windows keychain; "
              "BLOCKED inside another Claude Code session "
              "(use Task Scheduler for autonomous)",
    ),
    Orchestrator(
        key="deepseek",
        label="DeepSeek V4-flash",
        best_for="reasoning, planning, code review",
        cost="~$0.001 / dispatch (pay-per-token)",
        notes="4× faster post-W5-MM streaming",
    ),
    Orchestrator(
        key="kimi",
        label="Kimi K2.6",
        best_for="source-laden packets, large-context review",
        cost="$0 (Token Plan flat-rate)",
        notes="streaming fixed in W5-V (3/3 source-laden reliability)",
    ),
]


def by_key(key: str) -> Orchestrator | None:
    """Look up an orchestrator by key (returns None when unknown)."""
    for o in ORCHESTRATORS:
        if o.key == key:
            return o
    return None


def render_picker(probe_fn: Callable[[Orchestrator], ConnectionStatus] | None = None) -> str:
    """Render the picker menu as plain text.

    Returns the string the CLI verb prints before reading the operator's
    pick.  ``probe_fn`` is injectable for tests (default: each
    orchestrator's own ``probe()``).
    """
    probe = probe_fn or (lambda o: o.probe())
    lines: list[str] = ["Pick your orchestrator:"]
    lines.append("")
    for i, o in enumerate(ORCHESTRATORS, start=1):
        status = probe(o)
        if status == ConnectionStatus.READY:
            badge = "✓ ready"
        elif status == ConnectionStatus.MISSING_KEY:
            env = o.env_var() or "?"
            badge = f"✗ {env} not set"
        elif status == ConnectionStatus.BLOCKED:
            badge = "⚠ blocked (running inside Claude Code session)"
        elif status == ConnectionStatus.NOT_INSTALLED:
            badge = "✗ `claude` not on PATH"
        else:
            badge = "?"
        lines.append(f"  [{i}] {o.label:<25} {badge}")
        lines.append(f"      Best for: {o.best_for}")
        lines.append(f"      Cost:     {o.cost}")
        if o.notes:
            lines.append(f"      Notes:    {o.notes}")
        lines.append("")
    return "\n".join(lines)
