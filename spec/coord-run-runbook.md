# `harness coord` runbook — end-to-end walkthrough

Single document covering the planner → packet → dispatcher → worker →
integrator chain.  Written for an operator who has cloned the repo and
run `harness install` but never executed a coord run.

---

## 5-minute first coord run (offline, no API keys)

The fastest way to see the whole pipeline land a file on disk is the
MockEngine fixture used by [tests/test_coord_smoke_e2e.py](../tests/test_coord_smoke_e2e.py).
No external API keys required.

```powershell
# 1. Verify install
harness doctor                            # all checks green
harness session ok-to-stop                # expected: NOT-YET (you haven't done anything yet)

# 2. Lint the sample spec (catches obviously-empty/garbage specs)
harness lint-spec spec/samples/hello-world.md

# 3. Plan — produces runs/<run_id>/plan.json
harness coord plan --spec spec/samples/hello-world.md --engine mock

# 4. Inspect what was planned (without running)
harness coord run --spec spec/samples/hello-world.md \
                  --run-id <copy from step 3> \
                  --label first-run \
                  --dry-run

# 5. Actually run — workers dispatch to mock engine + apply edits
harness coord run --spec spec/samples/hello-world.md \
                  --run-id <copy from step 3> \
                  --label first-run

# 6. Live tail while it runs (open a second terminal)
harness coord watch --run-id <id>

# 7. After it finishes, verify
harness coord status --run-id <id>        # state: completed
harness coord list                        # this run shows up
```

If anything hangs see [§Recovery](#recovery).

---

## State machine

```
                ┌───────────────────────────────────────┐
                │                                       │
                │  spec.md   ──[planner]──► plan.json   │
                │                              │        │
                │                              ▼        │
                │   ┌────────  Coordinator.tick  ─────┐ │
                │   │                                 │ │
                │   │  state.PLANNING → RUNNING       │ │
                │   │                                 │ │
                │   │  for each task in plan:         │ │
                │   │    create_worktree              │ │
                │   │    run_worker (mock|kimi|...)   │ │
                │   │       └── progress.jsonl        │ │
                │   │       └── heartbeat sentinel    │ │
                │   │       └── FILE/REPLACE edits    │ │
                │   │       └── checkpoint.json       │ │
                │   │                                 │ │
                │   │  detect_stalled_workers         │ │
                │   │    └── L4 escalation if hung    │ │
                │   │                                 │ │
                │   │  all workers done?              │ │
                │   │    → state.INTEGRATING          │ │
                │   └────────────────┬────────────────┘ │
                │                    │                  │
                │                    ▼                  │
                │   harness coord integrate             │
                │     ├── merge worker branches         │
                │     │   (per WavePlan.strategy)       │
                │     ├── run pytest                    │
                │     ├── optional commit + push        │
                │     └── notify.json + webhook         │
                │                                       │
                └───────────────────────────────────────┘
```

Each phase mutates `runs/<run_id>/run_state.json`.  The state literal
walks `PLANNING → RUNNING → INTEGRATING → COMPLETED` (or `FAILED`).

---

## What lands where

| Artifact | Path | When |
|---|---|---|
| Plan | `runs/<id>/plan.json` | After `coord plan` (or `coord run` first tick) |
| Run state | `runs/<id>/run_state.json` | Mutated every `coord run` tick |
| Worker checkpoint | `runs/<id>/checkpoints/<wid>.json` | After each step + final |
| Worker progress | `runs/<id>/checkpoints/<wid>.progress.jsonl` | Step-level events (start/done) |
| Worker heartbeat | `runs/<id>/checkpoints/<wid>.heartbeat` | mtime updated each step boundary |
| Worker worktree | `.harness/worktrees/<id>/<wid>/` | Isolated git worktree per worker |
| Integrator notify | `runs/<id>/notify.json` | After `coord integrate` |
| Integrator webhook | `HARNESS_INTEGRATOR_WEBHOOK_URL` (env) | POST'd at integrate-time |

---

## Common failure modes + recovery

### Recovery

| Symptom | Likely cause | Fix |
|---|---|---|
| `coord plan` exits with "spec lint failed: E_EMPTY" | Spec file is empty/blank | Author the spec, OR `--skip-lint` (programmatic only) |
| `coord plan` exits with "adapter_load_failed" | `adapters/harness-planner/` missing | Re-run `harness install` |
| `coord run` reports L4 `stall` | A worker subprocess hung | `harness coord cancel --run-id <id>` then `coord retry --run-id <id> --worker-id <wid>` |
| `coord run` reports `kill_condition` triggered | YAML kill_conditions exceeded | Edit `operator.kill_conditions` in adapter YAML, `harness loop start` to re-arm |
| `dispatch` blocked with `packet_injection_blocked` | Packet content matched PACKET-INJECTION-FILTER | Review packet for secret-leak patterns OR set `HARNESS_ALLOW_UNSAFE_PACKETS=1` for explicit override |
| `dispatch` blocked with `packet_provenance_mismatch` | Spec was edited after `spec-register` | Re-register: `harness spec-register <spec>` then retry |
| Proxy key showing as quarantined | Auto-quarantine fired (3 flaps/hr) OR operator ran quarantine | `harness proxy unquarantine --alias <key>` or `--all` |
| Whole loop stopped | kill_conditions fired L4 | `harness loop start` re-arms; check `coord/dev_loop/escalations[]` |
| **"Everything is broken"** | Anything | `harness panic-dump` produces secret-scrubbed snapshot; paste path to Claude |

### Recovery verb cheat-sheet

```
harness session ok-to-stop      # is now a legitimate stop point?
harness panic-dump              # snapshot for Claude
harness coord cancel --run-id   # graceful stop of in-flight run
harness coord retry --worker-id # re-dispatch failed worker
harness coord replan --run-id   # plan again with failure feedback
harness coord rerun-failed      # chain replan + run + (optional integrate)
harness proxy unquarantine --all   # clear permanent quarantine
harness proxy reset-circuit <key>  # clear open circuit
harness loop start              # re-arm a stopped loop
harness state snapshot          # take db snapshot now
```

---

## Operator config that matters

Three sub-sections of the adapter `operator:` block change run behaviour:

```yaml
operator:
  session_handoff:               # SessionHandoffThresholds
    soft_mb: 8                   # informational
    strongly_mb: 18              # auto-write handoff_recommended.md
    critical_mb: 35              # halt + auto-write handoff_CRITICAL.md
  kill_conditions:               # KillConditions — loop hard-stops
    max_cost_usd: null           # e.g. 5.00 stops at $5 spend
    max_rows_dispatched: null    # e.g. 100 stops at 100 dispatches
    max_wallclock_minutes: null  # e.g. 180 stops after 3h
  production_hygiene_balance:    # ProductionHygieneBalance
    production_percent: 90       # creativity fires when below this
    hygiene_percent: 10          # must sum to 100
```

Defaults (no YAML override) preserve the values shown.

---

## Where to go from here

- [spec/multi-agent-harness-architecture.md](multi-agent-harness-architecture.md) — full v2 architecture
- [spec/operator-modes.md](operator-modes.md) — every adapter YAML key
- [spec/session-handoff-monitor.md](session-handoff-monitor.md) — when to start a fresh Claude session
- [coord/dev_loop/manager.md](../coord/dev_loop/manager.md) — autonomous loop per-tick procedure
- [coord/dev_loop/dispatch-rules.md](../coord/dev_loop/dispatch-rules.md) — engine routing + auto-fanout rule
