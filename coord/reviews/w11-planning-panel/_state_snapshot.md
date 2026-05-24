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
