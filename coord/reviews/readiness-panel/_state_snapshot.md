## CLI verbs (`harness --help`)

```
Usage: python -m harness [OPTIONS] COMMAND [ARGS]...

  xaxiu-harness: dispatch, observe, and retro across LLM engines.

Options:
  --mode [review_each|full_dev_authority|dry_run]
                                  Operator mode: review_each /
                                  full_dev_authority / dry_run.
  --escalation-threshold [L1|L2|L3|L4|L5]
                                  Only escalations at or above this level
                                  surface to operator.
  --engine-fill [aggressive|conservative|manual]
                                  Whether to fill idle Kimi slots with queued
                                  work.
  --max-parallel-supervisors INTEGER
                                  Max supervisors that may run in parallel
                                  within a tick.
  --explore-on-uncertainty [dispatch_alternatives|inline|ask_operator]
                                  What to do when the dev manager is
                                  uncertain.
  --observer-cadence-minutes INTEGER
                                  Cadence for the workflow-audit observer
                                  cycle.
  --profile [technical|non_technical]
                                  Operator profile (affects packet templates /
                                  error verbosity).
  --help                          Show this message and exit.

Commands:
  adapter              Manage harness adapters (generate, list, validate).
  budget               Dispatch budget + per-engine cost ledger.
  burst                Temporarily route all traffic to one engine.
  coord                Coordinator commands: plan, run, integrate, status.
  dashboard-serve      Run the operator-facing dashboard.
  dispatch             Execute a packet; auto-route if no backend is given.
  doctor               Preflight: check git, python, DPAPI, secrets,...
  engines              Query or modify the engine pool.
  engines-cooldowns    Show active engine cooldowns.
  engines-heal         W8-ENGINES-HEAL: one-command recovery for dead /...
  engines-reliability  Show / publish engine reliability ranking from...
  env                  Check which API keys are set (reports per-key +...
  heartbeat            Passive dev-manager liveness signal for the operator.
  init                 Create starter adapter YAML for a project.
  install              Setup Task Scheduler entries and first-run wizard.
  lint-spec            Pre-flight: validate a markdown spec for...
  lock                 Exclusive routing lock (disables auto-routing).
  loop                 Autonomous dev loop — productized coord/dev_loop/...
  loops                Manage user-defined scheduled loops.
  memory               W5-S: engine-agnostic operator memory (memory/*.md...
  morning-brief        W5-RR 2026-05-23: end-of-overnight DeepSeek...
  observer             Independent harness observer — authority audit,...
  orchestrator         W5-T: autonomous orchestrator (Path α:...
  panic-dump      
```

## `harness preflight --skip-engines` output

```
harness preflight — autonomous-mode readiness gate
============================================================
  [OK] dead_engines         all engines below failure threshold  (19ms)
  [!] git_clean            3 untracked files  (882ms)
  [OK] loops                dev loop task armed  (4464ms)
  [OK] observer             4 observer task(s) armed  (4347ms)
  [OK] pytest_cache         last pytest run green  (0ms)
  [OK] status_csv           writable, last touched 0.1h ago  (0ms)
============================================================
  5 ok, 1 warn, 0 fail in 4465ms

```
Exit code: 1

## `harness doctor` output

```
harness doctor — preflight diagnostics
==================================================
  [OK] python           Python 3.13 OK
  [OK] git              git installed + identity set
  [OK] dpapi            DPAPI read works
  [OK] secrets          engine keys available: dpapi=(none) env=['DEEPSEEK_API_KEY', 'KIMI_API_KEY', 'MIMO_API_KEY']
  [OK] engine_reachability env=KIMI_API_KEY mimo=tokenplan
  [OK] env_var_inventory KIMI_API_KEY:SET, DEEPSEEK_API_KEY:SET, ANTHROPIC_API_KEY:UNSET, GEMINI_API_KEY:UNSET, MIMO_API_KEY:SET, OPENAI_API_KEY:UNSET
          fix: Set at least one engine API key in your environment
  [OK] coord_dir        coord/ is writable
  [OK] task_scheduler   Task Scheduler reachable
==================================================
overall: OK

```

