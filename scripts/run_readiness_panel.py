"""Harness readiness assessment — 5 MiMo + 5 Kimi reviewers.

Operator directive 2026-05-23: assess whether the harness is ready
for the non-technical operator to use day-to-day.

Per memory [[user_non_technical_role]] the operator can:
  - Edit YAML
  - Run commands
  - Manage Windows Task Scheduler
  - Read STATUS.csv

BUT the operator CANNOT:
  - Author Python from scratch
  - Debug Python tracebacks
  - Read engine logs and root-cause issues

So "ready" = the operator should be able to install, run, observe, and
recover from typical workflows WITHOUT needing Python knowledge.

Each persona reviews the harness from a different angle.  Output is
a single readiness verdict + rubric scores from each reviewer; the
synthesis tells the operator where the bar is met and where it isn't.
"""

from __future__ import annotations

import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness.engines.concrete import get_engine  # noqa: E402

OUT_DIR = REPO_ROOT / "coord" / "reviews" / "readiness-panel"


# -- gather objective evidence ---------------------------------------------


def _gather_state_snapshot() -> str:
    """Snapshot the harness's current state.  Each reviewer reads this
    before scoring."""
    snapshot: list[str] = []
    # 1. CLI verb list — what can the operator actually do?
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "harness", "--help"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=20,
            env={**__import__("os").environ, "PYTHONPATH": "src"},
        )
        snapshot.append("## CLI verbs (`harness --help`)\n\n```\n"
                        + (proc.stdout[:3000] or proc.stderr[:1500])
                        + "\n```\n")
    except Exception as exc:
        snapshot.append(f"## CLI verbs — FAILED: {exc}\n")
    # 2. preflight — the W6-B2 readiness gate (without engine probes
    # so we don't burn API spend on the readiness assessment itself)
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "harness",
             "preflight", "--skip-engines"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
            env={**__import__("os").environ, "PYTHONPATH": "src"},
        )
        snapshot.append("## `harness preflight --skip-engines` output\n\n"
                        f"```\n{proc.stdout[:2000]}\n```\n"
                        f"Exit code: {proc.returncode}\n")
    except Exception as exc:
        snapshot.append(f"## preflight — FAILED: {exc}\n")
    # 3. doctor — long-running diagnostic
    try:
        proc = subprocess.run(
            [sys.executable, "-X", "utf8", "-m", "harness", "doctor"],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=30,
            env={**__import__("os").environ, "PYTHONPATH": "src"},
        )
        snapshot.append("## `harness doctor` output\n\n"
                        f"```\n{proc.stdout[:2000]}\n```\n")
    except Exception as exc:
        snapshot.append(f"## doctor — FAILED: {exc}\n")
    # 4. STATUS.csv row count + sample
    try:
        status_path = REPO_ROOT / "coord" / "STATUS.csv"
        lines = status_path.read_text(encoding="utf-8").splitlines()
        snapshot.append(f"## STATUS.csv ({len(lines)} rows)\n\n"
                        "First 3 rows + last 5 rows:\n\n```csv\n"
                        + "\n".join(lines[:3] + ["..."] + lines[-5:])
                        + "\n```\n")
    except Exception as exc:
        snapshot.append(f"## STATUS.csv — FAILED: {exc}\n")
    # 5. Test count
    snapshot.append("## Test count\n\n1544 passed + 6 skipped\n")
    # 6. Memory of the load-bearing operator-profile constraint
    snapshot.append("""\
## Operator profile (memory: user_non_technical_role)

The operator is NON-TECHNICAL.  Can:
  - Edit YAML, run CLI commands, manage Windows Task Scheduler
  - Read STATUS.csv

Cannot:
  - Author Python
  - Debug tracebacks
  - Read engine logs and root-cause issues

So "ready" = the operator can install → run → observe → recover
from typical workflows WITHOUT needing Python knowledge.
""")
    return "\n".join(snapshot)


