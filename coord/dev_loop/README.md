# coord/dev_loop — autonomous dev loop for xaxiu-harness

## Dual purpose

This directory serves two purposes simultaneously:

1. **Immediate**: drives autonomous development of xaxiu-harness itself. The dev manager loop (Claude main session) reads `state.json`, spawns supervisor sub-agents (Claude) for each phase, which in turn dispatch worker tasks to Kimi/DeepSeek via `xaxiu-swarm`.
2. **Prototype for Wave 6**: this is the working prototype of an "autonomous loops" feature that xaxiu-harness will eventually expose as a first-class user-facing capability. Users will be able to define loops + sub-loops in their adapter YAML, choose engines per sub-loop, and run them as Windows scheduled tasks or as `harness loop start <name>` invocations.

When editing files here, preserve patterns that generalize cleanly to the Wave 6 feature — the file structure here is the rough shape of what the harness will ship.

## Files

- `state.json` — shared loop state. Read by manager + every supervisor. Updated atomically.
- `manager.md` — prompt the dev manager (Claude main session) runs each `/loop` tick.
- `supervisors/creativity.md` — generates new feature ideas, refines specs, dreams up improvements. Runs at the slowest cadence (default 6h).
- `supervisors/developing.md` — dispatches code-writing packets to Kimi via xaxiu-swarm. Runs every ~30 min.
- `supervisors/testing.md` — runs pytest, identifies coverage gaps, dispatches test-writing packets. Runs every ~60 min.
- `supervisors/integrating.md` — merges completed Kimi outputs, runs validation, commits + pushes. Runs every ~20 min.
- `log.jsonl` — append-only event log per loop tick.

## Operator escalation

L5 errors halt all loops and surface to the operator. L1-L4 stay autonomous. See [reference_xaxiu_harness_error_taxonomy](https://github.com/xaxiuegg/xaxiu-harness/blob/master/coord/dev_loop/) (in operator's Claude memory).

## Engine routing defaults

| Phase | Default engine | Why |
|---|---|---|
| creativity | claude-in-session | Cheap, in-context, judgment work |
| developing | kimi (CLI) | Reliable multi-file Python editing |
| testing | kimi (CLI) | Same Python expertise, test scaffolding |
| integrating | claude-in-session | Git ops, conflict resolution, judgment |

Override per phase in `state.json::operator_directives.approved_engine_routing`.
