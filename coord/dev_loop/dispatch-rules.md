# Dispatch rules — engine routing for the autonomous loop

These rules are extracted from the operator's warehouse project retrospective (2026-05-20). They are load-bearing for the `developing` and `integrating` supervisors. Treat as the authoritative source of truth when packet drafting and dispatch decisions are made; if a supervisor's behavior conflicts with these rules, fix the supervisor.

## Three engine families

There are now THREE dispatch families:

1. **Swarm-based legacy** (`swarm/kimi`, `swarm/kimi-api`, `swarm/deepseek`) — the original xaxiu-swarm path documented in this file.  Active but allowlist-fragile for `kimi-api`.
2. **Swarm-based TOS-safe agentic** (`swarm/claude-mimo`, `swarm/claude-kimi`, `swarm/claude-deepseek` — W14-SWARM-CLAUDE-BACKENDS-VERIFIED 2026-05-26) — xaxiu-swarm dispatches through the local `claude-*` wrapper scripts.  Provides FULL agentic dispatch (tools enabled, multi-turn, in-place edits) via Claude Code's allowlisted UA.  Use this for agentic workloads on Kimi/MiMo/DeepSeek.
3. **Pattern B subprocess** (`kimi-via-claude`, `mimo-via-claude`, `deepseek-via-claude`) — single-inference programmatic dispatch via subprocess to local `claude` binary with `--tools ""`.  Use for panels, audits, FIND/REPLACE drafts, single-shot text generation.  Empirically benchmarked.  Routing rules + decision tree in **[spec/engine-routing-empirical.md](../../spec/engine-routing-empirical.md)**.

### Quick chooser

| Use case | Family | Example |
|---|---|---|
| Multi-file refactor / in-place edits | Swarm TOS-safe agentic | `xaxiu-swarm dispatch --backend claude-mimo ...` |
| Cross-engine ship audit (single text response) | Pattern B | `harness engines recommend audit` → use the recommended engine in code |
| Panel work / structured drafts | Pattern B | `kimi-via-claude` / `mimo-via-claude` / `deepseek-via-claude` |
| Interactive operator session | Wrapper script direct | `claude-mimo "your task"` |
| Legacy swarm/kimi-api / swarm/deepseek (existing scripts) | Swarm legacy | unchanged — works after 2026-05-26 Kimi restoration |

For Pattern B routing decisions in code, prefer the programmatic CLI:

```bash
harness engines recommend default     # → mimo-via-claude (most cases)
harness engines recommend latency     # → mimo-via-claude (9.3s avg)
harness engines recommend verbose     # → kimi-via-claude (elaboration)
harness engines recommend cost        # → kimi-via-claude (cheapest matrix)
harness engines recommend multimodal  # → mimo-via-claude (avoids WARN log)
harness engines recommend audit       # → deepseek-via-claude w/ v4-pro
```

The rest of this file documents the swarm-based dispatch path.  Both paths are active; choose the one that matches your packet shape.

## Engine selection (swarm path)

| Task shape | Engine | Model | Notes |
|---|---|---|---|
| Surgical FIND/REPLACE, single file, ≤40 LOC | Kimi CLI | default | Kimi-API also works if `--timeout >=420` |
| Multi-file Python implementation, single concern | Kimi CLI | default | Same domain only |
| V-file or context >500KB | DeepSeek | `deepseek-v4-flash` | 1M window required |
| Novel-feature drafting | DeepSeek | `deepseek-v4-flash` | Kimi consistently times out on novelty |
| Schema/math/logic verification | DeepSeek | `deepseek-v4-pro` | Reserve v4-pro for ship-blocking work; v4-flash for routine |
| Cross-engine ship audit | DeepSeek (vs prior Kimi work) or Kimi (vs prior DeepSeek work) | as above | Never the SAME engine that produced the artifact |
| Cross-engine ship audit (triangulation) | Gemini-2.5-pro | reserved for triangulation only | Use when both Kimi + DeepSeek already used; 2M-token window |

Never:
- Dispatch to Claude as a swarm worker (`--backend claude`). Use in-session Claude for judgment.
- Use Claude Agent-tool sub-agents for ship-gate audits. They share Claude's blind spots. Use the swarm cross-engine path.
- Bundle multi-domain work in one packet. Split by concern; dispatch separately.

## Timeouts and retries

