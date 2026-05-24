"""10-reviewer interaction-arc analysis panel.

Operator-requested 2026-05-23: 5 MiMo + 5 Kimi reviewers analyse the
full Claude-operator interaction arc (W6 STOPs + W6-PANEL pivot + W7
clean execution + post-W7 audit-every-Wn directive) and recommend
where/how to proceed next.

Each persona gets a different lens so the panel surfaces diversity,
not 10 copies of the same read.

Outputs:
  coord/reviews/interaction-panel/<persona>.md  (10 files)
  coord/reviews/interaction-panel/SYNTHESIS.md  (aggregate)
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness.engines.concrete import get_engine  # noqa: E402

OUT_DIR = REPO_ROOT / "coord" / "reviews" / "interaction-panel"

# (engine, model, name, framing) — same shape as run_closeout_panel.py
PERSONAS: list[tuple[str, str, str, str]] = [
    # 5 MiMo personas — long-horizon angles
    ("mimo", "mimo-v2.5-pro", "M1-strategy",
     "You are a STRATEGIST.  Lens: long-term direction.  The harness "
     "has shipped W6 (validation + foundation, with 2 STOPs) and W7 "
     "(test-quality recovery, all rows shipped clean).  The 10-reviewer "
     "panel mid-cycle reshaped the next move.  Where should the "
     "harness aim its next 1-2 waves?  Consider: is the foundation "
     "now strong enough to add features?  Or are we still in clean-up?"),
    ("mimo", "mimo-v2.5-pro", "M2-process",
     "You are a PROCESS ENGINEER.  Lens: the operator-Claude "
     "interaction quality.  Look at the patterns: operator nudges "
     "via stop-hook → Claude commits, operator says 'proceed per rec' "
     "→ Claude executes panel-converged path, operator says 'keep "
     "working autonomously' → Claude ships 8 W7 rows.  Where is the "
     "loop smooth?  Where does the operator have to intervene?  "
     "What would tighten the loop?"),
    ("mimo", "mimo-v2.5-pro", "M3-risk",
     "You are a RISK ANALYST.  Lens: what could go wrong NEXT.  Wave 7 "
     "added a lot of new code (StreamingTransport ABC, planner spec-"
     "drift enforcement, Kimi reasoning_only flag).  What new failure "
     "modes have we introduced?  What dependencies are we now sitting "
     "on?  Recommend 2-3 hardening actions BEFORE adding more features."),
    ("mimo", "mimo-v2.5-pro", "M4-velocity",
     "You are a DELIVERY MANAGER.  Lens: pace vs quality.  W6 = 5 "
     "hours, 11 commits, 2 STOPs.  W7 = 6 hours, 11 commits, 0 STOPs.  "
     "Is this acceleration?  Plateau?  What's the sustainable rate, "
     "and what's currently constraining it (engine latency? operator "
     "review bandwidth? test verification time)?"),
    ("mimo", "mimo-v2.5-pro", "M5-tech-debt",
     "You are an ARCHITECT focused on DEBT.  Lens: what tech debt is "
     "accumulating that future waves will pay for?  The mutation "
     "sweep surfaced test-quality debt; we paid some of it down in "
     "W7.  What's the NEXT category of debt — config drift, engine "
     "fan-out, observer coverage gaps, dashboard staleness?  Rank by "
     "compounding cost."),
    # 5 Kimi personas — pragmatic angles
    ("kimi", "kimi-for-coding", "K1-operator-ux",
     "You are an OPERATOR UX RESEARCHER.  Lens: what's painful for the "
     "non-technical operator who runs this harness?  Look at the stop-"
     "hook firing patterns, the audit-script STOPs, the panel-review "
     "pattern.  Where does the operator have to do more work than "
     "they should?  Name 2-3 specific friction points + concrete fixes."),
    ("kimi", "kimi-for-coding", "K2-test-quality-meta",
     "You are a TEST-QUALITY META REVIEWER.  Lens: the W7 mutation "
     "tests are behavioral, not boundary.  Is that enough?  What about "
     "the modules NOT in the W6-A3 sweep (proxy/, observer/, "
     "loops/, dashboard/) — do they have the same 0.0-kill-rate "
     "problem hiding?  Recommend a process to find out without doing "
     "another full sweep."),
    ("kimi", "kimi-for-coding", "K3-architecture",
     "You are a SOFTWARE ARCHITECT.  Lens: structural decisions ahead.  "
     "The StreamingTransport ABC just shipped (W7-B1-RETROFIT).  The "
     "planner now enforces single_worker.  What's the next "
     "architectural decision the harness needs to make?  Consider "
     "engine plurality (>5 backends now), state-layer pressure "
     "(SQLite + JSONL + JSON files), the dispatch+integrator+observer "
     "trinity."),
    ("kimi", "kimi-for-coding", "K4-cost",
     "You are a COST ENGINEER.  Lens: engine spend efficiency.  The "
     "budget summary shows DeepSeek at $0.35, all others $0 (tp-/sk- "
     "subscriptions).  But MiMo is the audit primary + the panel "
     "primary + the planner primary — what happens if MiMo's "
     "subscription quota tightens?  Recommend a hedge plan."),
    ("kimi", "kimi-for-coding", "K5-devils-advocate",
     "You are a DEVIL'S ADVOCATE.  Lens: what if our recent direction "
     "is wrong?  The audit-every-Wn directive just landed — but the "
     "audit script itself has STOPped on partial diffs (W6-A3, W6-C2 "
     "first runs).  Is the audit gate too noisy?  Should we replace "
     "it with something else (e.g. a different reviewer model, a "
     "machine-checkable acceptance grammar, integration smoke runs)?  "
     "Argue against the current direction; pick at least one concrete "
     "alternative."),
]


_INTERACTION_CONTEXT = """\
# Interaction-arc summary (operator-claude session 2026-05-23)

