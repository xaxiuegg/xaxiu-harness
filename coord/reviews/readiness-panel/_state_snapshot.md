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
  panic-dump           Capture a secret-scrubbed snapshot of harness...
  preflight          
```

## `harness preflight --skip-engines` output

```
harness preflight — autonomous-mode readiness gate
============================================================
  [!] dead_engines         dead engines: anthropic:5, gemini:5  (18ms)
          fix: Inspect state/engine_performance_log.jsonl; rotate keys or quarantine the affected engine.
  [X] git_clean            modified tracked files present (3 entries)  (925ms)
          fix: Commit or stash before going autonomous.
  [OK] loops                dev loop task armed  (5160ms)
  [OK] observer             4 observer task(s) armed  (5140ms)
  [X] pytest_cache         last run had failures (lastfailed has 2 tokens)  (0ms)
          fix: Run pytest, fix failures, then retry preflight.
  [OK] status_csv           writable, last touched 0.3h ago  (0ms)
============================================================
  3 ok, 1 warn, 2 fail in 5161ms

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
  [OK] engine_reachability env=DEEPSEEK_API_KEY mimo=tokenplan
  [OK] env_var_inventory KIMI_API_KEY:SET, DEEPSEEK_API_KEY:SET, ANTHROPIC_API_KEY:UNSET, GEMINI_API_KEY:UNSET, MIMO_API_KEY:SET, OPENAI_API_KEY:UNSET
          fix: Set at least one engine API key in your environment
  [OK] coord_dir        coord/ is writable
  [OK] task_scheduler   Task Scheduler reachable
==================================================
overall: OK

```

## STATUS.csv (269 rows)

First 3 rows + last 5 rows:

```csv
ID,Category,Title,Status,Owner,Effort,Updated,Notes
W19-STATUS-TRACKER,Wave 5.5,Canonical STATUS tracker as harness primitive (src/harness/status/ + harness status CLI verbs),shipped,Kimi+Claude,~45 min,2026-05-21,Commit 514945f; hybrid Kimi-CLI partial + Claude inline; 305/305 tests; 90% coverage
W20-OBSERVER,Wave 5.6,Independent observer primitive (the check on dev-manager authority),shipped,Kimi via swarm,~60 min,2026-05-21,Kimi-CLI landed 6 module files (state/scheduler/cycle/audit_prompt/flags/__init__) + tests/test_observer.py (22KB; 41 tests) + cli.py observer group (12 subcommands) + manager.md Step 0 during 1200s timeout per feedback_kimi_cli_incremental_edits. Claude removed obsolete observer_tick stub test. 346/346 tests pass; 79% coverage on harness.observer.
...
2026-05-23T211152Z,Dispatch,Dispatch 2026-05-23T211152Z,shipped,Claude,-,2026-05-23,task=3b7ff9adcfcb49c8a8d7d886b7bc2b5d; outcome=success
2026-05-23T221153Z,Dispatch,Dispatch 2026-05-23T221153Z,shipped,Claude,-,2026-05-23,task=51e6315f0ba3496dbe8a6d49e2cbf802; outcome=success
2026-05-23T231152Z,Dispatch,Dispatch 2026-05-23T231152Z,shipped,Claude,-,2026-05-23,task=3a15eb3dbbac46169f249843f304bc28; outcome=success
2026-05-24T001152Z,Dispatch,Dispatch 2026-05-24T001152Z,shipped,Claude,-,2026-05-24,task=22a3b9aef3754187908cee5e1b770089; outcome=success
2026-05-24T011152Z,Dispatch,Dispatch 2026-05-24T011152Z,shipped,Claude,-,2026-05-24,task=91c63d4f9da247e0bc9488ecbd0ba679; outcome=success
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
