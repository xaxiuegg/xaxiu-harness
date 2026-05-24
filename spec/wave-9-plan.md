# SPEC-ID: wave-9-plan — Detection-gate tightening + state safety + production hygiene

**Authored**: 2026-05-24 from the 40-reviewer master audit
(`coord/reviews/master-audit/OPERATOR_SUMMARY.md`).

**Theme**: the Wave 8 detection layer landed half-finished.  The audit
gate flips PASS↔STOP under noise; the mutation canary that would
bypass MiMo entirely was deferred; the silent-failure pattern that
broke quarantine for weeks likely exists elsewhere; operator-facing
commands hang under contention; `preflight --fix` silently stashes
in-progress work.  Wave 9 closes those gaps and audits the rest of
the state-write surface before the next horizon.

Verdict tally from the master audit: **0/40 SHIP-AS-IS, 10/40 HOLD,
30/40 SHIP-WITH-FIXES** — every reviewer wanted at least one of the
W9 rows before the next wave.

## Phases (composite-vote ordering)

### Phase 1 — Audit-gate determinism (every later verdict depends on this)

#### W9-AUDIT-NONDETERMINISM-AVG — `--avg-of-N` flag on the audit gate

`audit_task_with_mimo.py` re-runs N times, aggregates mean +
stdev + min + max + pass_count, gates on mean ≥ 0.7.  N=1 keeps
legacy single-run behavior.

**Acceptance**:
- `--avg-of-N N` flag accepted; defaults to 1 (legacy behavior preserved)
- N>1 runs the audit in parallel via ThreadPoolExecutor (capped at 5 workers for rate politeness)
- Pure `aggregate_runs()` helper exposed for unit testing
- Final exit code based on **mean confidence** vs 0.7 gate, not single-run
- Combined report at `coord/reviews/audits/<stamp>_<task-id>_audit_avg<N>.md` with header (mean/stdev/min/max/pass_count) + per-run raw responses
- Failed runs (engine init error, timeout) excluded from the mean but counted in the failed-runs total
- Tests cover: parse_audit_response, aggregate_runs (single + N=3 + all-failed + partial-failure + empty), formatters, plan-path routing
- Test count rises (1576 → 1595)

### Phase 2 — Deterministic regression signal (bypass MiMo entirely)

#### W9-MUTATION-CANARY — 3-mutant rolling spot-check

Deferred from W8 Track A.  Now load-bearing because the master
audit confirms MiMo non-determinism dominates the noise floor —
the canary is the ONLY deterministic regression signal
independent of MiMo.

**Acceptance**:
- `scripts/run_mutation_canary.py` runs in <3 min wall clock
- Applies exactly 3 known-killer mutations to one module per run
- Default rotation order: proxy → observer → loops → dashboard → engines (cycles)
- Rotation state stored in `coord/canary_state.json` (next module to test)
- Each mutation expects ≥1 test failure; a 0-kill mutation auto-flags a follow-up row in STATUS.csv
- Exit 0 = all mutations killed; exit 1 = at least one mutation survived
- Smoke test in tests/ exercises the mutator with a tiny fixture module + a single canned mutation

### Phase 3 — Operator-facing safety (parallel)

#### W9-CLI-TIMEOUT-BUDGET — perf-regression gate on operator commands

35 of 40 reviewers cited `harness preflight --skip-engines` and
`harness today` timing out at 30s in the panel snapshot.  Direct
invocation is ~7s; under contention with 20 concurrent
dispatches both blow past the budget.

**Acceptance**:
- `tests/test_perf_budget.py` asserts `harness preflight --skip-engines` completes in <8s wall clock when invoked cold
- Same test asserts `harness today` completes in <10s
- A separate test exercises both commands under contention (5 concurrent invocations); each is allowed up to 2× budget but must not deadlock
- If a check exceeds its sub-budget (loops or observer step), preflight degrades gracefully (skips that check + warns) instead of hanging
- README operator runbook callout: "preflight may run 2× slower if a dispatch is in flight; this is expected"

#### W9-PREFLIGHT-FIX-NOSTASH — kill silent stash data-loss in `preflight --fix`