## Phase A — Wave 6 (validation + foundation)
The operator pasted the W6 session-handoff doc.  Claude resumed the
W6-A1 env-doctor 3-engine end-to-end run.  Hit silent_no_op repeatedly
because the planner was emitting read_set=[] for write_set files; the
W6-A1-3 fix pre-loaded existing files into the prompt.  Then W6-A1-4
fixed the trusted_source flag (Kimi/mock direct-HTTP path was tripping
the injection scanner on legit harness code).  3 green e2e runs
landed; W6-A1 shipped.

W6-A2 token-tracking live tests landed.  W6-A3 mutation sweep ran:
2/5 modules PASS, 3/5 FAIL with 0.0-1.0 kill rate.  Audit STOPped at
0.60.

W6-B1 EngineTransport dispatch stalled mid-retrofit — transport.py
created in a worktree branch but not merged.  Shipped as 'partial'.
W6-B2 preflight verb + W6-B3 autonomous gate landed clean.  W6-C1 hook
path fix landed clean.  W6-C2 dead-engine alarm landed; audit STOPped
at 0.62 after 3 retries (auditor wanted behavioral integration, got
unit + source-grep sentinel).

W6-CLOSEOUT documented both STOPs honestly with operator decision
points — no spec-shaping to override the gate.

## Phase B — 10-reviewer panel
Operator asked for 5 MiMo + 5 Kimi reviewers to review the closeout.
First Kimi batch (4 of 5 reviewers) returned empty content because
the panel script passed max_tokens=4000 (or 2500 on retry), and
Kimi's reasoning_content ate the budget.  Retry at engine default
(32K) recovered all 4.  Synthesis showed: C2 accept (8/10), A3 split
(4 accept / 6 require-more-work), strongest panel signal was a
'conditional close + W7 backlog lock' option NOT in the closeout.

Operator chose the composite move: accept C2, conditionally accept A3
with W7-MUTATION-WORKER as backlog-lock gate, open W7 with worker.py
budget hook warm-up.

## Phase C — Wave 7 (clean execution)
Per the panel rec, W7 executed in sequence:
  W7-WORKER-BUDGET-HOOK (warm-up; in/out token split)
  W7-MUTATION-WORKER    (lock-gate; kill rate 0.0 → 4.00)
  W7-KIMI-REASONING-EMPTY  (bonus from panel retry footgun)
  W7-KIMI-MAX-TOKENS-FLOOR (companion)
  W7-MUTATION-ORCH         (kill rate 0.0 → 3.00)
  W7-MUTATION-CONCRETE     (kill rate 1.0 → 3.33)
  W7-B1-RETROFIT           (StreamingTransport ABC; DeepSeek + Kimi
                            refactored; MiMo OUT — batch HTTP not SSE)
  W7-SPEC-DRIFT            (planner enforces single_worker directive)
  W7-CLOSEOUT              (8/8 + 2 bonus shipped; 0 audit STOPs)

