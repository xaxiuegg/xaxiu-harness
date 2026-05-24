"""W11+ roadmap panel — 8 agents (mix of MiMo + DeepSeek) estimating
whether the harness can reach ChatGPT-tier friendliness, how many
waves it takes, what must be cut, and whether it's even the right
investment vs. forking an existing tool.

Operator directive 2026-05-25 (post-W10): user wants a rigorous
multi-agent roadmap before any W11 commitment.  Honest answer >
optimistic answer.

Each persona thinks from a distinct lens to surface convergent
themes vs. dissents.  Synthesis at the end maps the rough wave
count + critical decisions.
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

OUT_DIR = REPO_ROOT / "coord" / "reviews" / "roadmap-panel"


# (engine, model, persona_id, persona_lens)
# Mix engines to get diverse-bias views.  DeepSeek primary per
# W10-MIMO-FILTER-INVESTIGATION.
PERSONAS: list[tuple[str, str, str, str]] = [
    ("deepseek", "deepseek-v4-flash", "R1-feasibility-analyst",
     "HONEST FEASIBILITY ANALYST.  Question: is reaching ChatGPT-tier "
     "friendliness POSSIBLE with the current architecture, or does it "
     "require a fundamentally different product?  Look at: Python+CLI "
     "core, Windows-only DPAPI, dispatch-packet abstraction, "
     "multi-engine routing.  Identify what survives a chat-tier rewrite "
     "and what dies."),
    ("deepseek", "deepseek-v4-flash", "R2-wave-estimator",
     "WAVE-COUNT ESTIMATOR.  Given the current rate (1 wave ≈ 8-14 rows "
     "≈ 2-5 commits ≈ 1-2 weeks of operator time per wave), how many "
     "waves does the harness need to reach 7/10 for a ChatGPT-tier user? "
     "Stack-rank the remaining work as a wave plan: W11 through W?.  "
     "Each wave gets a 1-line theme + 3-5 row examples.  Include "
     "explicit confidence interval (e.g. '5-8 waves, p50=6, p90=10')."),
    ("deepseek", "deepseek-v4-flash", "R3-architect",
     "ARCHITECT.  What CODE-LEVEL changes are needed to get from "
     "CLI-tool to chat-tier?  Specifically: how do you move from "
     "click-CLI to Electron desktop app + Python backend?  What "
     "happens to the 30+ CLI verbs (hide? auto-generate GUI from "
     "them? rewrite?)?  Where do you put the chat input box that "
     "operators expect?  Concrete component list."),
    ("mimo", "mimo-v2.5-pro", "R4-ruthless-pm",
     "RUTHLESS PRODUCT MANAGER.  Half the harness's current surface "
     "(coord v2 worktree orchestration, observer cycle, mutation "
     "canary, audit gate, master-audit panel) is engineering-team "
     "infrastructure, NOT operator-facing value.  A chat-tier "
     "operator doesn't care about ANY of it.  Be ruthless: what "
     "should be CUT, what should be HIDDEN behind --advanced, "
     "what stays as operator-facing?  Don't preserve features "
     "just because they exist."),
    ("deepseek", "deepseek-v4-flash", "R5-competitive-bar",
     "COMPETITIVE-LANDSCAPE THINKER.  What does ChatGPT desktop / "
     "Claude Desktop / LM Studio / Ollama-with-Open-WebUI actually "
     "look like to a non-technical user?  Specifically the UX seams: "
     "first-screen layout, settings panel, error handling, model "
     "switching, context management, cost display.  Benchmark each "
     "vs current harness state.  Where is the harness IRRECOVERABLY "
     "behind, and where is it competitive?"),
    ("mimo", "mimo-v2.5-pro", "R6-user-research-proxy",
     "USER-RESEARCH PROXY.  Imagine 5 distinct chat-tier user "
     "journeys: (1) a parent who heard about LLMs and wants to "
     "try Kimi/DeepSeek without paying ChatGPT, (2) a high-school "
     "teacher building lesson plans, (3) a small-business owner "
     "drafting emails, (4) a journalist who needs research summaries, "
     "(5) a hobbyist coder.  For each: what's the journey from "
     "'I downloaded this' to 'I trust it daily'?  Where does each "
     "user GIVE UP and uninstall?  Which user is closest to "
     "harness's natural fit?"),
    ("deepseek", "deepseek-v4-flash", "R7-cost-realist",
     "COST/RESOURCE REALIST.  What does it COST to reach chat-tier? "
     "(a) Engineering hours (Claude/MiMo/DeepSeek API spend for the "
     "build itself + operator hours), (b) infra (Electron build, code-"
     "signing cert ($300-500/yr), bundled Python runtime size, "
     "auto-updater backend), (c) ongoing maintenance (4 engines × "
     "vendor API churn).  Is the operator's current trajectory "
     "(autonomous-loop + free MiMo/Kimi subscriptions + occasional "
     "DeepSeek pay-per-token) AFFORDABLE to reach the chat-tier "
     "goal?  Be specific with dollar estimates."),
    ("mimo", "mimo-v2.5-pro", "R8-kill-project-skeptic",
     "PROJECT-KILL SKEPTIC.  Be the harshest possible voice.  "
     "Would it be FASTER + CHEAPER to: (a) fork OpenWebUI + write "
     "a 4-engine routing plugin, (b) fork LangFlow + add the "
     "audit/canary pieces, (c) build a Claude Desktop fork with "
     "engine switching, OR (d) just have the operator pay $20/month "
     "for ChatGPT Plus and skip the whole harness?  Compare "
     "end-to-end TCO + time-to-chat-tier for each alternative vs. "
     "the W11-W?? path.  Recommend ABANDON if that's the honest "
     "answer; recommend CONTINUE only if there's a unique value "
     "that survives the comparison."),
]


def _gather_snapshot() -> str:
    snapshot: list[str] = []
    # Brief current-state summary
    snapshot.append("""\