PERSONAS: list[tuple[str, str, str, str]] = [
    ("mimo", "mimo-v2.5-pro", "M1-install",
     "INSTALL REVIEWER.  Can a fresh-clone operator stand up the harness "
     "in <30 minutes without Python knowledge?  Look at: install steps, "
     "required env vars, DPAPI key seeding, first-run experience.  Find "
     "the steps where the operator would get stuck without help."),
    ("mimo", "mimo-v2.5-pro", "M2-daily-workflow",
     "DAILY WORKFLOW REVIEWER.  Imagine the operator at the keyboard "
     "every morning.  What's the typical command sequence?  Where's "
     "the cognitive load?  Are CLI verbs discoverable + named "
     "consistently?  Does `harness morning-brief` give the operator "
     "what they need?"),
    ("mimo", "mimo-v2.5-pro", "M3-error-recovery",
     "ERROR RECOVERY REVIEWER.  When something breaks, can the operator "
     "fix it without filing a Python bug?  Look at error messages, "
     "L5 escalation contract, doctor + preflight outputs.  Find a "
     "specific failure that would block the operator dead."),
    ("mimo", "mimo-v2.5-pro", "M4-observability",
     "OBSERVABILITY REVIEWER.  Can the operator see what the harness is "
     "doing?  Dashboard at 7878, STATUS.csv updates, morning-brief, "
     "observer flags.  Where are the surfaces good?  Where does the "
     "operator have to dig into runs/ + worktrees themselves?"),
    ("mimo", "mimo-v2.5-pro", "M5-trust",
     "TRUST REVIEWER.  Can the operator TRUST the autonomous loop to "
     "run unattended?  Look at: kill-conditions, full-dev-authority "
     "safeguards, audit-gate behaviour, the L5 escalation contract.  "
     "Where is trust earned?  Where is trust unearned?"),
    ("kimi", "kimi-for-coding", "K1-onboarding-friction",
     "ONBOARDING-FRICTION REVIEWER.  A new operator clones the repo.  "
     "Where does CLAUDE.md / README.md / SESSION_BOOTSTRAP.md help "
     "vs. confuse?  What sequence of commands lands them on `harness "
     "morning-brief` for the first time?  Count operator decisions "
     "in that path."),
    ("kimi", "kimi-for-coding", "K2-documentation",
     "DOCUMENTATION REVIEWER.  Does the harness explain itself to a "
     "non-technical operator?  Skim README, spec/operator-modes.md, "
     "spec/observer.md, spec/multi-agent-harness-architecture.md.  "
     "Rate clarity for the non-Python-knower audience."),
    ("kimi", "kimi-for-coding", "K3-failure-modes",
     "FAILURE-MODES REVIEWER.  List the top 3-5 failure modes a real-"
     "world operator will hit in the first month.  For each: is the "
     "error message clear?  Is the recovery action obvious?  Or "
     "would the operator need to ping engineering?"),
    ("kimi", "kimi-for-coding", "K4-cli-ergonomics",
     "CLI ERGONOMICS REVIEWER.  60+ subcommands across 22 verbs.  "
     "Is `harness <verb> --help` enough?  Are verb names consistent "
     "(loop init/tick/start/stop vs observer ...)?  Is there a verb "
     "the operator will need but doesn't exist?"),
    ("kimi", "kimi-for-coding", "K5-honest-readiness",
     "HONEST READINESS REVIEWER.  Cut through the impressive numbers "
     "(1544 tests, 7 waves shipped, 8 W7 rows).  Would YOU hand this "
     "harness to a non-technical friend and tell them to run it for "
     "30 days without your help?  If yes, why.  If no, what's "
     "concretely missing?"),
]


_INSTRUCTIONS = """\
You are one of 10 readiness reviewers.  Use the state snapshot + your
assigned lens to answer the rubric below.  Don't restate the snapshot;
score against it.

## Rubric — score each 0-5 + one-line justification

1. **Install** — fresh clone → harness preflight green in ≤30 min, no
   Python knowledge required
2. **Daily run** — morning command sequence is obvious + low-toil
3. **Observe** — operator can see what's happening without
   reading runs/ files by hand
4. **Recover** — typical failures have clear remediation paths
   visible from the CLI / STATUS.csv / dashboard

## Plus answer:

5. **Hand to a non-technical operator today?** YES / WITH GUARDRAILS / NO,
   and one-paragraph reasoning.
6. **Top 3 blockers** — concrete artifacts/commands missing that, if
   shipped, would move your overall score by ≥1.

Total response under 400 words.  Start with "## Rubric" — no preamble.
"""


def _build_prompt(snapshot: str, framing: str) -> str:
    return f"""# Harness readiness assessment — your lens

{framing}

{snapshot}

{_INSTRUCTIONS}
"""


def _dispatch_persona(
    persona: tuple[str, str, str, str], snapshot: str,
) -> tuple[str, str, int, str]:
    engine_name, model, name, framing = persona
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
    print("[readiness] gathering state snapshot...", file=sys.stderr,
          flush=True)
    snapshot = _gather_state_snapshot()
    (OUT_DIR / "_state_snapshot.md").write_text(snapshot, encoding="utf-8")
    print(f"[readiness] snapshot: {len(snapshot)} chars",
          file=sys.stderr, flush=True)

    print(f"[readiness] dispatching {len(PERSONAS)} reviewers...",
          file=sys.stderr, flush=True)
    started = time.monotonic()
    results: list[tuple[str, str, int, str]] = []
    with ThreadPoolExecutor(max_workers=len(PERSONAS)) as pool:
        futures = {
            pool.submit(_dispatch_persona, p, snapshot): p[2]
            for p in PERSONAS
        }
        for f in as_completed(futures):
            results.append(f.result())
            name, text, latency, err = f.result()
            status = "OK " if (text.strip() and not err) else "ERR"
            print(f"  [{status}] {name:<24} {latency}ms  "
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
    synthesis = ["# Harness readiness — 10-reviewer synthesis\n"]
    synthesis.append(f"_Dispatched: {len(PERSONAS)} personas, "
                     f"elapsed {elapsed_s:.1f}s_\n")
    synthesis.append("State snapshot fed to each reviewer is at "
                     "`_state_snapshot.md` in this directory.\n")
    synthesis.append("## Per-persona responses\n")
    for name, text, latency, err in sorted(results, key=lambda r: r[0]):
        synthesis.append(f"### {name}\n")
        if err:
            synthesis.append(f"_dispatch error: {err}_\n")
            continue
        synthesis.append(f"{text}\n")
    (OUT_DIR / "SYNTHESIS.md").write_text(
        "\n".join(synthesis), encoding="utf-8"
    )
    print(f"\n[readiness] wrote synthesis: {OUT_DIR / 'SYNTHESIS.md'}",
          file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