Stop-hook noise was constant: ~6 hook fires across the session, each
flagging stale STATUS.csv against newly-modified files (mutation sweep
constantly bumps mtime).  Each fire took a turn to acknowledge +
touch STATUS.csv.

## Phase D — post-W7 directive
Operator: "Have mimo audited each Wn action you take.  In addition,
how should we proceed next.  Ask an engine to dispatch 5 agents each
(2 engines) come and analyze all claude-users interaction so far to
see where and how should we proceed."

This panel is the response to that directive.

## Numbers
  W6: 11 commits, 2 audit STOPs + 1 partial, 1465 pytest pass at close
  W7: 11 commits, 0 audit STOPs, 1544 pytest pass at close
  Test growth: +79
  Mutation kill rate: 5 of 5 hot modules now ≥3 (was 2 of 5)

## Operator standing directives (load-bearing)
- Full dev authority within xaxiu-harness; no per-action confirmation
- Escalate only L5 errors
- Don't ship features faster than you validate them
- Prefer larger working surface; don't trim for safety
- Run until wave_plan empty, not until task done
- Every Wn action gets a MiMo audit (this directive, 2026-05-23)

## Reviewer task

You are one of 10 independent reviewers.  Answer these three sections,
keep total response under 400 words, start with section heading "1.":

1. What's the SINGLE next-best move the harness should make?  Name
   the wave / row / file specifically; explain the reasoning briefly.

2. What pattern in the operator-Claude interaction is WORKING and
   should be preserved?  And what pattern is NOT working and should
   be replaced?

3. Where should the next 2-3 waves aim?  Don't enumerate W8-* rows;
   describe the THEME (e.g. 'consolidate the engine layer', 'turn
   observer into a first-class operator surface', 'add a real CI').
"""


def _build_prompt(framing: str) -> str:
    return f"""# Interaction-arc analysis panel — your lens

{framing}

{_INTERACTION_CONTEXT}
"""


def _dispatch_persona(
    persona: tuple[str, str, str, str],
) -> tuple[str, str, int, str]:
    engine_name, model, name, framing = persona
    try:
        eng = get_engine(engine_name, prefer_dpapi=True)
    except RuntimeError as exc:
        return (name, "", 0, f"engine init failed: {exc}")
    prompt = _build_prompt(framing)
    started = time.monotonic()
    try:
        # Note: NO max_tokens override — leave Kimi at the default 200K
        # / mimo at default.  W7-KIMI-MAX-TOKENS-FLOOR clamps Kimi
        # callers anyway, but the panel script learns from W6-PANEL.
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
    print(f"[panel] dispatching {len(PERSONAS)} reviewers in parallel...",
          file=sys.stderr, flush=True)
    started = time.monotonic()
    results: list[tuple[str, str, int, str]] = []
    with ThreadPoolExecutor(max_workers=len(PERSONAS)) as pool:
        futures = {pool.submit(_dispatch_persona, p): p[2] for p in PERSONAS}
        for f in as_completed(futures):
            results.append(f.result())
            name, text, latency, err = f.result()
            status = "OK" if (text.strip() and not err) else "ERR"
            print(f"  [{status:3}] {name:<24} {latency}ms  text_len={len(text)}  {err[:60]}",
                  file=sys.stderr, flush=True)
    elapsed_s = time.monotonic() - started

    for name, text, latency, err in results:
        body = text or f"<dispatch failed: {err or 'empty response'}>"
        (OUT_DIR / f"{name}.md").write_text(
            f"<!-- name={name} latency_ms={latency} error={err!r} -->\n\n"
            f"{body}\n",
            encoding="utf-8",
        )

    synthesis = ["# Interaction-arc panel — 10-reviewer synthesis\n"]
    synthesis.append(f"_Dispatched: {len(PERSONAS)} personas, "
                     f"elapsed {elapsed_s:.1f}s_\n")
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
    print(f"\n[panel] wrote synthesis: {OUT_DIR / 'SYNTHESIS.md'}",
          file=sys.stderr, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
