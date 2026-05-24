"""W11 execution-planning panel — 5 agents align on sequencing,
dependencies, W11-A scope concrete file list, risk, and TDD contract.

Output goal: a SHIPPABLE Wave 11 plan that the operator can read in
5 minutes and authorize.  Not abstract — concrete enough that
'start Wave 11-A' has a defined first commit.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "src"))

from harness.engines.concrete import get_engine  # noqa: E402

OUT_DIR = REPO_ROOT / "coord" / "reviews" / "w11-planning-panel"


PERSONAS: list[tuple[str, str, str, str]] = [
    ("deepseek", "deepseek-v4-flash", "P1-sequencer",
     "WAVE SEQUENCER.  Given Wave 11 has 16 active todo rows across "
     "3 sub-waves (11-A entry, 11-B SDK + context, 11-C telemetry + "
     "cross-platform) plus 6 engineering-hygiene rows folded in, "
     "design the ship order.  Answer: (a) which row ships FIRST and "
     "why (must unblock everything else), (b) which row ships LAST "
     "and why (depends on everything), (c) the critical-path chain, "
     "(d) which rows can ship in parallel without conflict, "
     "(e) explicit go/no-go gates between sub-waves.  Be concrete: "
     "use the actual row IDs."),
    ("deepseek", "deepseek-v4-flash", "P2-dependency-mapper",
     "DEPENDENCY MAPPER.  Build the dependency graph for the 16 "
     "W11 todo rows.  For each row, list (a) what it DEPENDS on "
     "(other rows or existing capabilities), (b) what DEPENDS on it "
     "(downstream rows that need it shipped first), (c) shared "
     "write-set with other rows (so we know what can't parallelize).  "
     "Surface any circular dependencies or hidden orderings.  Output "
     "as a markdown table: row | depends-on | enables | "
     "shared-write-set."),
    ("mimo", "mimo-v2.5-pro", "P3-w11a-scope-concrete",
     "W11-A SCOPE DESIGNER.  W11-AGENT-INIT-VERB is the first row "
     "to ship.  Give a CONCRETE deliverable: (a) the exact subcommand "
     "signature with all flags, (b) the literal file tree it writes "
     "to a fresh target directory, (c) the contents of each file "
     "(actual templates, not 'sample placeholder'), (d) what happens "
     "on re-run (idempotency contract), (e) what error states are "
     "possible and how each is handled, (f) the next command the verb "
     "prints to teach the agent how to dispatch.  Treat this as a "
     "spec the implementer could code from with zero ambiguity."),
    ("deepseek", "deepseek-v4-flash", "P4-risk-analyst",
     "RISK ANALYST.  For the 3-sub-wave Wave 11 plan, list the top "
     "5 risks ranked by (probability × impact).  For each: (a) one "
     "sentence on what goes wrong, (b) the leading indicator that "
     "would flag it early, (c) the mitigation or rollback.  "
     "Specifically consider: API cost creep on subscription engines, "
     "context-preservation refactor breaking existing dispatchers, "
     "cross-platform observer regressions, agent-target-project "
     "conflicts with operator's own (STATUS.csv collision), the "
     "competing-tools window (Cursor/Claude Code adding native "
     "routing while we ship)."),
    ("mimo", "mimo-v2.5-pro", "P5-tdd-designer",
     "TDD CONTRACT DESIGNER.  For each of the 10 NEW agent-first "
     "rows, give the test contract: (a) the smallest meaningful "
     "test fixture, (b) the 3-5 must-have test cases that prove the "
     "row 'works', (c) any integration / cross-module tests needed, "
     "(d) acceptance criteria for the audit gate.  Goal: the "
     "implementer writes tests FIRST + the audit gate has clear "
     "PASS criteria.  Don't write the actual code — write the tests "
     "that prove the row landed correctly."),
]


def _gather_snapshot() -> str:
    return """\
## Current state (post-W10 + agent-first pivot, commit 0c99386 + b4a4d9f)

- 16 active W11 todo rows + 4 deferred + 1 shipped (W11-AGENT-FIRST-PIVOT)
- 1810 tests pass + 6 skip + 3 deselected slow
- Test count baseline for W11

## The 10 NEW agent-first rows (queued from agent-as-user + context-preservation panels)

### Wave 11-A (entry)
- W11-AGENT-INIT-VERB: harness agent init --target <path>
  one-shot bootstrap (.env + adapter + scoped STATUS.csv + CLAUDE.md
  snippet + .harness/ state dir)
- W11-DPAPI-CROSS-PLATFORM: .env-first secrets; --encrypt-with-dpapi
  opt-in on Win; resolve_keys reads .env then DPAPI fallback
- W11-CLAUDE-MD-TEMPLATE: per-project-type templates ≤800 chars

### Wave 11-B (Python SDK + context preservation)
- W11-PYTHON-SDK-API: from harness import dispatch, retrieve,
  budget_status + type stubs
- W11-CONTEXT-FRUGAL-RETURN: DispatchResult default = summary +
  metadata + content_ref; .full() lazy fetch; tail-preservation;
  top-level error_excerpt
- W11-DISPATCH-CACHE: content-hash + adapter-hash keyed cache
  under .harness/dispatched/
- W11-RETRIEVE-API: harness.retrieve(id, scope='full' /
  'summary' / 'chunks')

