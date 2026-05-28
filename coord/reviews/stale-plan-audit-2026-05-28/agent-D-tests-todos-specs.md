# Agent D: Test + TODO + spec drift audit (2026-05-28)

Scope: skipped tests, TODO/FIXME/XXX comments in `src/harness/`, and spec/*.md drift vs. live implementation.

Method: grepped tests for skip markers; grepped `src/harness/` for `\bTODO\b|\bFIXME\b|\bXXX\b|\bHACK\b`; read 10 of 23 spec docs (prioritizing those with concrete file paths / function names / verb tables); cross-checked against the actual CLI surface (`cli.commands.keys()` = 62 top-level verbs, ran subcommand dump on `status`/`loop`/`observer`/`session`); ran `pytest --collect-only` (3171 tests collected, no collection errors).

---

## Section 1: Skipped tests

| Test | Skip reason | Verdict | Action |
|---|---|---|---|
| `tests/test_engines_tokens_live.py:33` (`pytestmark`) | "set HARNESS_LIVE_TESTS=1 to run live API token tests" | SKIP-VALID | Live API gate — intentional CI opt-in. |
| `tests/test_engines_tokens_live.py:57,73,89,157` | "<engine> unavailable: <err>" / "no engines available for budget e2e check" | SKIP-VALID | Per-engine availability fallthrough inside live tests; correct. |
| `tests/test_env_rotate.py:28` (`WINDOWS_ONLY`) | "DPAPI is Windows-only; rotation surface tested via mocks elsewhere" | SKIP-VALID | Platform gate. |
| `tests/test_keys_ui.py:126` | "POSIX file modes only" | SKIP-VALID | Platform gate. |
| `tests/test_observer_autoarm_all.py:53` | "db_scheduler module not yet shipped" | **SKIP-STALE** | `src/harness/state/db_scheduler.py` exists and exports `register_snapshot_task` + `unregister_snapshot_task`. The `try/except ImportError` guard will never fire — skip text is wrong-by-now. Action: drop the try/except guard + skip; import db_scheduler unconditionally. |
| `tests/test_observer_autoarm_all.py:78` | "db_scheduler module not yet shipped" | **SKIP-STALE** | Same as above — second occurrence, same issue. |
| `tests/test_oncommit_hook.py:29` (`pytestmark`) | "bash not available — hook is a bash script" | SKIP-VALID | Tool-availability gate. |
| `tests/test_stop_hook_script.py:34` (`pytestmark`) | "bash not available on this platform" | SKIP-VALID | Tool-availability gate. |
| `tests/test_wrapper_scripts.py:239` | "Executable bit not meaningful on Windows" | SKIP-VALID | Platform gate. |
| `tests/test_worker_mutation_killers.py:291,307,325` | "fuzzy_replace returned None for this drift pattern" | SKIP-VALID | Fuzzy-match probe; skipping when the probe legitimately can't match is the documented contract. |

Cross-check on the SKIP-STALE finding:

```
$ ls src/harness/state/db_scheduler*
src/harness/state/db_scheduler.py
$ PYTHONPATH=src python -c "from harness.state import db_scheduler; print(dir(db_scheduler))"
[…, 'register_snapshot_task', 'unregister_snapshot_task', …]
```

The module exists. The two skip paths in `test_observer_autoarm_all.py` are guarding for an already-met condition. The tests will run on every CI invocation, so this is dead code, not a hidden-coverage gap — but the comment is now misleading and should be removed.

### No `@pytest.mark.skipif` outside platform/availability gates, no `@pytest.mark.xfail` in the suite.

```
$ grep -rn "xfail\|pytest.mark.skip\>" tests/ | wc -l
0
```

So no xfail-trapped features either.

---

## Section 2: TODO/FIXME/XXX comments

The full `\bTODO\b|\bFIXME\b|\bXXX\b|\bHACK\b` grep over `src/harness/` returned **3 hits total, all non-actionable**:

```
src/harness/cli.py:3350:    Each cycle picks the next open TODO, composes a spec via the
src/harness/orchestrator.py:13:  1. Pick next TODO from coord/STATUS.csv
src/harness/status/schema.py:14:    TODO = "todo"
```

### TODO-STALE (already fixed elsewhere)

- *none*

### TODO-VALID (still relevant, no action)

- *none — see classification below.*

### TODO-OBSOLETE (feature no longer needed)

- *none*

### Non-actionable / not a real TODO marker

All 3 hits are documentation references to `Status.TODO` (the StrEnum value used in `coord/STATUS.csv`), NOT pending-work `# TODO:` comments:

- `src/harness/cli.py:3350` — docstring describing the orchestrator's behavior: "Each cycle picks the next open TODO" (refers to a status-csv row whose status is `todo`).
- `src/harness/orchestrator.py:13` — module docstring: "Pick next TODO from coord/STATUS.csv" (same meaning).
- `src/harness/status/schema.py:14` — `TODO = "todo"` enum member declaration in the `Status` StrEnum.

**Net result: zero pending-work TODOs in `src/harness/`.** Either the project has been very disciplined about closing them, or the convention here is "open a STATUS.csv row instead of leaving a TODO in source" — which is consistent with the canonical-tracker memory `feedback_status_csv_canonical`. Either way: no action.

---

## Section 3: spec/*.md drift

Reviewed: `v1-architecture.md`, `v1.1-operator-experience.md`, `multi-agent-harness-architecture.md`, `errors.md`, `operator-modes.md`, `observer.md`, `status-tracker.md`, `session-handoff-monitor.md`, `proxy-recovery.md`, `proxy-failure-matrix.md`, `autonomous-loops.md`, `wave-{4,5,6,9,10,11}-plan.md`, `coord-run-runbook.md`, `engine-routing-empirical.md`, `session-derived-feature-roster.md`, `ACCEPTED_LIMITATIONS.md`.

### Finding 1: spec/v1-architecture.md — stale repo path
- **Spec says** (line 6): "`D:/Projects/xaxiu-harness/`" — given as the repo root.
- **Reality**: Project relocated to `D:\xaxiu-harness-standalone\` on 2026-05-22 (see MIGRATION.md / `CLAUDE.md` line 4 of project instructions).
- **Suggested action**: replace path or add a 1-line "moved 2026-05-22 — see MIGRATION.md" header. Cheap fix; high visibility.

### Finding 2: spec/v1-architecture.md — engines/ layout
- **Spec says** (lines 12-14): `engines/` contains only `__init__.py, base.py, deepseek.py, kimi.py, anthropic.py`.
- **Reality**: actual layout has 18 entries — `_retry.py, base.py, claude_code_subprocess.py, concrete.py, dispatch_cache.py, dispatcher.py, gemini.py, guards.py, metadata.py, mock.py, parallel_dispatch.py, pool_dispatch.py, reliability.py, routing.py, routing_recommend.py, transport.py, wrapper_scripts.py` (and no per-engine `deepseek.py` / `kimi.py` / `anthropic.py` files — those folded into `concrete.py`).
- **Suggested action**: either replace the directory listing with a "see actual code" pointer, or refresh the bullet list. This spec is "v1" and intentionally frozen — likely best to add an "as-built drift" header rather than rewrite.

### Finding 3: spec/v1.1-operator-experience.md — stale repo path
- **Spec says** (line 3): "`D:/Projects/xaxiu-harness/spec/v1.1-operator-experience.md`"
- **Reality**: lives at `D:\xaxiu-harness-standalone\spec\v1.1-operator-experience.md`.
- **Suggested action**: same as Finding 1.

### Finding 4: spec/autonomous-loops.md — `harness loop` verb table doesn't match shipped surface
- **Spec says** (lines 38-48): `harness loop` group should expose `list, start, pause, resume, status, tick, logs, escalations, uninstall` — 9 subcommands.
- **Reality**: shipped surface is `init, start, status, stop, tick` — 5 subcommands. `list`, `pause`, `resume`, `logs`, `escalations`, `uninstall` were never wired; `init` and `stop` were added in their place.
- **Suggested action**: this is real drift. Either ship the missing verbs (5 of them), or amend the spec to match what was shipped + drop the 5 unimplemented ones. The session-derived-feature-roster row #12 marks this as ✅ — but the verb surface is partial. Worth resolving.

### Finding 5: spec/observer.md — verb table is a strict subset of what shipped (additive drift, not stale)
- **Spec says** (lines 73-80): observer should expose `init, arm, disarm, pause, resume, cycle-now, status, flags`.
- **Reality**: shipped surface is `ack, arm, audit-chat, budget-watch, cycle-now, daily-retro, disarm, flags, init, install-scheduler, pause, restart, resume, status, uninstall-scheduler, watchdog-status` (16 subcommands; all spec verbs present, plus 8 more from Wave 8/9/11+).
- **Suggested action**: spec is a snapshot, not stale per se. Add a paragraph "post-W6 additions: ack, audit-chat, budget-watch, daily-retro, install-scheduler, restart, uninstall-scheduler, watchdog-status — see CLI --help for current list." Low priority.

### Finding 6: spec/errors.md — first-wave subclass table is a strict subset
- **Spec says** (lines 38-50, "First-wave subclasses; more added by Wave A.6 retrofit"): 10 subclasses listed.
- **Reality**: 10 spec'd subclasses present + 2 added later (`StateLockTimeout` L3.state.E_STATE_LOCK_TIMEOUT, `WorktreeMissing` L4.dispatch.E_MISSING_WORKTREE).
- **Suggested action**: spec already warns about future additions; SPEC-MATCH within stated tolerance. No action needed beyond the routine retrofit the spec already promised.

### Finding 7: spec/wave-{4,5,6,9,10,11}-plan.md — wave-plan specs are historical
- **Reality**: wave plans are forward-authored, then partially shipped, then frozen. Each row is independently audited (W6 introduced the MiMo audit gate per spec). These are archived plans, not living specs — drift is expected and is tracked via the `session-derived-feature-roster.md` ✅ rollup + `STATUS.csv` shipped/parked rows.
- **Suggested action**: no spec drift to fix; verify rollup discipline holds elsewhere (Agent A/B/C scope).

### Finding 8: spec/status-tracker.md — implementation matches; one mention worth updating
- **Spec says** (line 102): "Existing 33-row STATUS.csv passes `harness status verify`" — the row count is historical.
- **Reality**: STATUS.csv grew significantly since the spec was authored. Acceptance is met (`verify` still works) but the number is stale.
- **Suggested action**: drop the literal "33-row" / change to "current row count". Trivial.

### Finding 9: spec/multi-agent-harness-architecture.md — module references valid
- **Spec says** (§2 + §3): coordinator, planner, worker, integrator, proxy at `src/harness/{coord,proxy}/...`. Each named subcomponent claimed to exist.
- **Reality**: all referenced modules exist (`src/harness/coord/{coordinator,planner,worker,integrator,checkpoint,worktree,schemas,run_state,...}.py` + `src/harness/proxy/{app,circuit,handlers,router,server,state,upstreams,lifecycle}.py`). SPEC-MATCH.

### Finding 10: spec/proxy-recovery.md, spec/proxy-failure-matrix.md, spec/session-handoff-monitor.md, spec/operator-modes.md, spec/coord-run-runbook.md — verified
- Spot-checked CLI verbs and module references; all named handles still resolve. SPEC-MATCH on these.

---

## Section 4: Import errors / orphaned tests

`PYTHONPATH=src python -m pytest tests/ --collect-only -q` runs clean: **3171 tests collected in 5.58s, zero collection errors**.

No tests import deleted modules. No deprecated CLI verbs in test code without backing implementation (62 top-level CLI verbs all importable). No orphaned tests detected.

---

## Summary

- **2 skipped-stale tests**: both at `tests/test_observer_autoarm_all.py:53,78` — guarding for `db_scheduler` "not yet shipped", but the module ships at `src/harness/state/db_scheduler.py` and the import succeeds. Skip text is misleading; the try/except branch is dead. Drop the guard.
- **0 stale TODOs**: the 3 grep hits in `src/harness/` are all docstring references to the `Status.TODO` enum value, not pending-work markers.
- **4 spec drifts worth fixing** (Findings 1, 3, 4, 8):
  - 2 stale repo paths in `v1-architecture.md` + `v1.1-operator-experience.md` (`D:/Projects/xaxiu-harness/` → `D:/xaxiu-harness-standalone/`).
  - `autonomous-loops.md` documents 9 `harness loop` subcommands; only 5 shipped — real implementation gap or spec needs trimming.
  - `status-tracker.md` references a stale "33-row" STATUS.csv literal.
- **3 spec drifts informational only** (Findings 2, 5, 6): one spec snapshot vs as-built directory listing (`engines/`), and two cases where the shipped surface is a strict superset of the spec'd surface (`harness observer` + `errors.py` subclasses) — both already noted in their respective specs as "additions expected".
- **0 orphaned tests** — full suite collects cleanly.

**Net headline**: the test suite is in good shape; the only material drift hides in `spec/autonomous-loops.md` (loop verb surface mismatches reality by 5 of 9 verbs) and in the two stale paths in the v1 specs. The two `db_scheduler` skip guards in `test_observer_autoarm_all.py` should be removed since the module has shipped.
