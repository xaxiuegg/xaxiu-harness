"""Master audit panel — 20 MiMo + 20 Kimi reviewers.

Operator directive 2026-05-24: pull a master audit of the post-W8
harness state.  40 personas, each scoped to a distinct lens, run in
parallel batches.  Output: per-persona response + SYNTHESIS.md
roll-up at ``coord/reviews/master-audit/``.

Concurrency: capped at 20 in-flight per engine (matches xaxiu-swarm
calibration of ~18 for kimi-api 3-key pool).  Total wall-time
should be ~3 minutes (two batches at ~90s each).
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness.engines.concrete import get_engine  # noqa: E402

OUT_DIR = REPO_ROOT / "coord" / "reviews" / "master-audit"
MAX_CONCURRENT = 20


# -- gather objective evidence ---------------------------------------------


def _run_harness_cmd(args: list[str], timeout: int = 30) -> str:
    """Run a `harness ...` subcommand and capture its stdout (truncated)."""
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "harness", *args],
            cwd=REPO_ROOT,
            capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "PYTHONPATH": "src"},
        )
        return (proc.stdout or proc.stderr or "")[:4000]
    except Exception as exc:
        return f"<FAILED: {exc}>"


def _gather_snapshot() -> str:
    """One snapshot fed to every reviewer.  Captures harness's current state."""
    parts: list[str] = []

    # 1. Wave 8 closeout doc
    closeout = REPO_ROOT / "coord" / "reviews" / "wave-8-closeout.md"
    if closeout.exists():
        parts.append("## Wave 8 closeout\n\n"
                     + closeout.read_text(encoding="utf-8")[:6000])

    # 2. CLI verb tree
    parts.append("## `harness --help` (CLI verb tree)\n\n```\n"
                 + _run_harness_cmd(["--help"], 15) + "\n```")

    # 3. Preflight (no engine probes — keep audit cheap)
    parts.append("## `harness preflight --skip-engines`\n\n```\n"
                 + _run_harness_cmd(["preflight", "--skip-engines"], 30)
                 + "\n```")

    # 4. `harness today` (operator daily pulse — W8-STATUS-HUMAN)
    parts.append("## `harness today`\n\n```\n"
                 + _run_harness_cmd(["today", "--since-hours", "48"], 30)
                 + "\n```")

    # 5. STATUS.csv head + tail
    try:
        csv = (REPO_ROOT / "coord" / "STATUS.csv").read_text(
            encoding="utf-8"
        ).splitlines()
        sample = csv[:3] + ["...", f"({len(csv) - 8} rows omitted)", "..."] + csv[-5:]
        parts.append(f"## STATUS.csv ({len(csv)} rows)\n\n```csv\n"
                     + "\n".join(sample) + "\n```")
    except Exception as exc:
        parts.append(f"## STATUS.csv — FAILED: {exc}")

    # 6. Recent commits
    try:
        proc = subprocess.run(
            ["git", "log", "--oneline", "-25"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=10,
        )
        parts.append("## Recent commits (last 25)\n\n```\n"
                     + (proc.stdout or "")[:3000] + "\n```")
    except Exception as exc:
        parts.append(f"## git log — FAILED: {exc}")

    # 7. Test count + skip count
    parts.append("## Test count\n\n"
                 "**1576 passed + 6 skipped** as of HEAD (commit `ee0b693`).\n"
                 "Wave 7 close: 1544 passed + 6 skipped.  Net +32 tests in W8.\n")

    # 8. Mutation kill rate sweep (W6-A3 → W7 → W8 stable)
    parts.append("""\
## Mutation kill rate — top 5 modules

| Module | W6 sweep | W7 sweep | Status |
| --- | --- | --- | --- |
| `engines/dispatcher.py` | 17.30 | (n/a) | high |
| `coord/integrator.py` | 5.00 | (n/a) | gate-passing |
| `engines/concrete.py` | 1.00 | 3.33 | recovered |
| `coord/worker.py` | 0.00 | 4.00 | recovered |
| `orchestrator.py` | 0.00 | 3.00 | recovered |

All five exceed the ≥3 gate.  W8 did not re-run the full sweep.
""")

    # 9. Operator + memory constraints
    parts.append("""\
## Operator profile + standing constraints

- Non-technical operator (memory `user_non_technical_role`); can edit YAML,
  run CLI commands, manage Windows Task Scheduler.  Cannot author Python.
- Full dev authority (memory `feedback_xaxiu_harness_full_dev_authority`):
  Claude commits, pushes, dispatches, installs deps without
  per-action confirmation.  Only L5 errors escalate.
- Engine routing (memory `feedback_engine_routing_2026_05_11`):
  Kimi-first non-V-file, DeepSeek for V-file + math + ship-critical,
  Claude in-session only.
- Audit policy (memory `feedback_audit_every_wn_action`):
  every Wn row gets a MiMo audit before "done".
""")

    # 10. Recent W8 audit roll-up (the 3-sweep history)
    parts.append("""\
## W8 audit roll-up (three MiMo sweeps post-Wave-8)

| Row | Sweep1 | Sweep2 | Sweep3 | Net |
| --- | --- | --- | --- | --- |
| W8-PREFLIGHT-FIX | 0.65 STOP | 0.85 PASS | 0.85 PASS | HARD PASS |
| W7-MUTATION-ORCH | 0.40 STOP | 0.85 PASS | 0.74 PASS | HARD PASS |
| W8-ENGINES-HEAL | 0.58 STOP | 0.85 PASS | 0.68 STOP | Non-det |
| W8-STATUS-HUMAN | 0.65 STOP | 0.75 PASS | 0.60 STOP | Non-det |
| W8-OPERATOR-RUNBOOK | 0.85 PASS | 0.40 STOP | 0.58 STOP | Non-det |
| W8-STOP-HOOK | 0.40 STOP | 0.35 STOP | 0.40 STOP | Persistent STOP |
| W8-AUDIT-PROMPT | 0.40 STOP | 0.20 STOP | 0.25 STOP | Persistent STOP |

The 3 non-det rows flipped PASS↔STOP with NO code change between
sweeps 2 and 3.  MiMo non-determinism, accepted-as-shipped per
W6-PANEL precedent.  Wave 9 candidate `W9-AUDIT-NONDETERMINISM-AVG`
queued to add --avg-of-N.
""")

    return "\n\n".join(parts)


# 20 MiMo personas — systematic / spec-grounded
MIMO_PERSONAS: list[tuple[str, str]] = [
    ("M01-INSTALL",
     "FRESH-INSTALL REVIEWER.  Clone the repo, get to `harness preflight` "
     "green in <30 min.  No Python knowledge.  Find every step where the "
     "operator gets stuck.  What's the ACTUAL cold-start path?"),
    ("M02-CLI-COMPLETENESS",
     "CLI COMPLETENESS REVIEWER.  60+ subcommands across 22 verbs.  Does "
     "the CLI cover the operator's lifecycle (install → daily run → recover "
     "→ retro → debug)?  What's missing?  What's redundant?"),
    ("M03-OPERATOR-DAILY",
     "OPERATOR DAILY-FLOW REVIEWER.  Daily / weekly / monthly cadences.  "
     "What does the operator actually do each morning?  Each week?  Each "
     "month?  Is the cadence supported by the verbs that exist today?"),
    ("M04-OBSERVABILITY",
     "OBSERVABILITY REVIEWER.  Can the operator see what the harness is "
     "doing?  STATUS.csv, dashboard, morning-brief, today, replay, observer "
     "flags.  Where are the surfaces good?  Where do they have to dig?"),
    ("M05-ERROR-RECOVERY",
     "ERROR RECOVERY REVIEWER.  When something breaks, can the operator "
     "fix it without a Python bug report?  L5 escalation contract, doctor "
     "+ preflight outputs, engines-heal.  Find a real failure that blocks "
     "the operator dead."),
    ("M06-AUDIT-GATE",
     "AUDIT GATE INTEGRITY REVIEWER.  W8 ended with 7 PASS / 3 STOP per "
     "the audit sweep.  The 3 STOPs flipped PASS↔STOP across runs.  Is "
     "the MiMo audit gate actually catching regressions or is it noise?  "
     "What's the false-positive + false-negative rate?"),
    ("M07-MUTATION-COVERAGE",
     "MUTATION COVERAGE REVIEWER.  5/5 hot modules above the ≥3 kill rate "
     "gate.  Is that the right bar?  Is the bar sustainable as the "
     "codebase grows?  What modules are CURRENTLY untested by mutations?"),
    ("M08-ENGINE-RELIABILITY",
     "ENGINE RELIABILITY REVIEWER.  Dispatcher fallback chain, dead-engine "
     "alarm (W6-C2), engine_health, quarantine + recovering states "
     "(W8-ENGINES-HEAL).  Is the engine layer robust against a single "
     "engine collapsing?"),
    ("M09-SECURITY-POSTURE",
     "SECURITY REVIEWER.  DPAPI for keys, JSONL+redact for logs, "
     "0600 file mode.  What's the worst secret-leak path?  Is the "
     "injection scanner load-bearing?  Where does trust depend on env?"),
    ("M10-STATE-ATOMICITY",
     "STATE ATOMICITY REVIEWER.  state/*.json + state/db.sqlite + "
     "yaml configs.  Are writes atomic?  Recoverable?  What happens on "
     "kill -9 mid-write?  Is StateFileCorruptError ever observed?"),
    ("M11-CONCURRENCY",
     "CONCURRENCY REVIEWER.  ThreadPoolExecutor in preflight, "
     "asyncio in coord, multiprocessing in mutation sweeps, lock files "
     "in scheduled_tasks.lock.  Where are the data races?  Where's the "
     "happens-before?"),
    ("M12-V2-COORD",
     "v2 COORD CORRECTNESS REVIEWER.  planner / worker / integrator / "
     "coordinator.  Worktrees, checkpoint, progress-stream, "
     "single-worker directive.  Where's the cross-worker contract drift "
     "still possible?"),
    ("M13-PROXY-SAFETY",
     "PROXY SAFETY REVIEWER.  v2/A — 4-key proxy + circuit breaker + "
     "auto-quarantine on flap.  Is the proxy actually safer than direct "
     "HTTPS?  Where's the failure-mode analysis weak?"),
    ("M14-OBSERVER-DESIGN",
     "OBSERVER DESIGN REVIEWER.  Chat / audit / retro observers via "
     "Task Scheduler.  Does the observer actually catch what it should?  "
     "Is the flag triage workflow operator-grade?"),
    ("M15-DASHBOARD-UX",
     "DASHBOARD UX REVIEWER.  FastAPI + WebSocket at 7878.  /v2/* JSON, "
     "HTML detail, cost panel.  Does the dashboard surface the right "
     "things at the right time?  What's missing?"),
    ("M16-TEST-QUALITY",
     "TEST QUALITY REVIEWER.  1576 pass.  Beyond raw count: are the tests "
     "behavioral or mock-heavy?  Pick 3 modules at random and rate the "
     "test quality.  Where's the dead test code?"),
    ("M17-DOCS-ACCURACY",
     "DOCS ACCURACY REVIEWER.  spec/* directory, README, CLAUDE.md.  "
     "Does the doc match the code?  Where's the documentation lying?  "
     "Where's the documentation missing?"),
    ("M18-STATUS-CSV-DISCIPLINE",
     "STATUS.csv DISCIPLINE REVIEWER.  ~280 rows.  Is the canonical tracker "
     "actually tracking?  Are statuses fresh?  Notes accurate?  Or has "
     "it drifted into 'tag every commit' noise?"),
    ("M19-WAVE-DISCIPLINE",
     "WAVE DISCIPLINE REVIEWER.  Wave plan → wave execute → wave audit → "
     "wave closeout.  Have W6/W7/W8 actually followed this loop?  Where "
     "has the discipline slipped?  Is the cadence sustainable?"),
    ("M20-RISK-PROFILE",
     "RISK PROFILE REVIEWER.  Step back: what are the top 5 RISKS to "
     "the harness over the next 30 days?  Cost overrun, engine collapse, "
     "data corruption, key revocation, scope creep — assess.  Quantify "
     "where you can."),
]


# 20 Kimi personas — broader / pragmatic / agentic
KIMI_PERSONAS: list[tuple[str, str]] = [
    ("K01-ONBOARDING",
     "ONBOARDING FRICTION REVIEWER.  Fresh operator, fresh clone, fresh "
     "machine.  Count the operator decisions on the path from clone "
     "to first successful `harness preflight`.  Where do you get "
     "stuck?  What's the actual fail-rate of a first attempt?"),
    ("K02-DOCS-CLARITY",
     "DOCS CLARITY REVIEWER.  README + CLAUDE.md + docs/OPERATOR_RUNBOOK.md + "
     "spec/*.  Rate each on (a) is the audience clear, (b) is it "
     "current, (c) does it answer the question it claims to answer."),
    ("K03-FAILURE-MODES",
     "FAILURE MODE TAXONOMY REVIEWER.  List the top 7 failure modes a "
     "real operator hits in their first 30 days.  For each: blast "
     "radius, recovery action, time-to-recover.  Sort by frequency × "
     "impact."),
    ("K04-CLI-ERGONOMICS",
     "CLI ERGONOMICS REVIEWER.  22 top-level verbs, 60+ subcommands.  Are "
     "verb names consistent?  Is `--help` enough?  Pick 3 verbs at "
     "random and rate the discoverability of their subcommands."),
    ("K05-HONEST-READINESS",
     "HONEST READINESS REVIEWER.  Cut through the impressive numbers "
     "(1576 tests, 8 W7 rows, 7 W8 rows).  Would YOU hand this harness "
     "to a non-technical operator and tell them to run it for 30 days "
     "without your help?  If no, what concretely is missing?"),
    ("K06-DOGFOOD",
     "DOGFOOD REVIEWER.  Does the harness use itself well?  Does it "
     "self-host the dev loop?  Does it audit its own audits?  Is the "
     "meta-layer healthy or a tower of indirection?"),
    ("K07-DEAD-CODE",
     "DEAD CODE REVIEWER.  Stubs, pending-wave verbs, unfinished "
     "scaffolding.  How much of the 22-verb CLI is actually live "
     "vs. 'pending Wave N'?  Quantify."),
    ("K08-PERFORMANCE",
     "PERFORMANCE REVIEWER.  Preflight ~5s with --skip-engines.  Dispatch "
     "latency.  Audit prompt latency (~60-90s per row).  What's the "
     "slowest hot path?  What's the throughput ceiling per session?"),
    ("K09-COSTS-BUDGET",
     "COSTS + BUDGET METER REVIEWER.  W6-A2 wired tokens through the "
     "ledger.  Is the budget meter trustworthy?  Can the operator "
     "answer 'how much did this session cost' in one command?"),
    ("K10-MULTI-ENGINE",
     "MULTI-ENGINE DISCIPLINE REVIEWER.  Kimi + DeepSeek + MiMo + "
     "Anthropic + Gemini + Mock.  Is the engine slot policy "
     "(`subscription cost: keep Kimi slots full`) enforced?  Are "
     "cooldowns respected?"),
    ("K11-AUDIT-NONDETERMINISM",
     "AUDIT NON-DETERMINISM REVIEWER.  3 W8 rows flipped PASS↔STOP "
     "across sweeps with no code change.  Is the audit gate's noise "
     "floor higher than its signal?  How should it be calibrated?"),
    ("K12-REPLAY",
     "REPLAY USEFULNESS REVIEWER.  `harness replay` exists for v1 and v2 "
     "coord runs.  When would the operator actually invoke it?  Is the "
     "decision-archaeology UX usable or just data?"),
    ("K13-SESSION-HANDOFF",
     "SESSION HANDOFF REVIEWER.  W2-ish session-handoff monitor with "
     "proactive transfer rec.  When the autonomous loop wants to hand "
     "control back, does it do so clearly?  Does the operator know "
     "what to do?"),
    ("K14-LOOP-PRODUCTION",
     "LOOP PRODUCTION REVIEWER.  `harness loop init/tick/start/stop/"
     "status`.  Is the productized dev-loop primitive operator-grade?  "
     "Does it survive a kill+restart?"),
    ("K15-COORD-V2-MATURITY",
     "v2 COORD MATURITY REVIEWER.  Multi-agent w/ worktrees, "
     "checkpoint, progress-stream, integrator.  Is v2 production-"
     "ready for unattended runs, or is it still demo-ware?"),
    ("K16-SPEC-CULTURE",
     "SPEC CULTURE REVIEWER.  spec/*.md is the design surface.  Do "
     "specs lead implementation, or are they retroactively edited?  "
     "Pick a spec and check freshness against code."),
    ("K17-AUTHORITY-DISCIPLINE",
     "DEV AUTHORITY DISCIPLINE REVIEWER.  Claude has full dev authority "
     "in xaxiu-harness — commits, pushes, dispatches without approval.  "
     "Where's the discipline check?  What stops Claude from going off "
     "the rails over a long horizon?"),
    ("K18-SCOPE-CREEP",
     "SCOPE CREEP REVIEWER.  W6 → W7 → W8.  Each wave adds more "
     "verbs, more state, more tests.  Is the harness converging "
     "toward done, or sprawling toward never-done?  How big is too "
     "big?"),
    ("K19-INTERACTION-FRICTION",
     "INTERACTION FRICTION REVIEWER.  How many operator-Claude turns "
     "to get a typical feature shipped?  Where's the friction "
     "(specs, dispatches, approvals)?  Can it be cut in half?"),
    ("K20-NEXT-WAVE",
     "NEXT WAVE RECOMMENDATION REVIEWER.  Given the post-W8 state, what "
     "should Wave 9 PRIMARILY focus on?  Stack-rank: detection, "
     "operator UX, engine reliability, v2 maturity, scope reduction.  "
     "Defend the #1 choice."),
]


_RUBRIC = """\
You are one of 40 master-audit reviewers.  Read the state snapshot,
then answer through YOUR specific lens (above).  Don't restate the
snapshot — score against it.

## Score (0-5) each — one-line justification per row

1. **Correctness** — does the harness do what its spec says?
2. **Robustness** — does it survive plausible failures?
3. **Operator-usability** — can the non-technical operator drive it?
4. **Test discipline** — would tests catch a real regression in your scope?
5. **Risk** — your lens-specific risk in the next 30 days (0=none, 5=ship-blocker)

## Plus

6. **Top blocker** — ONE concrete artifact / change that would lift your
   overall score by ≥1.
7. **Verdict** — SHIP-AS-IS / SHIP-WITH-FIXES / HOLD.  One sentence why.

Total under 350 words.  Start with "## Score" — no preamble.
"""


def _build_prompt(snapshot: str, framing: str) -> str:
    return f"""# Master audit — your lens

{framing}

{snapshot}

{_RUBRIC}
"""


def _dispatch_persona(
    persona: tuple[str, str, str], snapshot: str,
) -> tuple[str, str, int, str]:
    engine_name, name, framing = persona
    model = {
        "mimo": "mimo-v2.5-pro",
        "kimi": "kimi-for-coding",
    }[engine_name]
    try:
        eng = get_engine(engine_name, prefer_dpapi=True)
    except RuntimeError as exc:
        return (name, "", 0, f"engine init failed: {exc}")
    prompt = _build_prompt(snapshot, framing)
    started = time.monotonic()
    try:
        resp = eng.dispatch(prompt, model=model, extra_args={})
    except Exception as exc:
        return (name, "", int((time.monotonic() - started) * 1000),
                f"dispatch raised: {type(exc).__name__}: {exc}")
    latency = int((time.monotonic() - started) * 1000)
    if not resp.success:
        return (name, "", latency, f"dispatch failed: {resp.error}")
    return (name, resp.text or "", latency, "")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[master-audit] gathering state snapshot...", file=sys.stderr,
          flush=True)
    snapshot = _gather_snapshot()
    (OUT_DIR / "_state_snapshot.md").write_text(snapshot, encoding="utf-8")
    print(f"[master-audit] snapshot: {len(snapshot)} chars",
          file=sys.stderr, flush=True)

    all_personas: list[tuple[str, str, str]] = (
        [("mimo", name, framing) for name, framing in MIMO_PERSONAS]
        + [("kimi", name, framing) for name, framing in KIMI_PERSONAS]
    )
    print(f"[master-audit] dispatching {len(all_personas)} reviewers "
          f"(max_workers={MAX_CONCURRENT})...",
          file=sys.stderr, flush=True)
    started = time.monotonic()
    results: list[tuple[str, str, int, str]] = []
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENT) as pool:
        futures = {
            pool.submit(_dispatch_persona, p, snapshot): p[1]
            for p in all_personas
        }
        for f in as_completed(futures):
            results.append(f.result())
            name, text, latency, err = f.result()
            status = "OK " if (text.strip() and not err) else "ERR"
            print(f"  [{status}] {name:<28} {latency}ms  "
                  f"text_len={len(text)}  {err[:60]}",
                  file=sys.stderr, flush=True)
    elapsed_s = time.monotonic() - started

    for name, text, latency, err in results:
        body = text or f"<dispatch failed: {err or 'empty'}>"
        (OUT_DIR / f"{name}.md").write_text(
            f"<!-- name={name} latency_ms={latency} error={err!r} -->\n\n"
            f"{body}\n",
            encoding="utf-8",
        )

    synthesis: list[str] = []
    synthesis.append("# Master audit — 40-reviewer synthesis\n")
    synthesis.append(f"_Dispatched: {len(all_personas)} personas "
                     f"(20 MiMo + 20 Kimi), elapsed {elapsed_s:.1f}s_\n")
    synthesis.append("State snapshot fed to each reviewer is at "
                     "`_state_snapshot.md` in this directory.\n")
    ok_count = sum(1 for _, text, _, err in results if text.strip() and not err)
    synthesis.append(f"_OK responses: {ok_count}/{len(results)}_\n")
    synthesis.append("\n## Per-persona responses\n")
    for name, text, latency, err in sorted(results, key=lambda r: r[0]):
        synthesis.append(f"### {name}\n")
        if err:
            synthesis.append(f"_dispatch error: {err}_\n\n")
            continue
        synthesis.append(f"_latency: {latency}ms_\n\n{text}\n")
    (OUT_DIR / "SYNTHESIS.md").write_text(
        "\n".join(synthesis), encoding="utf-8"
    )
    print(f"\n[master-audit] wrote synthesis: {OUT_DIR / 'SYNTHESIS.md'}",
          file=sys.stderr, flush=True)
    print(f"[master-audit] elapsed {elapsed_s:.0f}s", file=sys.stderr,
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