## STATUS.csv (296 rows)

First 3 rows + last 5 rows:

```csv
ID,Category,Title,Status,Owner,Effort,Updated,Notes
W19-STATUS-TRACKER,Wave 5.5,Canonical STATUS tracker as harness primitive (src/harness/status/ + harness status CLI verbs),shipped,Kimi+Claude,~45 min,2026-05-21,Commit 514945f; hybrid Kimi-CLI partial + Claude inline; 305/305 tests; 90% coverage
W20-OBSERVER,Wave 5.6,Independent observer primitive (the check on dev-manager authority),shipped,Kimi via swarm,~60 min,2026-05-21,Kimi-CLI landed 6 module files (state/scheduler/cycle/audit_prompt/flags/__init__) + tests/test_observer.py (22KB; 41 tests) + cli.py observer group (12 subcommands) + manager.md Step 0 during 1200s timeout per feedback_kimi_cli_incremental_edits. Claude removed obsolete observer_tick stub test. 346/346 tests pass; 79% coverage on harness.observer.
...
W9-REDACTION-INTEGRITY-TEST,Security,Test that no secret pattern leaks to any output surface,todo,Claude,-,2026-05-24,"Surfaced by master audit (M09 SECURITY-POSTURE). Worst path: dispatch sends operator-controlled packet content to an LLM engine via proxy holding 4 API keys → prompt injection → engine exfiltrates key material into response → response logged or surfaced via retro/replay/today/panic-dump BEFORE redaction runs. Fix: enumerate every output surface, assert no known-secret-pattern (API key prefix, DPAPI blob, env var value) appears unredacted in any of their outputs. Memory file integrity check is a related sub-task."
W9-PROXY-FAILURE-MATRIX,Production,Document + test proxy fail-open vs fail-closed for each failure mode,todo,Claude,-,2026-05-24,"Surfaced by master audit (M13 PROXY-SAFETY). The v2/A proxy is an opaque safety layer with zero proxy tests in the mutation kill-rate table. The defining auto-quarantine-on-flap feature was demonstrably silently-broken for an unknown duration. Acceptance: produce a failure-mode matrix for (single key revoked, all keys exhausted, circuit-breaker open, all engines quarantined, TLS handshake failure) documenting (a) observable behavior, (b) fail-open vs fail-closed, (c) operator action required. Add proxy mutation tests."
W9-MUTATION-MANIFEST,Process,Track mutation coverage by module; auto-flag stale modules,todo,Claude,-,2026-05-24,Surfaced by master audit (M07 MUTATION-COVERAGE). The 5-module mutation kill rate is a static snapshot of 5 of ~20+ modules. W8 shipped 32 tests without re-running the sweep. Fix: mutation_targets.yaml listing every module + last-sweep SHA + ≥3 known-killer mutants per module. Any module shipping code without a passing sweep auto-flags. CI gate optional. Transforms the snapshot into an enforced tracker.
W8-SESSION-HANDOFF,Process,Wave 9 session-handoff doc + master prompt authored,shipped,Claude,-,2026-05-24,"coord/SESSION_HANDOFF_2026-05-24.md — self-contained master prompt for next session. Captures: full-dev-authority + L5-only escalation, HEAD state (1576 tests + 14 W9 rows queued), panel-recommended W9 ordering (1=W9-AUDIT-NONDETERMINISM-AVG, 2=W9-MUTATION-CANARY, 3=W9-CLI-TIMEOUT-BUDGET + W9-PREFLIGHT-FIX-NOSTASH parallel, 4=W9-SILENT-EXCEPTION-AUDIT, 5=W9-READINESS-PANEL-RERUN), boot sequence, hook gotchas (CRLF false-positive + --fix auto-stash), stash recovery. Mirrors W6 SESSION_HANDOFF pattern."
2026-05-24T051206Z,Dispatch,Dispatch 2026-05-24T051206Z,shipped,Claude,-,2026-05-24,task=e672e57d883649138df136c0b23d0445; outcome=success
```

## Test count

1544 passed + 6 skipped

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
