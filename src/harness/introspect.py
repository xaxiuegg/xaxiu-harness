"""W14-INTROSPECT 2026-05-28 (Phase 2.1 of agentic-operator roadmap):
single-call capability + state snapshot.

Background
==========

A fresh Claude Code session reading only the agent-instructions snippet
at ``~/.claude/CLAUDE.md`` knows WHICH verbs exist but not WHICH state
the harness is currently in.  Agents that need to answer "is the proxy
running?  what upstream?  are the wrappers on PATH?  which engines have
working keys?" otherwise have to issue 5+ individual queries (and read
their formats).

``harness introspect`` collapses all of that into one call.  Default
output is a human-readable text overview; ``--format json`` returns a
machine-readable dict shape agents can parse.

The snapshot is READ-ONLY and skips live network probes by default
(use ``--probe`` to opt in to per-engine network round-trips, which
cost a few cents per run).
"""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


def _harness_version() -> str:
    """Return the installed package version, falling back to ``"?"``
    if introspection fails."""
    try:
        import harness as _h
        return getattr(_h, "__version__", "?")
    except Exception:
        return "?"


def _repo_root() -> Path:
    """Locate the harness repo root (where pyproject.toml lives)."""
    here = Path(__file__).resolve()
    # cli.py is at <repo>/src/harness/cli.py — adjust if move
    return here.parents[2]


# ---------------------------------------------------------------------------
# Proxy state
# ---------------------------------------------------------------------------


def _check_proxy_state() -> Dict[str, Any]:
    """Read the proxy's pid file + state.json (if present)."""
    pid_path = Path(".harness") / "proxy.pid"
    state_path = Path(".harness") / "proxy_state.json"
    result: Dict[str, Any] = {
        "running": False,
        "pid": None,
        "endpoint": None,
        "upstream": None,
        "pool_size": 0,
    }
    if pid_path.exists():
        try:
            pid = int(pid_path.read_text().strip())
            result["pid"] = pid
            # Cheap presence check — full process check is platform-specific
            # and we're in a read-only snapshot
            result["running"] = True
            result["endpoint"] = "http://127.0.0.1:7879/v1"
        except (ValueError, OSError):
            pass
    if state_path.exists():
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            result["pool_size"] = len(data.get("keys", {}))
        except (json.JSONDecodeError, OSError):
            pass
    return result


# ---------------------------------------------------------------------------
# Engine summary
# ---------------------------------------------------------------------------


def _summarize_engines() -> List[Dict[str, Any]]:
    """For each engine in the metadata registry, summarize key presence
    + protocol surfaces + ua_gating in one row each."""
    from harness.engines.metadata import list_engine_metadata
    from harness.keys import resolve_keys

    rows: List[Dict[str, Any]] = []
    for name, md in sorted(list_engine_metadata().items()):
        if md.key_env:
            try:
                keys = resolve_keys(md.key_env)
            except Exception:
                keys = {}
            key_present = bool(keys)
            key_count = len(keys)
        else:
            key_present = False
            key_count = 0
        rows.append({
            "engine": name,
            "vendor": md.vendor,
            "key_env": md.key_env,
            "key_present": key_present,
            "key_count": key_count,
            "protocols": list(md.protocol_surfaces),
            "ua_gated": bool(md.ua_gating),
            "default_model": md.default_model,
            "latency_class": md.latency_class,
            "recommended_for": list(md.recommended_task_classes),
        })
    return rows


# ---------------------------------------------------------------------------
# Agent-instructions freshness check
# ---------------------------------------------------------------------------


# Marker scheme: post-v0.5.7 the START marker carries the version
# that wrote the snippet (e.g. `<!-- W14-HARNESS-AGENT-INSTRUCTIONS-START v0.5.7 -->`).
# Pre-v0.5.7 had no version (`<!-- W14-HARNESS-AGENT-INSTRUCTIONS-START -->`).
# Both forms are detected via the prefix below.
_AI_START_MARKER_PREFIX = "<!-- W14-HARNESS-AGENT-INSTRUCTIONS-START"
_AI_END_MARKER = "<!-- W14-HARNESS-AGENT-INSTRUCTIONS-END -->"