20 of 40 reviewers cited the silent `git stash` that
disappeared in-progress work during W8 (caught via `git stash
pop`).  Acceptable resolutions: skip stash for git_clean
fixes, surface "X files stashed → recover with `git stash pop`"
loudly, OR require `--allow-stash` to enable the auto-stash.

**Acceptance**:
- Running `harness preflight --fix` against a dirty working tree no longer silently stashes
- If auto-stash is needed for a specific fix, the operator sees a loud single-line warning naming the stash entry and the recovery command
- A new `--allow-stash` flag re-enables the legacy auto-stash silent behavior if needed (zero-surprise default; opt-in surprise)
- Test exercises the dirty-tree case + verifies no `git stash` is invoked without the flag
- README runbook section updated to describe the new behavior

### Phase 4 — Silent-failure audit

#### W9-SILENT-EXCEPTION-AUDIT — grep + harden `except .*: continue` pattern

The `except Exception: continue` pattern silently swallowed
every Pydantic ValidationError in `preflight.fix_dead_engines`
for an unknown duration before W8.  M08 flagged this as the
highest-probability next failure mode.

**Acceptance**:
- `grep -rn "except.*continue\|except.*pass" src/harness/` produces a documented list at `coord/reviews/silent-exception-audit.md`
- Each occurrence in the production hot-path (engines/, dispatch/, state/, proxy/, coord/) either: (a) logs at WARNING level with the exception text, (b) re-raises a typed HarnessError with the L1-L5 + domain tag, or (c) carries an inline comment explaining why silence is intentional
- A new lint rule in `src/harness/lint.py` (or scripts/lint_silent_except.py) flags new `except .*: continue` additions in source review
- Test count rises by the number of files touched (one regression test per converted site if non-trivial)

### Phase 5 — Re-run readiness panel

#### W9-READINESS-PANEL-RERUN — measure the YES-vote delta

W8 readiness panel: 0/10 YES votes at wave-start.  Now that
preflight --fix + runbook + status --human + engines heal all
ship, re-run the same 10-reviewer panel.  Expected: YES count
above 0; new blockers surface for Wave 10.

**Acceptance**:
- `scripts/run_readiness_panel.py` invoked + produces a fresh `coord/reviews/readiness-panel/<stamp>_*` set
- Delta vs the W8 baseline (0/10 YES) recorded in `coord/reviews/wave-9-closeout.md`
- New convergent blockers (cited by ≥3 reviewers) added as Wave 10 candidates in STATUS.csv
- Panel run logged + reproducible from the script + state snapshot

### Phase 6 — State-write safety

#### W9-STATE-ATOMIC-WRITES — extend `_atomic_write_json` to all state writes

The schema bug proved silent state corruption is real.
`_atomic_write_json` exists in `src/harness/state/files.py` but
is not the universal write path.

