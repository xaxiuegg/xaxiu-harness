"""Operator-requested: 10 Kimi + 10 MiMo agents brainstorm orchestrator
architectures.

Each agent receives the same situation packet + asks: "given these
constraints, what's the BEST architecture?"  Goal: surface ideas
Claude hadn't considered.

Sequential dispatch (rate-limit + cost-tracking friendly).  Each
agent's response is captured + aggregated into:
    coord/coverage/brainstorm_orchestrator_<stamp>.json
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from harness.engines.concrete import get_engine  # noqa: E402


SITUATION = """\
You are advising on the design of an autonomous orchestrator for a
multi-engine LLM dispatch harness.

# Current situation

The harness ("xaxiu-harness") is a Python tool that dispatches "specs"
(markdown work orders) to one of several LLM engines:
- MiMo Pro v2.5 (Xiaomi, free via Token Plan subscription, 100% reliable
  for spec composition)
- DeepSeek v4-flash (pay-per-token ~$0.001/dispatch; reasoning-strong
  but drifts to prose+markdown on FILE/REPLACE ~50%)
- Kimi K2.6 (free via subscription; CLI is agentic, HTTP has 60s
  thinking-cap)
- Claude Code (interactive only; operator has Max subscription but no
  separate Anthropic Console API key)

The CURRENT orchestrator is Claude Opus 4.7 running interactively in a
Claude Code session (the operator triggers tasks, Claude composes specs
and dispatches them).

# Problem

When the Claude Code session ends (operator closes laptop, subscription
quota maxes out, OS reboot), the orchestrator stops.  We've verified
that spawning `claude -p` (headless Claude Code) as a subprocess from
INSIDE another Claude Code session is blocked — Anthropic's
anti-recursion guard refuses to honor OAuth for child Claude Code
processes.

The orchestrator's responsibilities:
1. Read coord/STATUS.csv → identify next TODO (light reasoning)
2. Compose a spec markdown following operator conventions
3. Fire `coord run --watch` to dispatch to a worker engine
4. Interpret results, update STATUS.csv, decide next move

# Constraints

- No Anthropic Console API key (operator deems it uneconomical).
- $0-low cost preferred ($1-5/overnight tops).
- Must work AUTONOMOUSLY (no operator presence assumed).
- Must integrate with Windows Task Scheduler (operator's environment).
- Existing engines callable: MiMo (free), DeepSeek (cheap pay-per-token),
  Kimi (free; CLI agentic, HTTP unreliable for big packets).
- Operator can keep Claude Code session running INTERACTIVELY when
  available, but architecture must not depend on this.

# Already-considered options

1. Arch A: claude -p via cron — BLOCKED by Anthropic anti-recursion when
   spawned from another Claude Code session.  Workable only if launched
   directly from Task Scheduler.
2. Arch B: single non-Claude engine (DeepSeek or MiMo) — proven working
   in pilots.
3. Arch C: hybrid (MiMo primary, DeepSeek fallback) — proven working,
   $0 typical.
4. Burst-composition: Claude session pre-composes a queue of specs,
   autonomous executor consumes the queue.
5. Anthropic Console API key — operator declined.
6. Local LLM (Ollama, Qwen) — viable backup.
7. GitHub Actions / CI — viable but adds ops overhead.

# Your task

Recommend ONE architecture (existing or novel) that BEST solves the
problem given the constraints.  Focus on:
- WHY your recommendation is better than the obvious choice (Arch C
  cron with MiMo).
- Specific implementation steps.
- What could go wrong.
- Concrete pros + cons.

Aim for 200-400 words.  Be specific and opinionated.  If you have a
novel idea not in the existing options, lay it out clearly.

# Output format

Plain text, no markdown headers, just your recommendation.
"""


ASSIGNMENTS = [
    ("kimi", "kimi-for-coding", 10),
    ("mimo", "mimo-v2.5-pro", 10),
]


@dataclass
class AgentResult:
    engine: str
    model: str
    agent_idx: int
    success: bool
    latency_ms: int
    raw_text: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    error: str | None = None


def main() -> int:
    out_dir = Path("coord/coverage")
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results: list[AgentResult] = []
    total = sum(n for _, _, n in ASSIGNMENTS)

    print(f"=== 20-agent orchestrator brainstorm ===", flush=True)
    print(f"  Kimi x10 (kimi-for-coding) + MiMo x10 (mimo-v2.5-pro)", flush=True)

    for engine_name, model, count in ASSIGNMENTS:
        eng = get_engine(engine_name, prefer_dpapi=False)
        for i in range(count):
            agent_idx = i + 1
            print(f"\n[{engine_name}/{model}] agent {agent_idx}/{count}",
                  flush=True)
            started = time.monotonic()
            try:
                resp = eng.dispatch(SITUATION, model, {})
                latency = int((time.monotonic() - started) * 1000)
                ok = bool(resp.success and (resp.text or "").strip())
                results.append(AgentResult(
                    engine=engine_name, model=model, agent_idx=agent_idx,
                    success=ok, latency_ms=latency,
                    raw_text=resp.text or "",
                    tokens_in=getattr(resp, "tokens_in", 0),
                    tokens_out=getattr(resp, "tokens_out", 0),
                    error=resp.error,
                ))
                mark = "OK" if ok else "FAIL"
                print(f"  {mark} {latency}ms len={len(resp.text or '')}",
                      flush=True)
            except Exception as exc:
                latency = int((time.monotonic() - started) * 1000)
                results.append(AgentResult(
                    engine=engine_name, model=model, agent_idx=agent_idx,
                    success=False, latency_ms=latency,
                    error=f"{type(exc).__name__}: {exc}",
                ))
                print(f"  FAIL {latency}ms exc={type(exc).__name__}",
                      flush=True)

    # Summary
    ok_count = sum(1 for r in results if r.success)
    print(f"\n=== SUMMARY ===  {ok_count}/{len(results)} agents returned",
          flush=True)
    for name, _, _ in ASSIGNMENTS:
        engine_results = [r for r in results if r.engine == name]
        ok = sum(1 for r in engine_results if r.success)
        print(f"  {name:10s}  ok={ok}/{len(engine_results)}", flush=True)

    report_path = out_dir / f"brainstorm_orchestrator_{stamp}.json"
    report_path.write_text(json.dumps({
        "run_at_utc": datetime.now(timezone.utc).isoformat(),
        "situation_chars": len(SITUATION),
        "total_agents": len(results),
        "ok": ok_count,
        "results": [asdict(r) for r in results],
    }, indent=2), encoding="utf-8")
    print(f"\nReport: {report_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