def _check_agent_instructions() -> Dict[str, Any]:
    """Detect whether ~/.claude/CLAUDE.md has the harness snippet
    installed AND whether it matches the current template.

    Returns a dict with: ``target_path``, ``installed`` (bool),
    ``current`` (bool — matches the freshly-generated snippet),
    ``installed_hash``, ``current_hash``, ``hint``.
    """
    target = Path.home() / ".claude" / "CLAUDE.md"
    result: Dict[str, Any] = {
        "target_path": str(target),
        "installed": False,
        "current": False,
        "installed_hash": None,
        "current_hash": None,
        "installed_version": None,
        "current_version": _harness_version(),
        "hint": "",
    }

    # Compute the hash of the FRESH snippet we would install today.
    # Hash the stripped form so it matches the stripped `installed_snippet`
    # extracted below.
    try:
        from harness.cli import _agent_instructions_snippet
        fresh = _agent_instructions_snippet(
            "claude-md", _repo_root(), Path.home(),
        )
        fresh_normalised = fresh.strip()
        result["current_hash"] = hashlib.sha256(
            fresh_normalised.encode("utf-8"),
        ).hexdigest()[:12]
    except Exception:
        fresh_normalised = None

    if not target.exists():
        result["hint"] = (
            "snippet not installed.  Run "
            "`python -m harness install-agent-instructions`."
        )
        return result
    try:
        content = target.read_text(encoding="utf-8")
    except OSError:
        result["hint"] = "could not read installed CLAUDE.md"
        return result

    if _AI_START_MARKER_PREFIX not in content or _AI_END_MARKER not in content:
        result["hint"] = (
            "snippet markers not found in CLAUDE.md.  Run "
            "`python -m harness install-agent-instructions`."
        )
        return result

    result["installed"] = True
    # Locate the START line + extract the version-stamp (if any).
    # Pre-v0.5.7 installs had no version → returns empty string.
    prefix_idx = content.index(_AI_START_MARKER_PREFIX)
    start_line_end = content.index("-->", prefix_idx) + len("-->")
    start_marker_text = content[prefix_idx:start_line_end]
    import re
    vmatch = re.search(r"v([\d.]+)", start_marker_text)
    if vmatch:
        result["installed_version"] = vmatch.group(1)
    end = content.index(_AI_END_MARKER)
    installed_block = content[start_line_end:end]
    # Strip the auto-installed comment line so we hash just the snippet
    lines = installed_block.lstrip("\n").splitlines()
    if lines and lines[0].startswith("<!--"):
        lines = lines[1:]
    installed_snippet = "\n".join(lines).strip()
    result["installed_hash"] = hashlib.sha256(
        installed_snippet.encode("utf-8"),
    ).hexdigest()[:12]

    if result["current_hash"] and result["installed_hash"]:
        result["current"] = (
            result["installed_hash"] == result["current_hash"]
        )

    if not result["current"]:
        iv = result.get("installed_version") or "<unversioned>"
        cv = result.get("current_version") or "?"
        result["hint"] = (
            f"installed snippet predates the current repo "
            f"(installed v{iv} → current v{cv}).  Run "
            f"`python -m harness install-agent-instructions --force` "
            f"to refresh."
        )

    return result


# ---------------------------------------------------------------------------
# Wrapper-script summary
# ---------------------------------------------------------------------------


def _summarize_wrappers() -> Dict[str, Any]:
    """Whether per-provider Claude Code wrappers (claude-mimo etc.)
    are installed + whether their directory is on PATH."""
    result: Dict[str, Any] = {
        "wrappers": [],
        "dir": None,
        "on_path": False,
    }
    try:
        from harness.engines.wrapper_scripts import (
            DEFAULT_WRAPPER_DIR, list_wrappers,
        )
        result["dir"] = str(DEFAULT_WRAPPER_DIR)
        wrappers = list_wrappers()
        result["wrappers"] = [
            {
                "name": w["name"],
                "installed": w["installed"],
                "key_present": w["key_present"],
            }
            for w in wrappers
        ]
        # Is the wrapper dir on PATH?
        path_entries = (
            os.environ.get("PATH", "").split(os.pathsep)
        )
        normalised_wrapper_dir = str(DEFAULT_WRAPPER_DIR).lower()
        result["on_path"] = any(
            p.strip().lower() == normalised_wrapper_dir
            for p in path_entries if p.strip()
        )
    except Exception:
        pass
    return result


# ---------------------------------------------------------------------------
# Doctor summary (read-only, no live probe by default)
# ---------------------------------------------------------------------------


