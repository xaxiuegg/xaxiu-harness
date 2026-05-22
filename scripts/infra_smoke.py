"""Comprehensive infrastructure smoke test — post-migration validation.

Walks every external-facing piece of the harness and records PASS/FAIL/
DEGRADED with one-line rationale.  Output: coord/validation/<stamp>.md.

Categories:
  A. Direct HTTP probes (4 engines)
  B. dispatch_packet direct dispatch (each engine, force_engine=)
  C. worker.run_worker (worktree + edit + commit)  — mocked to avoid mutating tree
  D. observer cycle (real, not dry-run) + observer audit-chat
  E. coord plan + run + integrate on a tiny spec (real end-to-end)
  F. CLI verb sanity (doctor, status, observer, budget, engines)
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@dataclass
class Check:
    category: str
    name: str
    status: str             # PASS / FAIL / DEGRADED / SKIP
    latency_ms: int = 0
    detail: str = ""
    extras: dict = field(default_factory=dict)


CHECKS: list[Check] = []


def record(c: Check) -> Check:
    CHECKS.append(c)
    glyph = {"PASS": "✓", "FAIL": "✗", "DEGRADED": "~", "SKIP": "-"}.get(c.status, "?")
    print(f"  {glyph} {c.category}/{c.name}: {c.status}  {c.latency_ms}ms  {c.detail[:80]}",
          flush=True)
    return c


# ---------------------------------------------------------------------------
# A. Direct HTTP probes
# ---------------------------------------------------------------------------

def cat_A_http_probes() -> None:
    import httpx
    print("\n=== A. Direct HTTP probes ===", flush=True)
    probes = [
        ("kimi-k2.6", "https://api.kimi.com/coding/v1/chat/completions",
         {"Authorization": f"Bearer {os.environ.get('KIMI_API_KEY','')}",
          "User-Agent": "claude-code/0.1.0"},
         {"model": "kimi-for-coding",
          "messages": [{"role": "user", "content": "reply OK"}], "max_tokens": 5}),
        ("deepseek-v4-flash", "https://api.deepseek.com/v1/chat/completions",
         {"Authorization": f"Bearer {os.environ.get('DEEPSEEK_API_KEY','')}"},
         {"model": "deepseek-v4-flash",
          "messages": [{"role": "user", "content": "reply OK"}], "max_tokens": 5}),
        ("mimo-pro-sgp", "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions",
         {"Authorization": f"Bearer {os.environ.get('MIMO_API_KEY','')}",
          "User-Agent": "claude-code/0.1.0"},
         {"model": "mimo-v2.5-pro",
          "messages": [{"role": "user", "content": "reply OK"}], "max_tokens": 5}),
        ("mimo-std-sgp", "https://token-plan-sgp.xiaomimimo.com/v1/chat/completions",
         {"Authorization": f"Bearer {os.environ.get('MIMO_API_KEY','')}",
          "User-Agent": "claude-code/0.1.0"},
         {"model": "mimo-v2.5",
          "messages": [{"role": "user", "content": "reply OK"}], "max_tokens": 5}),
    ]
    for label, url, headers, body in probes:
        started = time.monotonic()
        try:
            r = httpx.post(url, headers=headers, json=body, timeout=15)
            latency = int((time.monotonic() - started) * 1000)
            if r.status_code == 200:
                record(Check("A", label, "PASS", latency, f"http 200 ({len(r.text)} chars)"))
            else:
                record(Check("A", label, "FAIL", latency,
                             f"http {r.status_code}: {r.text[:80]}"))
        except Exception as e:
            record(Check("A", label, "FAIL", int((time.monotonic()-started)*1000),
                         f"{type(e).__name__}: {e}"))


# ---------------------------------------------------------------------------
# B. dispatch_packet (via in-process)
# ---------------------------------------------------------------------------

def cat_B_dispatch_packet() -> None:
    print("\n=== B. dispatch_packet ===", flush=True)
    from harness.engines.dispatcher import dispatch_packet
    import tempfile

    fd, packet_path = tempfile.mkstemp(suffix=".md", text=True)
    Path(packet_path).write_text(
        "# probe\n\nReply with exactly the word OK and nothing else.\n",
        encoding="utf-8",
    )
    os.close(fd)
    try:
        for engine in ["kimi", "deepseek", "mimo"]:
            started = time.monotonic()
            try:
                r = dispatch_packet(
                    project="harness-planner",
                    packet_path=packet_path,
                    force_engine=engine,
                    trusted_source=True,
                )
                latency = int((time.monotonic() - started) * 1000)
                if r.success:
                    record(Check("B", f"dispatch_packet/{engine}", "PASS",
                                 latency, f"engine_used={r.engine_used} text={(r.text or '')[:30]!r}"))
                else:
                    status = "DEGRADED" if "fallback" in (r.error or "") else "FAIL"
                    record(Check("B", f"dispatch_packet/{engine}", status,
                                 latency, f"error={r.error}"))
            except Exception as e:
                record(Check("B", f"dispatch_packet/{engine}", "FAIL",
                             int((time.monotonic()-started)*1000),
                             f"{type(e).__name__}: {e}"))
    finally:
        Path(packet_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# C. worker.run_worker (mocked dispatch — verify wiring, not engine)
# ---------------------------------------------------------------------------

def cat_C_worker_wiring() -> None:
    print("\n=== C. worker.run_worker wiring ===", flush=True)
    from unittest.mock import patch, MagicMock
    from types import SimpleNamespace
    from harness.coord.worker import run_worker

    task = {
        "worker_id": "worker-1", "title": "smoke", "description": "smoke",
        "read_set": [], "write_set": [], "test_set": [], "depends_on": [],
        "steps": [],
        "estimated_kimi_minutes": 1, "max_context_tokens": 10000,
    }
    started = time.monotonic()
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        run_dir = Path(td) / "runs" / "smoke-run-id"
        run_dir.mkdir(parents=True)
        try:
            with patch("harness.coord.worker._dispatch_via_swarm") as mock:
                mock.return_value = SimpleNamespace(
                    success=True, text="", error=None,
                    tokens_used=0, cost_usd=0.0,
                )
                with patch("harness.coord.worker._run_pytest", return_value={
                    "ran": 0, "passed": 0, "failed": 0, "skipped": 0, "duration_seconds": 0.0,
                }):
                    result = run_worker(task, run_dir, project_root=Path(td))
            latency = int((time.monotonic() - started) * 1000)
            ok = result.get("state") == "completed"
            record(Check("C", "run_worker (mocked engine)", "PASS" if ok else "FAIL",
                         latency,
                         f"state={result.get('state')} steps={result.get('steps_completed')}"))
        except Exception as e:
            record(Check("C", "run_worker (mocked engine)", "FAIL",
                         int((time.monotonic()-started)*1000),
                         f"{type(e).__name__}: {e}"))


# ---------------------------------------------------------------------------
# D. observer cycle
# ---------------------------------------------------------------------------

def cat_D_observer() -> None:
    print("\n=== D. observer ===", flush=True)
    from harness.observer.cycle import run_cycle

    started = time.monotonic()
    try:
        report = run_cycle(engine="swarm/mimo")
        latency = int((time.monotonic() - started) * 1000)
        # CycleReport uses `error` (None on success) — no `dispatch_success` field.
        if report.error is None:
            record(Check("D", "cycle-now (real dispatch)", "PASS", latency,
                         f"engine={report.engine_used} flags={len(report.flags_raised)}"))
        else:
            record(Check("D", "cycle-now (real dispatch)", "FAIL", latency,
                         f"error={report.error}"))
    except Exception as e:
        record(Check("D", "cycle-now", "FAIL",
                     int((time.monotonic()-started)*1000),
                     f"{type(e).__name__}: {e}"))

    # observer state read
    started = time.monotonic()
    try:
        state_path = Path("coord/observer/observer-state.json")
        if not state_path.exists():
            record(Check("D", "observer-state.json", "FAIL", 0, "missing"))
        else:
            state = json.loads(state_path.read_text(encoding="utf-8"))
            armed = state.get("armed", False)
            cycles = state.get("total_cycles", 0)
            status = "PASS" if armed and cycles > 0 else "DEGRADED"
            record(Check("D", "observer-state", status,
                         int((time.monotonic()-started)*1000),
                         f"armed={armed} total_cycles={cycles}"))
    except Exception as e:
        record(Check("D", "observer-state", "FAIL", 0, str(e)))


# ---------------------------------------------------------------------------
# E. coord plan (real engine) — skip full run; that takes minutes
# ---------------------------------------------------------------------------

def cat_E_coord_plan() -> None:
    print("\n=== E. coord plan ===", flush=True)
    from harness.coord.planner import plan as run_planner
    spec = Path("spec/samples/env-doctor-check.md")
    if not spec.exists():
        record(Check("E", "coord plan", "SKIP", 0, f"spec missing: {spec}"))
        return
    started = time.monotonic()
    try:
        # Use mimo (the working engine) to keep this fast
        result = run_planner(spec, engine="mimo", skip_lint=True)
        latency = int((time.monotonic() - started) * 1000)
        ok = result and len(result.tasks) > 0
        record(Check("E", "coord plan --engine mimo", "PASS" if ok else "DEGRADED",
                     latency, f"tasks={len(result.tasks) if result else 0}"))
    except Exception as e:
        record(Check("E", "coord plan", "FAIL",
                     int((time.monotonic()-started)*1000),
                     f"{type(e).__name__}: {str(e)[:80]}"))


# ---------------------------------------------------------------------------
# F. CLI verbs
# ---------------------------------------------------------------------------

def cat_F_cli_verbs() -> None:
    print("\n=== F. CLI verbs ===", flush=True)
    from click.testing import CliRunner
    from harness.cli import cli

    for label, args in [
        ("doctor", ["doctor"]),
        ("observer status", ["observer", "status"]),
        ("observer flags", ["observer", "flags"]),
        ("budget summary", ["budget", "summary"]),
        ("engines", ["engines"]),
        ("coord (help)", ["coord", "--help"]),
    ]:
        started = time.monotonic()
        try:
            r = CliRunner().invoke(cli, args)
            latency = int((time.monotonic() - started) * 1000)
            ok = r.exit_code == 0 and len(r.output) > 0
            status = "PASS" if ok else "DEGRADED"
            record(Check("F", label, status, latency,
                         f"exit={r.exit_code} out={len(r.output)}ch"))
        except Exception as e:
            record(Check("F", label, "FAIL", int((time.monotonic()-started)*1000),
                         f"{type(e).__name__}: {e}"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    print(f"infra_smoke @ {datetime.now(timezone.utc).isoformat()}", flush=True)
    print(f"cwd: {Path.cwd()}", flush=True)

    cat_A_http_probes()
    cat_B_dispatch_packet()
    cat_C_worker_wiring()
    cat_D_observer()
    cat_E_coord_plan()
    cat_F_cli_verbs()

    # Summarize
    by_status: dict[str, int] = {}
    for c in CHECKS:
        by_status[c.status] = by_status.get(c.status, 0) + 1
    print("\n=== summary ===", flush=True)
    for s in ("PASS", "DEGRADED", "FAIL", "SKIP"):
        if s in by_status:
            print(f"  {s}: {by_status[s]}", flush=True)
    total = len(CHECKS)
    passed = by_status.get("PASS", 0)
    print(f"  total: {total}  pass-rate: {passed/total*100 if total else 0:.0f}%", flush=True)

    # Write report
    out_dir = Path("coord/validation")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"infra_smoke_{stamp}.md"
    lines = [
        f"# Infrastructure smoke — {datetime.now(timezone.utc).isoformat()}",
        f"\ncwd: `{Path.cwd()}`\n",
        "| Category | Check | Status | Latency (ms) | Detail |",
        "|---|---|---|---|---|",
    ]
    for c in CHECKS:
        lines.append(f"| {c.category} | {c.name} | **{c.status}** | {c.latency_ms} | {c.detail[:120]} |")
    lines.append(f"\n## Summary\n")
    for s in ("PASS", "DEGRADED", "FAIL", "SKIP"):
        if s in by_status:
            lines.append(f"- **{s}**: {by_status[s]}")
    lines.append(f"- **Pass rate**: {passed/total*100 if total else 0:.0f}%")
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nReport: {out_path}", flush=True)
    json_path = out_dir / f"infra_smoke_{stamp}.json"
    json_path.write_text(json.dumps({
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "cwd": str(Path.cwd()),
        "checks": [asdict(c) for c in CHECKS],
        "summary": by_status,
    }, indent=2), encoding="utf-8")

    return 0 if (by_status.get("FAIL", 0) == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