| Backend | Packet shape | Minimum `--timeout` | Retry on timeout |
|---|---|---|---|
| `swarm/kimi` | Single-file surgical (≤40 LOC delta) | 420 | Fall back to `swarm/kimi-api` or `swarm/deepseek` immediately (per `[[reference_xaxiu_swarm_concurrency_calibration]]`); same-engine retry blocked 60min via `state.json::engine_cooldowns[swarm/kimi]` |
| `swarm/kimi` | Multi-file refactor / new module (≥200 LOC delta) | **1200** | Same fallback; partial files that landed BEFORE timeout per `[[feedback_kimi_cli_incremental_edits]]` are kept — re-dispatch only the unfinished portion |
| `swarm/kimi-api` | Single-file (NON-agentic; produces FIND/REPLACE response) | 420 | Same fallback rule |
| `swarm/deepseek` v4-flash | Single-file surgical | 600 | Fall back to v4-pro if recoverable, else `swarm/kimi` immediately (cooldown gates only same engine) |
| `swarm/deepseek` v4-pro | Complex / V-file / math | 1200 | Fall back to `swarm/kimi`; escalate L5 if both fail |

**Fallback ≠ retry.** Cooldown blocks the SAME engine from being re-dispatched; switching to an alternate engine is immediate (no delay). Observed warehouse policy `engine_slots.*.fill_policy = immediate_fallback`. Re-dispatching the engine that just timed out without cooldown is the failure mode this rule prevents.

**Key insight:** a swarm-reported "timeout" on `swarm/kimi` does NOT mean nothing landed. Empirically 9/29 = 31% of recent workers in this project (last 18 runs) tagged timeout while writes landed via incremental Edit/Write. Always run `bin/parse-swarm-status.py <output> --expect-edits-in <paths>` (or check `git diff` directly) to see actual file state before deciding retry vs partial-success. See [[feedback_kimi_cli_incremental_edits]] in memory.

Cooldown state lives in `state.json::engine_cooldowns[<engine>]`:
```json
{
  "last_failure_at": "<iso>",
  "failure_reason": "timeout|api_error|refusal|trap",
  "cooldown_until": "<iso, last_failure_at + 60min>"
}
```
Supervisors must check `cooldown_until` before dispatching; if the chosen engine is cooling, switch to the alternate.

## Required flags per dispatch

Every `xaxiu-swarm dispatch` invocation MUST include:
- `--backend <name>`
- `--deliverable <project root>` (so worker writes back to the right place)
- `--add-dir <project root>` (so worker can read project files)
- `--context-file D:/Projects/xaxiu-harness/CLAUDE.md` (memory + conventions)
- `--progress 30` (heartbeat for long runs)
- `--timeout <per-table-above>`

For DeepSeek surgical patches (FIND/REPLACE without investigation), also pass `--no-thinking` to avoid the v4-pro "thinking eats the output budget" trap.

## Packet scope validation (pre-dispatch checklist)

Before dispatching, the developing supervisor MUST confirm the packet:
- [ ] Touches a single domain (single module or tightly-related sibling files)
- [ ] Has explicit acceptance criteria listing concrete artifacts (file paths, function names)
- [ ] For surgical patches: includes verifiable anchors (3+ lines of unchanged context around each FIND block)
- [ ] Specifies output format unambiguously (e.g. "FIND/REPLACE blocks" vs "complete file rewrite")
- [ ] References the relevant CLAUDE.md sections, memory entries, or spec files by path

If any check fails, the packet is split or revised before dispatch. Vague packets are the #1 cause of engine hallucination.

## Post-dispatch verification (before integrating)

The integrating supervisor MUST run these gates IN ORDER. Stop at first failure.

1. **`git diff --stat`** — refuse to integrate single-file diffs >1500 LOC without explicit `confirm_large_diff: true` on the merge entry.
2. **Anchor byte-verification** — for surgical patches, the developing supervisor must have verified that all FIND blocks match source exactly. If not done, integrating supervisor reruns the check.
3. **`pytest tests/ -q`** — full suite must be green. If newly failing, classify as regression and block.
4. **CLI smoke test** — for verbs the wave affected, `harness <verb> --help` must succeed.
5. **Cross-engine audit (optional, ship-gate only)** — for waves marked `ship_blocking: true`, dispatch a verification packet to the alternate engine. Both must concur before integrate.

## Observer-flagged anti-patterns (do NOT repeat)

From warehouse `dev-panel-runs/.../observer/daily/`:
- **REV 202 Babel TDZ crash shipped undetected** — never claim "live" without a curl smoke test confirming the artifact loads and renders.
- **`planner.html` race condition** — never run two supervisors simultaneously that write to the same file. The dev manager enforces one-supervisor-per-tick.
- **Same-engine ship-audit** — never dispatch a Claude-sub-agent to validate Claude's own work, OR a Kimi packet to validate a Kimi-authored patch. Cross-engine only.

## Engine slot policy (don't let cheap engines sit idle)

| Engine | max_parallel | fill_policy | Why |
|---|---|---|---|
| `swarm/kimi` (xaxiu-swarm wrapping Kimi-Code CLI subprocess) | 6 | aggressive | Subscription-cost; cheap to keep busy. Empirical ceiling from warehouse calibration 2026-05-20 (`reference_xaxiu_swarm_concurrency_calibration`). |
| `swarm/kimi-api` (REST) | 6 (up to 18 with 3-key pool) | aggressive_overflow | Same provider, different transport; use when CLI slots full and task is REST-friendly. 3-key pool × 6 = 18 confirmed. |
| `swarm/deepseek` (v4-flash/pro) | 1 | on_demand | Per-API cost; only dispatch when task needs DeepSeek's strengths. |