## Current state (post-W10, commit 0c99386)

- 1810 tests pass + 6 skip + 3 deselected slow
- 10 waves shipped (W1-W10) over ~3 weeks of operator-driven work
- Test count growth: started ~1000 → 1810 over 10 waves
- Wave rate: ~8-14 rows per wave, ~2-5 commits per wave, ~1-2 weeks/wave

## Honest rating today
- ChatGPT-tier user (treats LLMs like ChatGPT/Claude Desktop): **2/10**
- CLI-literate non-Python user: **6/10**

## Operator profile
The operator is NON-TECHNICAL.  Can:
  - Edit YAML, run CLI commands, manage Windows Task Scheduler
  - Read STATUS.csv

Cannot:
  - Author Python
  - Debug Python tracebacks
  - Read engine logs and root-cause issues

User stated framing: 'just happen to thought of it as Claude Code
or ChatGPT the like' — i.e. type, get answer.

## What's been built (just the headline features)

ENGINE/DISPATCH LAYER:
- Multi-engine dispatch with auto-fallback (Kimi, DeepSeek, MiMo,
  Anthropic, Gemini, Mock)
- Per-key circuit breakers + auto-quarantine on flap
- 4-key proxy pool for Kimi (24 concurrent slots)
- Cost ledger per dispatch
- Adapter-driven routing (YAML config per project)

OPERATOR UX LAYER (W8-W10):
- harness daily (W10): one-verb morning routine
- harness env-wizard (W10): guided DPAPI key setup
- harness preflight (W6+): readiness gate with PASS / PASS-WITH-
  WARNINGS / FAIL verdict (W10)
- harness today (W8): plain-language daily pulse
- harness morning-brief (W4): overnight summary
- harness profile set/show (W10): persisted operator profile
- harness status list --recent N (W10): recent-rows view
- harness engines-heal (W8): one-command engine recovery
- preflight --fix (W8): auto-remediation (no longer silently stashes
  per W10)
- Operator runbook + verdict semantics table + DPAPI section

DETECTION/SAFETY LAYER (W6-W9):
- MiMo audit gate (--avg-of-N for non-determinism)
- Mutation canary (rotating 4-module warm tier)
- Mutation manifest (3-tier coverage tracking)
- Silent-except lint baseline (locked at 0 broad swallows)
- Atomic state writes + advisory file locks
- Redaction patterns consolidated + integrity tests
- Proxy failure matrix (12-row spec + tests)
- CRLF hook fix
- Stop-hook noise reduction

COORD V2 (multi-agent worktree):
- Planner → Worker → Coordinator → Integrator pipeline
- Worktree-isolated parallel workers
- Checkpoint + progress-stream + heartbeat
- 13 coord subcommands (plan/run/work/retry/integrate/replan/etc)

