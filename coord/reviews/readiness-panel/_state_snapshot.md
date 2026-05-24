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
  daily                W10-DAILY-QUICKSTART-VERB: operator-friendly daily...
  dashboard-serve      Run the operator-facing dashboard.
  dispatch             Execute a packet; auto-route if no backend is given.
  doctor               Preflight: check git, python, DPAPI, secrets,...
  engines              Query or modify the engine pool.
  engines-cooldowns    Show active engine cooldowns.
  engines-heal         W8-ENGINES-HEAL: one-command recovery for dead /...
  engines-reliability  Show / publish engine reliability ranking from...
  env                  Check which API keys are set (reports per-key +...
  env-wizard           W10-ENV-VAR-WIZARD: guided API-key population.
  heartbeat            Passive dev-manager liveness signal for the operator.
  init                 Create starter adapter YAML for a project.
  install              Setup Task Scheduler entries and first-run wizard.
  lint-spec            Pre-flight: validate a markdown spec for...
  lock                 Exclusive routing lock (disables auto-routing).
  loop                 Autonomous dev loop — productized coord/dev_loop/...
  loops                Manage user-defined scheduled loops.
  memory               W5-S: engine-agnostic operator memory (memory/*.md...
  morning-brief        W5-RR 2026-05-23: end-of-overnight DeepSeek...
  observer
```

## `harness preflight --skip-engines` output

```
harness preflight — autonomous-mode readiness gate
============================================================
  [OK] dead_engines         all engines below failure threshold  (18ms)
  [X] git_clean            modified tracked files present (2 entries)  (2135ms)
     → Run to fix:  Commit or stash before going autonomous.
  [!] loops                dev loop task not registered  (7085ms)
     → Run to fix:  harness loop start
  [!] observer             observer probe timed out (5s); will retry next preflight  (6622ms)
     → Run to fix:  re-run preflight or run `harness observer scheduler-status`
  [OK] pytest_cache         last pytest run green  (0ms)
  [OK] status_csv           writable, last touched 0.1h ago  (0ms)
============================================================
  3 ok, 2 warn, 1 fail in 7086ms

  Verdict: FAIL  (exit code 4)
  Hard blocker — autonomous mode refuses to start.

```
Exit code: 4

## `harness doctor` output

```
harness doctor — preflight diagnostics
==================================================
  [OK] python           Python 3.13 OK
  [OK] git              git installed + identity set
  [OK] dpapi            DPAPI read works
  [OK] secrets          engine keys available: dpapi=(none) env=['DEEPSEEK_API_KEY', 'KIMI_API_KEY', 'MIMO_API_KEY']
  [OK] engine_reachability env=MIMO_API_KEY mimo=tokenplan
  [OK] env_var_inventory KIMI_API_KEY:SET, DEEPSEEK_API_KEY:SET, ANTHROPIC_API_KEY:UNSET, GEMINI_API_KEY:UNSET, MIMO_API_KEY:SET, OPENAI_API_KEY:UNSET
          fix: Set at least one engine API key in your environment
  [OK] coord_dir        coord/ is writable
  [OK] task_scheduler   Task Scheduler reachable
==================================================
overall: OK

```

## STATUS.csv (310 rows)

First 3 rows + last 5 rows:

```csv
ID,Category,Title,Status,Owner,Effort,Updated,Notes
W19-STATUS-TRACKER,Wave 5.5,Canonical STATUS tracker as harness primitive (src/harness/status/ + harness status CLI verbs),shipped,Kimi+Claude,~45 min,2026-05-21,Commit 514945f; hybrid Kimi-CLI partial + Claude inline; 305/305 tests; 90% coverage
W20-OBSERVER,Wave 5.6,Independent observer primitive (the check on dev-manager authority),shipped,Kimi via swarm,~60 min,2026-05-21,Kimi-CLI landed 6 module files (state/scheduler/cycle/audit_prompt/flags/__init__) + tests/test_observer.py (22KB; 41 tests) + cli.py observer group (12 subcommands) + manager.md Step 0 during 1200s timeout per feedback_kimi_cli_incremental_edits. Claude removed obsolete observer_tick stub test. 346/346 tests pass; 79% coverage on harness.observer.
...
W10-DPAPI-SEEDING-VISIBILITY,Production,Document DPAPI seed path in OPERATOR_RUNBOOK,shipped,Claude,-,2026-05-25,"docs/OPERATOR_RUNBOOK.md got a new 'Where do API keys live? (DPAPI)' section explaining: where DPAPI lives (Edge password store analogy), file path %APPDATA%\harness\state\secrets.json, recommended setup (harness env-wizard), check-state (harness env), rotation flow (--overwrite), L5 fallback when DPAPI is broken. Non-Python language; operator can follow without engineering."
W10-FRESH-CANARY-MODULES,Process,Run canary on observer/cycle loops/runner dashboard/app to populate manifest,shipped,Claude,-,2026-05-25,"Canary rotation completed full pass through warm-tier modules. coord/mutation_targets.yaml updated with last_sweep_sha=7698602 + last_sweep_date=2026-05-25 + kill-rate notes per module. Results: proxy/circuit 2/2 killed (3rd run, consistent), observer/cycle 0/3 applicable patterns (idioms don't match the 5-pattern template — NEUTRAL pass; flagged for module-specific pattern expansion), loops/runner 1/1 killed (eq_to_neq), dashboard/app TBD on completion. Zero null-SHA warm-tier modules remain at commit time."
W10-MIMO-FILTER-INVESTIGATION,Process,Investigate MiMo content filter blocking every W9 audit,shipped,Claude,-,2026-05-25,"Decision doc at coord/reviews/audit-engine-choice.md: demote MiMo to fallback, promote DeepSeek-v4-flash to primary. Root cause: MiMo content filter trips on audit prompts that name live API keys verbatim (KIMI_API_KEY etc) which the harness audit prompt does by design when describing failure modes. Filter trips during prompt itself; no restructuring will reliably avoid it. DeepSeek-v4-flash has 1M context vs MiMo 131K, no content filter, ~$0.03/wave at observed token usage. scripts/audit_task_with_mimo.py::_dispatch_with_fallback swapped: now tries DeepSeek primary, falls back to MiMo on empty/unparseable response. MiMo content-filter rejection on fallback path explicitly surfaced as both-engines-failed error. 28 existing audit tests still pass after the swap."
W10-AUDIT-FOLLOWUP-COMMIT-POLICY,Process,When a followup commit lands the followup deserves its own audit pass,shipped,Claude,-,2026-05-25,"New --reaudit flag on scripts/audit_task_with_mimo.py + find_latest_commit_for_task(task_id, lookback=50) helper. Searches git log for the most recent commit whose subject contains task_id as a whole token (boundary rule: hyphen suffix OK so W10-CLI matches W10-CLI-TIMEOUT-BUDGET; bare alphanumeric suffix rejected so W10-FO does not match W10-FOO; pre-boundary alphanumeric/hyphen rejected so XW10-FOO does not match W10-FOO). 6 new tests: returns first match, returns None when no match, token boundary, hyphen suffix allowed, empty log, substring rejection."
2026-05-24T081155Z,Dispatch,Dispatch 2026-05-24T081155Z,shipped,Claude,-,2026-05-24,task=5b19fddc499749f7a01f52a11491aa9a; outcome=success
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