**Acceptance**:
- Every state-file mutation site (engine_health.json, active_dispatches.json, loops.json, observer flags, runs/* checkpoints) routes through the temp+rename helper
- The helper raises a typed `StateFileCorruptError` (L4.state.E_corrupt) on serialization failure rather than swallowing it
- Integration test: kill mid-write (simulated by raising in the write callback) leaves the original file intact + no partial temp file
- `grep -rn "open.*w" src/harness/state/ src/harness/engines/health.py` shows zero remaining direct writes to JSON state files

#### W9-STATE-FILE-LOCK — advisory locks on shared mutable state

`engine_health.json` is shared across ThreadPoolExecutor,
asyncio, and multiprocessing with no synchronization.  M11
called out the textbook data race.

**Acceptance**:
- `portalocker` (or fcntl-equivalent on Windows) advisory locks wrap the read-modify-write cycle in `_check_dead_engines` + `engines heal` + `preflight --fix`
- Concurrent smoke test: submit two `preflight --fix` calls to a ThreadPoolExecutor; assert no duplicate quarantine writes + no lost updates
- Lock acquisition timeout (5s) raises `L4.state.E_lock_timeout` rather than hanging
- Lock files cleaned up on process exit

### Phase 7 — Security posture

#### W9-REDACTION-INTEGRITY-TEST — assert no secret-pattern leaks anywhere

M09 worst-case path: prompt injection → engine exfiltrates key
material into response → logged via retro/replay/today/panic-dump
before redaction runs.  No redaction-integrity tests exist.

**Acceptance**:
- `tests/test_redaction_integrity.py` enumerates every operator-facing output surface (retro, replay, today, panic-dump, status, dashboard JSON)
- For each surface, a test injects a known-secret-pattern (API key prefix `sk-`, DPAPI blob magic bytes, env-var value) into a synthetic transcript + asserts the secret never appears in the surface's output
- Memory-file integrity check: a tampered memory file produces a loud warning at preflight time
- `harness env` per-key reporting is verified to not leak any key value in any mode (including debug)

### Phase 8 — Proxy hardening

#### W9-PROXY-FAILURE-MATRIX — document + test proxy fail-modes

M13: the v2/A proxy is an opaque safety layer with zero proxy
tests in the mutation kill-rate table.  Auto-quarantine-on-flap
was silently broken for an unknown duration before W8.

**Acceptance**:
- `spec/proxy-failure-matrix.md` produced: for each failure mode (single key revoked, all keys exhausted, circuit-breaker open, all engines quarantined, TLS handshake failure) documents observable behavior, fail-open vs fail-closed, operator action
- Test for each row: simulate the failure + assert the documented behavior
- Mutation kill tests added for `src/harness/proxy/*.py` (≥3 known-killer mutants); kill rate ≥0.5
- Proxy added to the canary rotation

### Phase 9 — Mutation coverage manifest

#### W9-MUTATION-MANIFEST — track mutation coverage by module, auto-flag stale

M07: mutation tracking is a static snapshot of 5 of ~20+
modules.  W8 shipped 32 tests without re-running the sweep.

**Acceptance**:
- `mutation_targets.yaml` lists every module under `src/harness/` with: last-sweep SHA, ≥3 known-killer mutants, kill rate, last-run timestamp
- A new `harness mutation status` (or `harness coverage`) verb reports which modules are stale (SHA differs from current HEAD)
- CI gate (optional): any module shipping code without a passing sweep auto-flags as a new STATUS.csv row
- The canary rotation (W9-MUTATION-CANARY) reads its module list from this manifest

### Phase 10 — Audit anchor flexibility

#### W9-AUDIT-ANCHOR-MULTI-COMMIT — accept commit range, not single anchor

W8-STOP-HOOK + W8-AUDIT-PROMPT both shipped across multiple
commits; the single-anchor audit consistently STOPped because
the auditor only saw the first commit's diff.

**Acceptance**:
- `audit_task_with_mimo.py` accepts `--commit-range A..B` (or `--since N` for the last N commits touching the row's files)
- Combined diff + file-content view assembled from the full range, still respecting the per-file budget
- Backward-compatible with single `--commit` (legacy)
- Tested with a 3-commit deliverable: the auditor sees all 3 diffs

### Phase 11 — Hook bug

#### W9-ONCOMMIT-HOOK-CRLF — strip CR before grep in `.claude/hooks/check-csv-on-commit.sh`

Windows git emits CRLF in `git log --name-only` output; the
hook's `grep -E '^coord/STATUS\.csv$'` anchor never matches
because the trailing CR breaks the `$` anchor.  Hook fires
falsely on commits that clearly touch STATUS.csv.

**Acceptance**:
- Hook strips CR via `tr -d '\r'` (or uses `git log --name-only --pretty= -- coord/STATUS.csv -1` + exit-code check)
- A commit that touches STATUS.csv does NOT trigger the hook warning
- A commit that does NOT touch STATUS.csv DOES trigger the warning (regression-safe)
- Hook self-test in `bin/test-on-commit-hook.sh` for ongoing protection

## Wave-9 closeout (not a separate row, but the wave-exit gate)

When all 14 Wave 9 rows show `Status=shipped` in `coord/STATUS.csv`:

1. Author `coord/reviews/wave-9-closeout.md` summarizing what shipped, the audit sweep verdicts, the readiness-panel delta, and any Wave 10 candidates surfaced.
2. Run a final master-audit sweep (40-reviewer or scaled-down) to capture the post-W9 horizon.
3. Run `harness session ok-to-stop` — exit 0 ends the autonomous loop.

— End of plan —
