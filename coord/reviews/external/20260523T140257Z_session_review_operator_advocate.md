<!-- engine=mimo model=mimo-v2.5-pro success=True latency_ms=50671 tokens_in=16854 tokens_out=2402 persona=operator_advocate -->

# Review by Operator Advocate

# Operator Advocate Review — xaxiu-harness Session 2026-05-23

## Top 3 Concerns

### 1. Stop-hook spam is hostile UX — and it's still firing

Operators #8 through #15, #20, #23 through #31, and #57 through #60 are *all identical stop-hook messages* about `check-csv-stale.sh` detecting warehouse files modified by *other projects*. That's roughly **20 of 76 operator messages** — over a quarter of the session — consumed by a hook that is misfiring on cross-project noise the operator cannot suppress. The hook checks `D:/Projects/warehouse/` which is shared across every project on the system. This isn't a warning — it's a persistent interruption that forced the operator to either ignore it or interrupt the agent to acknowledge it. The operator *never once acted on this signal*. It added zero value and extracted maximum friction. This hook either needs project-scoped file globs or a one-line guard that ignores files outside the harness working tree.

### 2. Kimi went 0/10 across multiple campaigns and nobody noticed until the operator investigated (W5-V)

The operator's own words: "the fact that you have 0 kimi indicate your way of wiring kimi is incorrect, throughout multiple attempts." Three bugs — missing `stream:true`, non-standard SSE `data:{` vs `data: {`, missing `import json` — combined to make Kimi silently fail on every single dispatch. The harness has silent-no-op detection for *workers* (W4-A) and *integrators* (W4-B), but the dispatch layer itself had no mechanism to flag "this engine returned 0 successful responses across 10 attempts." The operator discovered the pattern by reading campaign results, not because the harness surfaced it. **A dispatch engine that fails 10/10 should auto-log a diagnostic entry and surface a loud warning** — not silently score each as an individual failure and move on.

### 3. No `harness status` — readiness is a guess, not a fact

The operator asked "is my observer armed" (#40) and "is the harness ready to be used" (#44) multiple times because **there is no single verb that answers this question**. To verify readiness today you need to: run `harness doctor`, check `coord/STATUS.csv`, verify Task Scheduler tasks, confirm each engine's API key is set and non-expired, and grep for recent observer cycles. That's 5+ manual checks. A tool that requires this much legwork to know "am I good to go?" will not survive contact with an overnight unattended run. The `harness start` verb (W5-SS) with its orchestrator picker and mode toggle is a step in the right direction, but it doesn't surface pre-flight readiness as a gate. You should not be allowed to start if any engine has a dead key or the observer is unregistered.

## What Was Done Right

- **Silent no-op guards (W4-A, W4-B)** are exactly the kind of defense-in-depth that prevents "everything looks green but nothing happened" production incidents. Steal this pattern for every handoff point in the pipeline.
- **Bypass chain + visible substitution warning (W3-A)**: When the system does something unexpected (engine substitution), it *tells you* with a WARNING log. This is the right default for a multi-engine system.
- **`scripts/infra_smoke.py` (W2-INFRA-SMOKE)**: A 6-category, 17-check matrix that validates the entire harness surface area in one command. This should be a `harness doctor` expansion, not a standalone script — but the design is right.
- **CRLF-tolerant FILE/REPLACE (W5-J)**: Caught a real ship-blocker caused by Windows line endings. The fix was surgical and the regression test proves it.
- **Engine-agnostic memory (W5-S)**: Universal memory that any engine can read is the correct architectural decision for a multi-engine system. This is the feature that makes the harness worth having.
- **`harness session ok-to-stop`**: A machine-readable answer to "should I keep going" is exactly what unattended operation needs. The concept is right even if the execution needs polish.
- **20-agent cross-engine coverage campaign**: Using the engines themselves to stress-test the harness is a genuinely novel validation approach. MiMo 9/10 surfacing 6 novel ideas proves the concept.

## DIRECTIVE

**Ship a `harness preflight` verb that runs every readiness check in <30 seconds and outputs a single pass/fail matrix with zero ambiguity.** It must check: each engine key is set and non-expired (fire a 1-token probe), observer is registered in Task Scheduler, STATUS.csv is writable, pytest is green (or cache last result), and git working tree is clean. Gate `harness orchestrator start` behind a green preflight. No operator should ever have to ask "is it ready?" again — the answer should be on screen in one command.

## Confidence Level

**0.35** — The code is well-tested (1354/1354 green) and the architectural decisions are sound. But from the operator lens: the stop-hook spam alone would make me disable hooks entirely, Kimi's 0/10 silent failure proved the dispatch layer can't be trusted to surface its own breakage, and the absence of a readiness gate means the first overnight run *will* start in an unknown state. The harness is a capable development tool; it is not yet an unattended-overnight tool. The gap between those two states is exactly the `harness preflight` verb described above, plus a dispatch-layer health signal that screams when an engine fails N/N in a row.