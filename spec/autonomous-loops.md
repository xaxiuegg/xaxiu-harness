# Spec: autonomous loops (Wave 6)

## Goal

Productize the `coord/dev_loop/` prototype into a first-class harness feature. Users define autonomous development/operations loops per project in their adapter YAML, choose engines per sub-loop, and the harness runs them via Windows Task Scheduler (with cloud cron as a planned alternative).

## Reference implementation

`coord/dev_loop/` is the working prototype that develops xaxiu-harness itself. It demonstrates the full pattern: one manager + four supervisors (creativity, developing, testing, integrating) + worker engines + shared state file + escalation-with-auto-retry. Wave 6 generalizes this.

## Adapter YAML schema (new section)

```yaml
loops:
  <loop_name>:
    description: "<one line>"
    state_file: "coord/<loop_name>/state.json"
    tick_script: "bin/<loop_name>-tick.ps1"
    cadence_minutes: 30
    supervisors:
      <phase_name>:
        prompt_file: "coord/<loop_name>/supervisors/<phase>.md"
        engine: "kimi" | "deepseek" | "claude-in-session"
        model: null | "<model-id>"
        cadence_minutes: <int>
    escalation:
      level_threshold: "L5"        # only L5 surfaces to operator
      notification_method: "file" | "windows_toast" | "email"
      notification_target: "coord/<loop_name>/escalations.md"
    schedule:
      mechanism: "windows_task" | "cloud_cron"
      run_when_locked: true
      wake_to_run: true
```

## New CLI verbs (Wave 6)

| Verb | Behavior |
|---|---|
| `harness loop list` | Print configured loops + their armed/paused status + last tick time |
| `harness loop start <name>` | Register Task Scheduler entry (or cloud cron) and arm |
| `harness loop pause <name>` | Set `loop_status: operator_paused` in state |
| `harness loop resume <name>` | Set `loop_status: armed` |
| `harness loop status <name>` | Detailed view: phase cursors, escalations, recent log entries |
| `harness loop tick <name>` | Manual one-shot tick (for testing without waiting for cadence) |
| `harness loop logs <name> [--phase <p>] [--tail N]` | Read log.jsonl filtered/tailed |
| `harness loop escalations <name> [--clear <id>]` | Show or clear escalations |
| `harness loop uninstall <name>` | Remove Task Scheduler entry + leave state files for inspection |

## Module layout

```
src/harness/loops/
├── __init__.py
├── runner.py           # the tick orchestrator (replaces dev-loop-tick.ps1 logic)
├── supervisor.py       # base class + sub-agent invocation helpers
├── state.py            # atomic JSON I/O, schema validation, migration
├── escalations.py      # escalation lifecycle (raise, retry, resolve, notify)
├── scheduler/
│   ├── __init__.py
│   ├── windows_task.py # Register-ScheduledTask wrapper
│   └── cloud_cron.py   # /schedule routine wrapper (post-v1)
└── notifications/
    ├── __init__.py
    ├── file_based.py
    └── windows_toast.py
```

## Escalation model (carried from dev_loop prototype)

- **Never globally halt the loop.** Only specific phases pause via `phase_status: paused_by_escalation`.
- **Auto-retry with exponential backoff.** When `next_retry_at <= now`, the affected work is re-attempted. Success removes the escalation; failure increments backoff (1m → 5m → 15m → 1h, cap 4h).
- **Operator notification is informational, not gating.** The escalations file/toast tells the operator something needs their attention, but the loop continues retrying without manual intervention. When the operator fixes the underlying cause (e.g. rotates an API key), the next auto-retry simply succeeds.
- **L5 reserved for "operator must act AND retries cannot fix automatically"** — e.g. branch protection blocks the integrate phase entirely. Even L5 doesn't halt OTHER phases.

## Engine choice per supervisor

User picks the engine per phase in adapter YAML. Defaults from prototype:

| Phase | Default engine | Rationale |
|---|---|---|
| creativity | claude-in-session | judgment work, in-context |
| developing | kimi | reliable multi-file Python edits |
| testing | kimi | same Python expertise, test scaffolding |
| integrating | claude-in-session | git ops, conflict resolution |

User can override per-loop in their adapter YAML. The dispatcher in `engines/dispatcher.py` is the same one used for one-shot dispatches — supervisors call it via the same auto-fallback path.

## Migration from `coord/dev_loop/`

When Wave 6 ships, the existing `coord/dev_loop/` files become the seed for the first user of the feature (xaxiu-harness itself, self-developing). The migration:

1. Generate `loops.dev_loop` section in xaxiu-harness's own adapter YAML, derived from current state.json.
2. Move `coord/dev_loop/` to canonical location (TBD — `~/.harness/loops/<project>/dev_loop/` or stay project-local; operator chooses).
3. Replace `bin/dev-loop-tick.ps1` with `harness loop tick dev_loop`.
4. Re-register Task Scheduler entry to invoke the new CLI verb.

## Non-goals (post-v1)

- Distributed loops (one supervisor on master, another on a second machine)
- Cloud-only loops (zero local machine dependency)
- Real-time supervisor coordination (beyond shared state file)
- Visual loop config builder (Wave 5 covers this for adapters generally)

## Acceptance criteria for Wave 6

1. `harness loop start dev_loop` registers the scheduled task and the loop runs autonomously.
2. Adding a new supervisor to adapter YAML appears as a runnable phase without code changes.
3. Switching `developing.engine` from `kimi` to `deepseek` in YAML takes effect on next tick.
4. L5 escalations write to the notification target without halting the loop.
5. Existing `coord/dev_loop/` flow migrates without data loss.
6. Documentation in `docs/loops.md` covers user-facing config + troubleshooting.
