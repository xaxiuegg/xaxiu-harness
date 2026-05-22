"""Multi-engine multi-agent harness functional coverage campaign.

Each engine spawns N independent agent dispatches.  Each agent is asked to:
  1. Read the function-under-test source (embedded in the packet).
  2. Propose a one-line probe + predicted result + 3 failure modes.
  3. Output structured JSON.

Orchestrator then executes each probe, compares to prediction, records
PASS/FAIL/DEGRADED.  Surfaces functions where engines DISAGREE on health
(diagnostic gold).

Sequential dispatch (parallel = rate-limit per benchmark earlier today).
"""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.engines.concrete import get_engine  # noqa: E402


@dataclass(frozen=True)
class FUT:
    name: str            # function-under-test label
    source_path: str     # file containing it
    probe_hint: str      # what the agent should design a probe for


# Matrix: 4 engines × 5 FUTs (20 agent dispatches total)
KIMI_FUTS = [
    FUT("harness doctor", "src/harness/doctor.py",
        "Invoke `harness doctor` and parse the 6 preflight checks; predict overall."),
    FUT("observer cycle", "src/harness/observer/cycle.py",
        "Invoke `harness observer cycle-now --engine swarm/mimo` and verify dispatch_success."),
    FUT("observer audit-chat", "src/harness/observer/chat.py",
        "Invoke `harness observer audit-chat` and verify it locates a transcript."),
    FUT("state inspect", "src/harness/state/inspect.py",
        "Invoke `harness state inspect` and verify JSON or human output."),
    FUT("replay", "src/harness/replay.py",
        "Invoke `harness replay --help` and verify the CLI surface."),
]
MIMO_PRO_FUTS = [
    FUT("coord plan", "src/harness/coord/planner.py",
        "Invoke `harness coord plan --spec spec/samples/hello-world.md --engine mock` and verify plan.json."),
    FUT("coord run (mock)", "src/harness/coord/coordinator.py",
        "Invoke `harness coord run --run-id <existing> --engine swarm/mock` and verify worker spawn."),
    FUT("coord integrate", "src/harness/coord/integrator.py",
        "Invoke `harness coord integrate --run-id <existing>` and verify success/pytest pass."),
    FUT("dispatch_packet", "src/harness/engines/dispatcher.py",
        "Invoke dispatch_packet with force_engine='mimo' and verify engine_used."),
    FUT("dispatch bypass_chain", "src/harness/engines/dispatcher.py",
        "Verify that force_engine_failed_no_fallback returns when bypass_chain=True."),
]
MIMO_STD_FUTS = [
    FUT("engines list", "src/harness/cli.py",
        "Invoke `harness engines` and verify per-engine status output."),
    FUT("budget summary", "src/harness/budget.py",
        "Invoke `harness budget summary` and verify ledger row count > 0."),
    FUT("loop start/stop", "src/harness/loops/__init__.py",
        "Invoke `harness loop status` and verify a status line."),
    FUT("heartbeat", "src/harness/heartbeat.py",
        "Invoke `harness heartbeat show` and verify timestamp."),
    FUT("session ok-to-stop --json", "src/harness/session/stop_check.py",
        "Invoke `harness session ok-to-stop --json` and verify JSON payload."),
]
DEEPSEEK_FUTS = [
    FUT("STATUS.csv schema", "src/harness/status/schema.py",
        "Read coord/STATUS.csv via harness.status.store.read_status and verify row count."),
    FUT("proxy lifecycle", "src/harness/proxy/lifecycle.py",
        "Invoke `harness proxy --help` and verify CLI surface."),
    FUT("spec lint", "src/harness/lint.py",
        "Invoke `harness lint-spec --spec spec/samples/hello-world.md` and verify exit 0."),
    FUT("panic-dump", "src/harness/panic.py",
        "Invoke `harness panic-dump --target-dir tmp_panic` and verify tarball."),
    FUT("observer flags", "src/harness/observer/state.py",
        "Invoke `harness observer flags` and verify list output."),
]

ASSIGNMENTS = [
    ("kimi",     "kimi-for-coding",  KIMI_FUTS),
    ("mimo",     "mimo-v2.5-pro",    MIMO_PRO_FUTS),
    ("mimo",     "mimo-v2.5",        MIMO_STD_FUTS),
    ("deepseek", "deepseek-v4-flash", DEEPSEEK_FUTS),
]