### Wave 11-C (telemetry + cross-platform)
- W11-AGENT-TELEMETRY: budget_status() returns offload_ratio,
  remaining_budget, dispatches_fired, engines_used dict
- W11-CROSS-PLATFORM-OBSERVER: cron alternative to Windows Task
  Scheduler for observer cycle
- W11-ADAPTER-VALIDATE-JSON: harness adapter validate --json
  emits {field, line, severity, message, suggested_fix}

## 6 engineering-hygiene rows folded in
- W11-HIDE-ADVANCED-VERBS (helps both tracks)
- W11-L5-OUTPUT-CONTRACT (helps both tracks)
- W11-OBSERVER-WATCHDOG-RECOVERY (pairs with cross-platform observer)
- W11-PER-CHECK-LATENCY-OBSERVABILITY (engineering hygiene)
- W11-MUTATION-PATTERN-EXPANSION (engineering hygiene)
- W11-AUDIT-ALL-W10-ROWS (engineering hygiene; can run any time)

## Existing relevant capabilities
- harness.engines.dispatcher.dispatch_packet (current public dispatch)
- harness.state.files.atomic_write_json (canonical state writer)
- harness.state.locks.advisory_lock (file-lock helper)
- harness.secrets.dpapi.encrypt_secret / decrypt_secret / has_secret
- harness.adapters.loader.load_project_adapter (current adapter API)
- harness.adapters.scaffold.scaffold_adapter (current adapter generator)
- harness.budget.record_dispatch (cost ledger)
- scripts/audit_task_with_mimo.py (audit gate, DeepSeek primary post-W10)
- scripts/run_mutation_canary.py (deterministic regression signal)

## Operator profile
The operator runs Claude Code (this agent) as their primary
interface.  Each session is in the 1-2M operator-token range.
The agent-first pivot maximizes the % of work offloaded to
subscription engines while preserving the agent's context window.
"""


_INSTRUCTIONS = """\
You are one of 5 W11 planning-panel reviewers.  Use the state
snapshot + your assigned lens to produce a CONCRETE planning
artifact.  Output structure (≤800 words; markdown tables welcome):

## Output structure

1. **Top-line summary** — 2-3 sentences with your lens's
   recommendation.

2. **The concrete artifact** — the tables / lists / specs that
   your lens uniquely produces.  This is the bulk of the output.

3. **Two open questions** the operator should answer before
   shipping starts.

4. **Alignment check** — anything in the queue you'd reorder,
   merge, or split based on your lens.

No preamble.  Be CONCRETE not aspirational.  Your lens:
"""


def _run_one(engine_name: str, model: str, pid: str, lens: str,
             snapshot: str) -> tuple[str, str, str]:
    started = time.monotonic()
    try:
        eng = get_engine(engine_name, prefer_dpapi=False)
    except RuntimeError as exc:
        return (pid, f"engine init failed: {exc}", "FAIL")
    prompt = snapshot + "\n\n---\n\n" + _INSTRUCTIONS + lens
    resp = eng.dispatch(prompt, model, {"max_tokens": 6500})
    elapsed_ms = int((time.monotonic() - started) * 1000)
    if not resp.success or not (resp.text or "").strip():
        return (pid, f"engine failed: {resp.error}", "FAIL")
    return (pid, resp.text.strip(), f"OK ({elapsed_ms}ms)")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("[w11-planning] gathering snapshot...", file=sys.stderr)
    snapshot = _gather_snapshot()
    (OUT_DIR / "_state_snapshot.md").write_text(snapshot, encoding="utf-8")
    print(f"[w11-planning] snapshot: {len(snapshot)} chars", file=sys.stderr)

    print(f"[w11-planning] dispatching {len(PERSONAS)} reviewers...",
          file=sys.stderr)
    started = time.monotonic()
    results: dict[str, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_run_one, eng, model, pid, lens, snapshot): pid
            for eng, model, pid, lens in PERSONAS
        }
        for f in as_completed(futures):
            pid, text, status = f.result()
            results[pid] = (text, status)
            text_len = len(text)
            print(f"  [{status}] {pid:<30} text_len={text_len}",
                  file=sys.stderr)
    elapsed_s = time.monotonic() - started
    print(f"\n[w11-planning] elapsed {elapsed_s:.0f}s", file=sys.stderr)

    for pid, (text, status) in results.items():
        (OUT_DIR / f"{pid}.md").write_text(
            f"<!-- persona={pid} status={status} -->\n\n# {pid}\n\n{text}\n",
            encoding="utf-8",
        )

    synth_lines = [
        "# W11 execution-planning panel — synthesis",
        "",
        f"_Dispatched: {len(PERSONAS)} reviewers, elapsed {elapsed_s:.0f}s_",
        "",
    ]
    for eng, model, pid, lens in PERSONAS:
        text, status = results.get(pid, ("(no response)", "MISSING"))
        synth_lines.append(f"## {pid}  ({eng}/{model})\n\n{text}\n\n---\n")
    (OUT_DIR / "SYNTHESIS.md").write_text(
        "\n".join(synth_lines), encoding="utf-8",
    )
    print(f"[w11-planning] wrote synthesis: {OUT_DIR / 'SYNTHESIS.md'}",
          file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