Defaults live in `src/harness/operator/modes.py::DEFAULT_ENGINE_SLOTS` — adapter YAML overrides via `operator.engine_slots`.

## Auto-fanout — split before dispatch (2026-05-21)

A packet is a single Kimi worker's contract. When the contract is too
broad, the worker times out, returns truncated edits, or silently drops
symbols. Empirical rate from 2026-05-21 telemetry: supervisors-coverage
needed 3 retries (761df48 / 5a77137 / 3b4ab7b); V2-FIRST-RUN caught 4
production gaps that should have been separate scoped waves.

**Hard rule** — split the packet into N siblings dispatched via
`xaxiu-swarm swarm --max-concurrent N` when ANY of the following is true:

| Signal | Threshold |
|---|---|
| Expected edited LOC (counting new files) | > 500 |
| Distinct top-level symbols (`def` / `class` count) | > 2 |
| Distinct top-level files touched (excluding tests) | > 3 |
| Test files added | > 1 |

**Soft rule** — consider splitting also when:
- The packet spans more than one module directory.
- The packet asks for both a schema change AND a wiring change.
- The packet would touch `src/harness/cli.py` (conflict hotspot — see
  `CLI-DECOMPOSE` row in STATUS.csv).

Splitting beats retrying. 3 narrow packets in parallel beat 1 wide
packet that times out at 420s.

After supervisors return diffs in a tick, the manager runs slot-fill (see `coord/dev_loop/manager.md` slot-filling section):
1. Count `engine_slots.kimi.in_flight`. If `< max_parallel`, find queued waves with deps met whose file scopes don't overlap any in-flight dispatch. Dispatch each via `xaxiu-swarm dispatch --backend kimi ...` (or `xaxiu-swarm swarm` for a batch).
2. If `kimi` slots are full and more eligible work exists, dispatch overflow to `kimi-api`.
3. Never auto-fill DeepSeek slots from slot-fill — that's reserved for explicit supervisor requests per engine-strength routing.

**Conflict-avoidance for parallel Kimi dispatches:**
- Two parallel dispatches MUST touch disjoint file sets. Compute "files claimed" per packet (read the packet's Scope section) before dispatch.
- Cross-file refactors (e.g. "rename X across all uses") must stay as ONE dispatch.
- Sub-waves naturally split: e.g. Wave B has two natural halves (engines/concrete tests + engines/guards tests) — dispatch as 2 packets in parallel if no shared fixture work.

## Wave-splitting heuristics

When a wave touches N independent modules, split into N packets and fan out:
- Per-module isolation: each Kimi worker gets ONE module + its existing test file
- Per-feature isolation: distinct CLI verbs or distinct engine adapters split cleanly
- Anti-pattern: do NOT split a single function's refactor across workers; the cross-cutting changes will conflict

## Multi-packet dispatch — prefer `xaxiu-swarm swarm` over N `dispatch` calls

When dispatching ≥2 packets in parallel, use the `swarm` subcommand, not multiple `dispatch` invocations:

```
xaxiu-swarm swarm \
  --backend swarm/kimi \
  --max-concurrent 3 \
  --timeout 600 \
  --add-dir D:/Projects/xaxiu-harness \
  --context-file D:/Projects/xaxiu-harness/CLAUDE.md \
  packet1.md packet2.md packet3.md
```

Or, route different packets to different backends in one call:

```
xaxiu-swarm swarm \
  --backends "swarm/kimi,swarm/kimi-api,swarm/deepseek" \
  --max-concurrent 3 \
  packet1.md packet2.md packet3.md
```

Why `swarm` over multiple `dispatch`:
- Single audit run-id ties all related workers together for forensics
- `--max-concurrent` lets the slot policy be enforced inside swarm
- `--heartbeat` gives liveness signals across the fleet
- Shared `--context-file` is inlined once per worker, not duplicated by the caller

Use `dispatch` (singular) only for: one-off ad-hoc work, smoke tests, or when you need backend-specific flags swarm doesn't expose.

## When to escalate

| Condition | Level | Notes |
|---|---|---|
| Same wave fails on both engines 3 retries each | L5 | `L5.dispatch.E_WAVE_PERSISTENTLY_FAILING` |
| All engines in cooldown simultaneously | L5 | `L5.network.E_ALL_ENGINES_UNREACHABLE` |
| `pytest` red, regression introduced, fix unclear after one retry | L4 | `L4.testing.E_REGRESSION_PERSISTENT` |
| Anchor verification fails after engine fallback | L3 | Re-draft packet, dispatch fresh |
| Single engine timeout, fallback succeeded | L1 | Logged, no action |