PROBE_INSTRUCTIONS = """\
# Multi-agent coverage probe — design a test for ONE function

You are a test-design agent.  You will receive ONE function-under-test
(FUT).  Your job, in 60–120 lines:

1. Read the source provided below.
2. Propose a one-line invocation (Python `python -m harness ...` or
   Python expression) that exercises the FUT's main contract.
3. Predict the expected stdout/return shape (1–3 lines).
4. List 3 plausible failure modes (1 line each).
5. Confidence level (0.0–1.0) that the FUT works as advertised.

Output **JSON only**, no preamble or markdown fence:

```
{
  "fut": "<short name>",
  "probe": "<one-line shell-or-python invocation>",
  "expected": "<1–3 lines summary>",
  "failure_modes": ["<mode 1>", "<mode 2>", "<mode 3>"],
  "confidence": 0.0
}
```

# Function-under-test
"""


@dataclass
class AgentResult:
    engine: str
    model: str
    fut: str
    success: bool
    latency_ms: int
    raw_text: str = ""
    parsed: dict = field(default_factory=dict)
    error: str | None = None


def _build_packet(fut: FUT) -> str:
    src_text = ""
    p = Path(fut.source_path)
    if p.exists():
        try:
            src_text = p.read_text(encoding="utf-8")[:4000]  # cap to fit packet
        except OSError:
            src_text = "(could not read)"
    else:
        src_text = f"(file not found: {fut.source_path})"
    return (
        PROBE_INSTRUCTIONS
        + f"\nFUT name: {fut.name}\n"
        + f"FUT probe hint: {fut.probe_hint}\n"
        + f"\n## {fut.source_path}\n\n```python\n{src_text}\n```\n"
    )


def _extract_json(text: str) -> dict:
    """Best-effort JSON extraction from engine response."""
    import re
    # Strip code fences
    cleaned = re.sub(r"^```(?:json)?\s*", "", text.strip())
    cleaned = re.sub(r"\s*```\s*$", "", cleaned)
    # Find first { ... } JSON-like block
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if not m:
        return {}
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}


def main() -> int:
    out_dir = Path("coord/coverage")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    results: list[AgentResult] = []
    total_agents = sum(len(futs) for _, _, futs in ASSIGNMENTS)
    print(f"=== Multi-agent coverage campaign: {total_agents} agents ===", flush=True)

    for engine_name, model, futs in ASSIGNMENTS:
        eng = get_engine(engine_name, prefer_dpapi=False)
        for fut in futs:
            print(f"\n[{engine_name}/{model}] FUT={fut.name}", flush=True)
            packet = _build_packet(fut)
            started = time.monotonic()
            try:
                # For mimo, pass 'auto' so it picks Pro or Std automatically;
                # but here we want EXPLICIT Pro/Std per the matrix.
                resp = eng.dispatch(packet, model, {"max_tokens": 1500})
                latency = int((time.monotonic() - started) * 1000)
                ok = bool(resp.success and (resp.text or "").strip())
                raw = resp.text or ""
                err = resp.error
            except Exception as exc:
                latency = int((time.monotonic() - started) * 1000)
                ok = False
                raw = ""
                err = f"{type(exc).__name__}: {exc}"

            parsed = _extract_json(raw) if ok else {}
            results.append(AgentResult(
                engine=engine_name, model=model, fut=fut.name,
                success=ok and bool(parsed), latency_ms=latency,
                raw_text=raw, parsed=parsed, error=err,
            ))
            mark = "✓" if (ok and parsed) else "✗"
            print(f"  {mark} {latency}ms  parsed_keys={list(parsed.keys()) if parsed else 'EMPTY/UNPARSEABLE'}",
                  flush=True)

    # Summary
    by_engine: dict[str, dict[str, int]] = {}
    for r in results:
        by_engine.setdefault(f"{r.engine}/{r.model}", {"ok": 0, "fail": 0})
        by_engine[f"{r.engine}/{r.model}"]["ok" if r.success else "fail"] += 1

    print("\n=== summary ===", flush=True)
    for k, v in by_engine.items():
        print(f"  {k:30s}  ok={v['ok']}  fail={v['fail']}", flush=True)
    overall_ok = sum(1 for r in results if r.success)
    print(f"  TOTAL: {overall_ok}/{len(results)} agents returned parseable probe-design")

    # Persist
    report_path = out_dir / f"multi_agent_campaign_{stamp}.json"
    report_path.write_text(json.dumps({
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "total_agents": len(results),
        "ok": overall_ok,
        "by_engine": by_engine,
        "results": [asdict(r) for r in results],
    }, indent=2), encoding="utf-8")
    print(f"\nReport: {report_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