def _doctor_summary(probe: bool = False) -> Dict[str, Any]:
    """Run the doctor checks, summarize counts + first-issue hint."""
    try:
        from harness.doctor import run_all, overall_severity
        diagnoses = run_all(with_probe=probe)
        overall = overall_severity(diagnoses)
        counts: Dict[str, int] = {"ok": 0, "warn": 0, "fail": 0}
        first_issue: Optional[Dict[str, str]] = None
        for d in diagnoses:
            counts[d.severity] = counts.get(d.severity, 0) + 1
            if d.severity != "ok" and first_issue is None:
                first_issue = {
                    "name": d.name,
                    "severity": d.severity,
                    "message": d.message,
                    "fix": d.fix or "",
                }
        return {
            "overall": overall,
            "total_checks": len(diagnoses),
            "counts": counts,
            "first_issue": first_issue,
            "probed": probe,
        }
    except Exception as e:
        return {"overall": "unknown", "error": str(e)}


# ---------------------------------------------------------------------------
# Recent ask outputs
# ---------------------------------------------------------------------------


def _recent_asks(limit: int = 5) -> List[Dict[str, Any]]:
    """Scan coord/reviews/ask-* for the most recent N + read each
    summary.json's mode / verdict / engines."""
    reviews = _repo_root() / "coord" / "reviews"
    if not reviews.exists():
        return []
    rows: List[Dict[str, Any]] = []
    # ask dirs are timestamped — sort by name desc for newest-first
    dirs = sorted(
        [d for d in reviews.glob("ask-*") if d.is_dir()],
        reverse=True,
    )
    for d in dirs[:limit]:
        summary = d / "summary.json"
        row: Dict[str, Any] = {
            "id": d.name,
            "path": str(d),
            "mode": "?",
            "verdict": None,
            "engines": [],
            "total_cost_usd": None,
        }
        if summary.exists():
            try:
                data = json.loads(summary.read_text(encoding="utf-8"))
                row["mode"] = data.get("mode", "?")
                row["engines"] = [
                    r.get("engine", "?")
                    for r in data.get("results", [])
                ]
                row["total_cost_usd"] = data.get("total_cost_usd")
                # Audit-mode verdict — surface PASS/PARTIAL/FAIL
                v = data.get("verdict")
                if isinstance(v, dict):
                    row["verdict"] = v.get("verdict")
            except (json.JSONDecodeError, OSError):
                pass
        rows.append(row)
    return rows


# ---------------------------------------------------------------------------
# Top-level snapshot
# ---------------------------------------------------------------------------