WHAT'S STILL MISSING (W11+ candidates queued):
- Standalone installer (.exe / .msi) — currently git clone + pip install
- harness start wizard (single-command first-run path)
- Dashboard as default surface (currently opt-in localhost FastAPI)
- Morning email brief
- Cost visibility widget
- Hide advanced verbs (--advanced namespace)
- L5 escalation output contract
- Observer watchdog self-recovery
- Mutation pattern expansion (async/await flips for observer/cycle)
""")

    # W10 readiness panel synthesis (compressed)
    try:
        snapshot.append("\n## W10 readiness panel verdict (just the headline)\n\n"
                        "0/10 YES, 8/10 WITH GUARDRAILS, 2/10 NO.  Every NO-vote "
                        "reviewer cited the first-run preflight failure (git_clean "
                        "blocker) as unresolvable for a non-technical user.\n")
    except OSError:
        pass

    # W10 master audit
    snapshot.append("\n## W10 master-audit panel (40 reviewers)\n\n"
                    "0 SHIP-AS-IS, 5 HOLD, 35 SHIP-WITH-FIXES.  No regressions "
                    "post-W9 (was 0/4/35).  Convergent themes: structural "
                    "first-run gap, observer fragility, latency observability, "
                    "cost surfacing.\n")

    return "\n".join(snapshot)


_INSTRUCTIONS = """\
You are one of 8 roadmap-planning panel reviewers.  Use the state
snapshot + your assigned lens to answer:

## Output structure (mandatory; keep under 700 words)

1. **Headline verdict** — one sentence: WILL the harness eventually
   reach 7/10 for a ChatGPT-tier user?  YES / YES-IF / NO / NEEDS-PIVOT.

2. **Wave-count estimate** — your best guess at how many waves
   (W11 through W??) it takes.  Include a confidence range
   (e.g. "5 waves p50, 3-9 p90").

3. **The 3 most load-bearing decisions** the operator must make
   in W11 to keep the trajectory on track.  Be specific (not "improve
   UX" — what specifically?).

4. **The one thing you would CUT or HIDE** that the harness currently
   ships but a chat-tier user will never use.

5. **The one risk** most likely to derail the trajectory (per your
   lens).  Be specific.

6. **A single-sentence recommendation** — go / pivot / abandon.

No preamble.  No restating the snapshot.  Your lens:
"""


def _run_one(engine_name: str, model: str, pid: str, lens: str,
             snapshot: str) -> tuple[str, str, str]:
    started = time.monotonic()
    try:
        eng = get_engine(engine_name, prefer_dpapi=False)
    except RuntimeError as exc:
        return (pid, f"engine init failed: {exc}", "FAIL")
    prompt = (
        snapshot
        + "\n\n---\n\n"
        + _INSTRUCTIONS
        + lens
    )
    resp = eng.dispatch(prompt, model, {"max_tokens": 4500})
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if not resp.success or not (resp.text or "").strip():
        return (pid, f"engine failed: {resp.error}", "FAIL")
    return (pid, resp.text.strip(), f"OK ({elapsed_ms}ms)")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[roadmap] gathering state snapshot...", file=sys.stderr)
    snapshot = _gather_snapshot()
    (OUT_DIR / "_state_snapshot.md").write_text(snapshot, encoding="utf-8")
    print(f"[roadmap] snapshot: {len(snapshot)} chars", file=sys.stderr)

    print(f"[roadmap] dispatching {len(PERSONAS)} reviewers "
          f"(max_workers=8)...", file=sys.stderr)
    started = time.monotonic()
    results: dict[str, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = {
            pool.submit(_run_one, eng, model, pid, lens, snapshot): pid
            for eng, model, pid, lens in PERSONAS
        }
        for f in as_completed(futures):
            pid, text, status = f.result()
            results[pid] = (text, status)
            text_len = len(text)
            print(f"  [{status}] {pid:<28} text_len={text_len}",
                  file=sys.stderr)
    elapsed_s = time.monotonic() - started
    print(f"\n[roadmap] elapsed {elapsed_s:.0f}s", file=sys.stderr)

    for pid, (text, status) in results.items():
        (OUT_DIR / f"{pid}.md").write_text(
            f"<!-- persona={pid} status={status} -->\n\n# {pid}\n\n{text}\n",
            encoding="utf-8",
        )

    synth_lines = [
        "# Chat-tier roadmap panel — synthesis",
        "",
        f"_Dispatched: {len(PERSONAS)} reviewers (DeepSeek primary + MiMo "
        f"on creative lenses), elapsed {elapsed_s:.0f}s_",
        "",
        "Each persona thinks from a distinct lens to surface convergent "
        "themes vs. dissents.  See `_state_snapshot.md` for the input.",
        "",
    ]
    for eng, model, pid, lens in PERSONAS:
        text, status = results.get(pid, ("(no response)", "MISSING"))
        synth_lines.append(f"## {pid}  ({eng}/{model})\n\n{text}\n\n---\n")
    (OUT_DIR / "SYNTHESIS.md").write_text(
        "\n".join(synth_lines), encoding="utf-8",
    )
    print(f"[roadmap] wrote synthesis: {OUT_DIR / 'SYNTHESIS.md'}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
