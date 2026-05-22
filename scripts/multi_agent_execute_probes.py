"""Execute the agent-proposed probes from W4-G campaign.

Reads the most recent campaign report from coord/coverage/, takes each
parsed probe and runs it.  Records actual stdout/stderr/exit, then scores:

  PASS       — exit 0 and predicted shape roughly matches
  DEGRADED   — exit 0 but predicted shape differs
  FAIL       — exit non-zero or process crashed
  SKIP       — probe couldn't be safely executed (interactive, network-
               heavy, or needs an existing run-id we don't have)

This is a sanity scoring; not byte-exact diffing.
"""

from __future__ import annotations

import json
import shlex
import subprocess
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class ProbeResult:
    engine: str
    model: str
    fut: str
    probe: str
    expected: str
    confidence: float
    exit_code: int
    stdout: str
    stderr: str
    runtime_ms: int
    verdict: str  # PASS / DEGRADED / FAIL / SKIP
    notes: str = ""


SKIP_PATTERNS = [
    # Mock-engine run-id probes — the IDs don't exist
    ("test-run-123",   "fabricated run-id not in state"),
    ("test_run_001",   "fabricated run-id not in state"),
    ("test_run_id",    "fabricated run-id not in state"),
    # Interactive flags
    ("input(",         "interactive probe blocked"),
]


def _classify_probe(probe: str) -> tuple[bool, str]:
    """Return (skip, reason)."""
    for needle, reason in SKIP_PATTERNS:
        if needle in probe:
            return True, reason
    return False, ""


def _run_probe(probe: str, timeout: int = 30) -> tuple[int, str, str, int]:
    """Run probe as a subprocess, return (exit, stdout, stderr, ms)."""
    # Normalise:  'harness ...' / 'python -m harness ...' / 'python -c ...'
    cmd = probe.strip()
    if cmd.startswith("harness "):
        cmd = "python -m " + cmd  # python -m harness ...
    started = time.monotonic()
    try:
        # On Windows, shell=False with split args is safer than shell=True
        # but `python -c "from ..."` needs the quoted-arg preserved.
        # Use shlex.split with posix=False to keep Windows quoting.
        try:
            args = shlex.split(cmd, posix=False)
        except ValueError:
            args = cmd.split()
        proc = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(Path(__file__).resolve().parents[1]),
            env={**__import__("os").environ, "PYTHONPATH": "src"},
        )
        ms = int((time.monotonic() - started) * 1000)
        return proc.returncode, proc.stdout or "", proc.stderr or "", ms
    except subprocess.TimeoutExpired:
        ms = int((time.monotonic() - started) * 1000)
        return 124, "", "(timeout)", ms
    except FileNotFoundError as exc:
        ms = int((time.monotonic() - started) * 1000)
        return 127, "", f"command not found: {exc}", ms
    except Exception as exc:
        ms = int((time.monotonic() - started) * 1000)
        return 1, "", f"{type(exc).__name__}: {exc}", ms


def _score(exit_code: int, stdout: str, stderr: str, expected: str) -> tuple[str, str]:
    if exit_code == 0:
        # Loose shape-match: do any 3-letter words from `expected` appear in
        # actual stdout/stderr?  Heuristic; we mark anything passing
        # exit-0 but with no overlap as DEGRADED.
        sample = " ".join((stdout + " " + stderr).lower().split())
        if not sample:
            return "DEGRADED", "exit=0 but empty stdout/stderr"
        # extract keywords from expected (>= 4 chars, not common)
        STOP = {"with", "from", "that", "this", "have", "shows", "output",
                "outputs", "exit", "code", "string", "boolean", "json",
                "list", "may", "be", "an", "the", "for", "and", "or",
                "in", "of", "to", "a"}
        keywords = [w for w in expected.lower().split() if len(w) >= 4 and w not in STOP]
        hits = sum(1 for kw in keywords[:8] if kw in sample)
        if hits >= 1:
            return "PASS", f"exit=0, keyword-overlap={hits}/{min(8, len(keywords))}"
        return "DEGRADED", f"exit=0 but no keyword overlap (expected={expected[:80]!r})"
    if exit_code == 124:
        return "FAIL", "timeout"
    if exit_code == 127:
        return "FAIL", "command not found"
    return "FAIL", f"exit={exit_code}, stderr={stderr[:120]!r}"


def main() -> int:
    cov_dir = Path("coord/coverage")
    reports = sorted(cov_dir.glob("multi_agent_campaign_*.json"))
    if not reports:
        print("no campaign reports found", flush=True)
        return 2
    src = reports[-1]
    data = json.loads(src.read_text(encoding="utf-8"))
    print(f"Loading {src.name} ({data['ok']}/{data['total_agents']} parseable)", flush=True)

    results: list[ProbeResult] = []
    for r in data["results"]:
        if not r["success"]:
            continue  # No probe to execute — agent failed to design one
        p = r["parsed"]
        probe = (p.get("probe") or "").strip()
        if not probe:
            continue
        skip, reason = _classify_probe(probe)
        if skip:
            print(f"  SKIP  [{r['engine']}/{r['model']}] {r['fut']}: {reason}", flush=True)
            results.append(ProbeResult(
                engine=r["engine"], model=r["model"], fut=r["fut"],
                probe=probe, expected=p.get("expected", ""),
                confidence=float(p.get("confidence", 0.0)),
                exit_code=-1, stdout="", stderr="", runtime_ms=0,
                verdict="SKIP", notes=reason,
            ))
            continue

        print(f"  EXEC  [{r['engine']}/{r['model']}] {r['fut']}: {probe[:80]}", flush=True)
        exit_code, stdout, stderr, ms = _run_probe(probe)
        verdict, notes = _score(exit_code, stdout, stderr, p.get("expected", ""))
        print(f"        -> {verdict} ({ms}ms) {notes}", flush=True)
        results.append(ProbeResult(
            engine=r["engine"], model=r["model"], fut=r["fut"],
            probe=probe, expected=p.get("expected", ""),
            confidence=float(p.get("confidence", 0.0)),
            exit_code=exit_code, stdout=stdout[:500],
            stderr=stderr[:500], runtime_ms=ms,
            verdict=verdict, notes=notes,
        ))

    # Summary
    by_verdict: dict[str, int] = {}
    for r in results:
        by_verdict[r.verdict] = by_verdict.get(r.verdict, 0) + 1

    by_fut: dict[str, list[tuple[str, str]]] = {}  # fut → [(engine, verdict), ...]
    for r in results:
        by_fut.setdefault(r.fut, []).append((f"{r.engine}/{r.model}", r.verdict))

    print("\n=== probe-execution summary ===", flush=True)
    for v, n in sorted(by_verdict.items()):
        print(f"  {v:9s} {n}", flush=True)

    # Cross-engine agreement: if same FUT executed by multiple engines, do
    # they agree?  (this campaign has each FUT by a single engine, so no
    # multi-engine FUTs — but report shape supports it for future runs.)
    disagreements = [(fut, marks) for fut, marks in by_fut.items()
                     if len({m[1] for m in marks}) > 1]
    if disagreements:
        print("\n=== cross-engine disagreement ===", flush=True)
        for fut, marks in disagreements:
            print(f"  {fut}: " + ", ".join(f"{e}={v}" for e, v in marks), flush=True)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = Path("coord/coverage") / f"multi_agent_execute_{stamp}.json"
    out.write_text(json.dumps({
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_campaign": src.name,
        "by_verdict": by_verdict,
        "by_fut": by_fut,
        "disagreements": disagreements,
        "results": [asdict(r) for r in results],
    }, indent=2), encoding="utf-8")
    print(f"\nReport: {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