def build_snapshot(probe: bool = False) -> Dict[str, Any]:
    """Single-call read-only snapshot of harness capability + state.

    Cheap by default (no live network).  Pass ``probe=True`` to also
    run live per-engine round-trips (costs a few cents per run).
    """
    from harness.engines.metadata import list_engine_metadata
    from harness.proxy.upstreams import list_upstreams

    return {
        "version": _harness_version(),
        "harness_path": str(_repo_root()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "verbs": {
            "ask": {
                "available": True,
                "modes": ["routed", "audit", "panel"],
                "default_mode": "routed",
            },
            "proxy": {
                "available": True,
                "upstream_options": sorted(list_upstreams().keys()),
                **_check_proxy_state(),
            },
            "engines": {
                "describe_available": True,
                "metadata_count": len(list_engine_metadata()),
            },
            "swarm": {
                "available": _check_swarm_sibling(),
                "sibling_hint": (
                    "https://github.com/xaxiuegg/xaxiu-swarm — clone "
                    "separately for agentic multi-file dispatch"
                ),
            },
        },
        "engines": _summarize_engines(),
        "agent_instructions": _check_agent_instructions(),
        "wrappers": _summarize_wrappers(),
        "doctor": _doctor_summary(probe=probe),
        "recent_asks": _recent_asks(limit=5),
    }


def _check_swarm_sibling() -> bool:
    """Best-effort check for xaxiu-swarm installed as a sibling repo
    or on PATH."""
    # Try a sibling-dir guess first
    sibling = _repo_root().parent / "xaxiu-swarm"
    if sibling.exists() and sibling.is_dir():
        return True
    # PATH lookup
    import shutil
    return bool(shutil.which("xaxiu-swarm"))


# ---------------------------------------------------------------------------
# Text rendering
# ---------------------------------------------------------------------------


def render_text(snapshot: Dict[str, Any]) -> str:
    """Render the snapshot as a human-readable text overview.

    Designed for `harness introspect` (default).  Agents can also
    parse this format heuristically, but `--format json` is the
    recommended programmatic surface.
    """
    lines: List[str] = []

    def _h1(s: str) -> None:
        lines.append("")
        lines.append(s)
        lines.append("=" * len(s))

    def _h2(s: str) -> None:
        lines.append("")
        lines.append(s)
        lines.append("-" * len(s))

    _h1(f"harness introspect — v{snapshot['version']}")
    lines.append(f"  path: {snapshot['harness_path']}")
    lines.append(f"  timestamp: {snapshot['timestamp']}")

    # Verbs
    _h2("Available verbs")
    ask = snapshot["verbs"]["ask"]
    lines.append(
        f"  harness ask                modes: {', '.join(ask['modes'])} "
        f"(default: {ask['default_mode']})"
    )
    proxy = snapshot["verbs"]["proxy"]
    proxy_status = "RUNNING" if proxy.get("running") else "stopped"
    lines.append(
        f"  harness proxy              {proxy_status}; upstreams: "
        f"{', '.join(proxy.get('upstream_options', []))}"
    )
    if proxy.get("running"):
        lines.append(
            f"                             endpoint: {proxy.get('endpoint')}, "
            f"pool: {proxy.get('pool_size')} keys"
        )
    eng = snapshot["verbs"]["engines"]
    lines.append(
        f"  harness engines describe   {eng['metadata_count']} engines "
        f"registered (run `harness engines compatibility-matrix` for the "
        f"N×M table)"
    )
    swarm = snapshot["verbs"]["swarm"]
    swarm_status = "installed" if swarm["available"] else "not installed"
    lines.append(f"  xaxiu-swarm (sibling)      {swarm_status}")

    # Engines
    _h2("Engines (Pattern B + reference)")
    for e in snapshot["engines"]:
        key_status = (
            f"key=YES ({e['key_count']})" if e["key_present"]
            else "key=missing"
        )
        ua = " [UA-gated]" if e["ua_gated"] else ""
        lines.append(
            f"  {e['engine']:<22} {key_status:<16} "
            f"protocols: {','.join(e['protocols'])}{ua}"
        )

    # Agent instructions
    _h2("Agent-instructions snippet")
    ai = snapshot["agent_instructions"]
    if not ai["installed"]:
        lines.append(f"  [X] NOT installed at {ai['target_path']}")
    elif ai["current"]:
        v = ai.get("current_version") or "?"
        lines.append(
            f"  [OK] installed at {ai['target_path']} (v{v}, current)"
        )
    else:
        iv = ai.get("installed_version") or "<unversioned>"
        cv = ai.get("current_version") or "?"
        lines.append(
            f"  [!] installed at {ai['target_path']} but STALE "
            f"(v{iv} → v{cv})"
        )
    if ai.get("hint"):
        lines.append(f"       hint: {ai['hint']}")

    # Wrappers
    _h2("Per-provider Claude Code wrappers")
    wr = snapshot["wrappers"]
    lines.append(f"  dir:      {wr.get('dir')}")
    lines.append(
        f"  on_PATH:  {'yes' if wr.get('on_path') else 'NO'}"
    )
    for w in wr.get("wrappers", []):
        flag = "[OK]" if w["installed"] else "[ ]"
        key = "key=yes" if w["key_present"] else "key=missing"
        lines.append(f"    {flag} {w['name']:<22} {key}")

    # Doctor
    _h2("Doctor summary")
    d = snapshot["doctor"]
    if "error" in d:
        lines.append(f"  doctor failed: {d['error']}")
    else:
        counts = d.get("counts", {})
        lines.append(
            f"  overall: {d.get('overall', '?').upper()}   "
            f"({counts.get('ok', 0)} OK / "
            f"{counts.get('warn', 0)} warn / "
            f"{counts.get('fail', 0)} fail; "
            f"{'live-probed' if d.get('probed') else 'cached'})"
        )
        if d.get("first_issue"):
            issue = d["first_issue"]
            lines.append(
                f"  first issue: [{issue['severity']}] {issue['name']}: "
                f"{issue['message']}"
            )
            if issue.get("fix"):
                lines.append(f"    fix: {issue['fix']}")

    # Recent asks
    _h2("Recent ask outputs (last 5)")
    asks = snapshot.get("recent_asks", [])
    if not asks:
        lines.append("  (none in coord/reviews/)")
    else:
        for a in asks:
            mode = a.get("mode") or "?"
            verdict = (
                f" verdict={a['verdict']}" if a.get("verdict") else ""
            )
            cost = (
                f" ${a['total_cost_usd']:.4f}"
                if a.get("total_cost_usd") is not None else ""
            )
            engines = ",".join(a.get("engines", []))
            lines.append(
                f"  {a['id']}   mode={mode}{verdict}"
                f"   engines={engines}{cost}"
            )

    lines.append("")
    return "\n".join(lines)
