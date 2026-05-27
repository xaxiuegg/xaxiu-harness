# xaxiu-harness — agent reference

> Single source of truth for agentic coding agents (Claude, ChatGPT, Cursor, Aider, etc.) using xaxiu-harness as a sub-tool.
>
> If you're an operator running the harness yourself, you want [`OPERATOR_GUIDE.md`](OPERATOR_GUIDE.md) instead. This doc is for **another agent** (LLM-driven coding session) that wants to dispatch work to harness engines while preserving its own context window.

## 0. Orient yourself in two commands

After install, run these. They are the live truth — if anything in this doc contradicts them, trust the binary.

```bash
harness today           # shipped in last 24h + blockers + reachable engines + L5 events
harness capabilities    # SDK function list, CLI verb list, engine key presence, audit ledger path
```

Both are **introspection-only** — no engine dispatch, near-zero cost. Protected by a CI gate (`tests/test_docs_no_future_as_present.py`) so they never reference fictional verbs.

The W13-AUDIT-JSONL ledger at `~/.harness/audit.jsonl` records every dispatch with redacted prompt/response excerpts:

```bash
harness audit show --tail 20         # last 20 dispatch rows (redacted)
harness audit summary --since-hours 24
```

---

## 1. Install + verify

```bash
git clone https://github.com/xaxiuegg/xaxiu-harness.git
cd xaxiu-harness
pip install -e .          # or `pip install -r requirements.lock` for exact pins
```

Python 3.13+ recommended. 3.11 is the floor.

Verify cross-platform import works (P1 audit fix 2026-05-27 — this was broken pre-fix on Linux/macOS):

```bash
python -c "from harness.cli import cli; print('ok')"
```

If that prints `ok`, you can also call the CLI directly:

```bash
python -m harness --help
```

`python -m harness` is the universally-correct invocation form — `harness` (the .exe shortcut pip creates) sometimes isn't on PATH on Windows + Git Bash.

---

## 2. Set engine API keys

The SDK resolves keys in this order:

1. `os.environ[name]` — explicit (CI secrets, `export KEY=...`)
2. `.env` file in the project's `.harness/` parent dir
3. Windows DPAPI store (gracefully skipped on non-Windows)

For Linux / Mac / WSL agents, the simplest path is `.env`:

```bash
cat > .env <<'EOF'
KIMI_API_KEY=sk-...
DEEPSEEK_API_KEY=sk-...
MIMO_API_KEY=sk-...
EOF
```

You don't need all three. MiMo is the recommended starter (cheapest; subscription pricing with `tp-` keys).

Verify which keys are loaded without leaking values:

```bash
python -c "from harness.secrets.resolve import source_of; \
[print(f'{k}: {source_of(k)}') for k in ('KIMI_API_KEY','DEEPSEEK_API_KEY','MIMO_API_KEY')]"
```

Output is `env` / `dotenv` / `dpapi` / `missing` — never the key itself.

---

## 3. (Optional) Initialize the harness inside your own project

If you're using the harness inside *your* project rather than the harness repo itself:

```bash
harness agent init --target .
# or for a fresh directory:
harness agent init --target ./my-project --project-type python
```

Writes 7 files non-destructively: `.env`, `.gitignore`, `adapter.py`, `CLAUDE.md` (marker-gated append), `.harness/config.json`, `.harness/STATUS.csv`, `.harness/dispatched/.gitkeep`. Re-running is safe.

Cross-platform: Windows + Linux + macOS all work after the P1 fix (2026-05-27) that removed the import-time DPAPI guard.

For the harness repo itself, skip this step.

---

## 4. Dispatch your first prompt

```python
import harness

result = harness.dispatch("What model are you? Reply in one sentence.", engine="kimi")
print(result.summary)
# 'I am Kimi, a large language model developed by Moonshot AI.'

print(result.success)        # True
print(result.engine_used)    # 'kimi'
print(result.dispatch_id)    # 'cf922c67f58d45819620a566e8d0d10a'
print(result.tokens_in, result.tokens_out)   # 14 110
```

The default mode is **context-frugal**: `result.text` is `None` and only `result.summary` is populated (~300 chars). The full response stays in the dispatch cache for lazy retrieval.

This is the load-bearing design choice — your agent context grows ~36 tokens per dispatch instead of ~1500.

---

## 5. Lazy-fetch the full text when needed

```python
full_response = result.full()   # round-trips to cache, populates result.text
print(full_response)
```

Idempotent — second `.full()` is a near-zero local read.

Or retrieve by id later:

```python
body = harness.retrieve(result.dispatch_id, scope="full")
chunks = harness.retrieve(result.dispatch_id, scope="chunks", chunk_size_tokens=500)
```

---

## 6. Engine fallback chain

Pass a list of engines; the first available one is used:

```python
result = harness.dispatch(
    "complex task",
    engine=["kimi", "deepseek", "mimo"],
)
print(result.engine_used)        # whichever succeeded
print(result.fallback_chain)     # which engines were tried
```

---

## 7. Monitor your budget

```python
status = harness.budget_status()
print(status["offload_ratio"])           # 0.36 → 36% of work on subscription engines
print(status["remaining_budget_usd"])    # 4.41 → $4.41 of $5 cap left
print(status["engines_used"])            # {'kimi': 1353, 'deepseek': 2099, ...}
print(status["unpriced_dispatches"])     # 0 in steady state; >0 means meter undercounts
```

Cheap to call (~1KB payload); safe to poll between dispatches without blowing your context.

**`unpriced_dispatches`** (P3 audit fix 2026-05-27): non-zero means the budget meter is undercounting because some engine names aren't in the pricing table. Run `harness budget summary` to see which engines need a pricing-table entry.

Operator-readable variant from the CLI:

```bash
harness cost-today
# $0.2595 spent / $5.00 budget (today) - 2387 sub, 1693 paid (16% offload)  [ok]
```

---

## 8. The 3-engine cross-engine panel from your agent

When your agent hits a non-trivial decision and wants a second opinion:

```python
import subprocess

result = subprocess.run([
    "python", "-m", "harness", "ask",
    "should this side-project use sqlite or postgres? trade-offs?",
    "--no-save",  # or omit to keep coord/reviews/ output
    "--max-budget-usd", "0.50",
], capture_output=True, text=True, timeout=300)
print(result.stdout)
```

Or in shell-out form:

```bash
harness ask "your question" --output /tmp/panel
# then read /tmp/panel/packet.md for synthesis
```

Cost: ~$0.20-0.30 per 3-engine panel. Use sparingly — not every prompt needs this.

For empirical engine routing (which engine is best for what task):

```bash
harness engines recommend default   # → mimo-via-claude
harness engines recommend audit     # → deepseek-via-claude (v4-pro override)
harness engines recommend latency   # → deepseek-via-claude
```

Engine name goes to **stdout** (pipe-friendly); rationale goes to **stderr**.

---

## 9. Install the harness into your CLAUDE.md (agent-instructions)

If your agent runs in a session with its own `CLAUDE.md`, install the harness reference into it so the harness is discoverable on every future session:

```bash
# User-level (recommended — applies to every Claude Code session on this machine):
python -m harness install-agent-instructions

# Per-project:
python -m harness install-agent-instructions --target ./CLAUDE.md
```

This appends a marker-gated section (`<!-- W14-HARNESS-AGENT-INSTRUCTIONS-START -->` / `-END`) explaining where the harness lives, the four key verbs (`harness ask`, `harness doctor`, `harness engines recommend`, `harness keys serve`), when to reach for `harness ask` (high-stakes decisions, second opinion), and when NOT to (every prompt — it costs $0.20-0.30).

Idempotent. `--uninstall` removes cleanly. `--force` replaces a corrupted block.

Preview what gets installed:

```bash
python -m harness agent-instructions --format claude-md
```

Three formats available: `claude-md` (full section for CLAUDE.md), `prompt` (one-shot for new sessions), `short` (one-paragraph hint).

---

## 10. Multi-agent coordination (`harness coord`)

When your agent has a spec broken into 3-12 independent file-disjoint tasks and wants to fan out to multiple engines, use the v2 coord subsystem.

### 10.1 When to reach for coord

| Situation | Use this |
|---|---|
| One file, one engine, one prompt | `harness.dispatch()` (§ 4) |
| High-stakes decision, want 3 perspectives | `harness ask` (§ 8) |
| Spec with 3-12 independent tasks, want autonomous execution across multiple engines | `harness coord` (this section) |
| Long-running overnight batch work | `harness coord run --resume` |

Coord is overhead — spec writing + planner round-trip + worktree setup. Worth it for autonomous fanout; wasted for single-shot dispatches.

### 10.2 The subcommand surface

```
$ harness coord --help

Commands:
  plan                   Generate a WavePlan from a spec markdown file.
  plan-from-description  Generate a plan.json from a one-line description.
  run                    Execute a coordination run.
  work                   Worker entry-point — load plan, find task, run.
  status                 Show run state summary.
  watch                  Tail a running coord run and print events as they happen.
  list                   List runs/ with state + age + worker count.
  integrate              Integrate a completed run: tests, commit, push.
  retry                  Re-dispatch a failed worker from its last checkpoint.
  rerun-failed           Chain replan → run → (optional) integrate for a failed run.
  replan                 Re-run planner with failed-worker feedback.
  cancel                 Gracefully cancel an in-flight run.
  cleanup                Remove worktrees and run state for a completed run.
```

### 10.3 Typical workflow

```bash
# 1. Plan: turn a spec into a WavePlan JSON
harness coord plan --spec spec/wave-X.md
# → writes runs/<run-id>/plan.json (immutable after creation)

# 2. Run: dispatch workers in parallel git worktrees
harness coord run --spec spec/wave-X.md --max-workers 24

# 3. Watch (optional, in another terminal): tail events
harness coord watch --run-id <id>

# 4. Status: at any point, see the live state
harness coord status --run-id <id>

# 5. After all workers report success — integrate (merge worker branches)
harness coord integrate --run-id <id>

# Recovery paths:
harness coord retry        --run-id <id> --worker-id worker-3
harness coord replan       --run-id <id>  # planner sees failure context
harness coord rerun-failed --run-id <id>  # replan → run → integrate chain
harness coord cancel       --run-id <id>
harness coord cleanup      --run-id <id>  # drop worktrees + state
```

### 10.4 State on disk

```
runs/<run-id>/
├── run.json              # coordinator-owned overall state
├── plan.json             # planner output (immutable; replans → plan.v2.json)
├── checkpoints/
│   └── worker-N.json     # per-worker resume state (workers are idempotent)
└── deliverables/
    └── worker-N.json     # structured worker output

worktrees/<run-id>/
└── worker-N/             # git worktree on branch wt/<run>/<worker>
                          # workers never read/write the main checkout
```

Both `runs/` and `worktrees/` are gitignored.

### 10.5 Architecture invariants

From [`spec/multi-agent-harness-architecture.md`](../spec/multi-agent-harness-architecture.md):

- **Isolation over coordination**: each worker writes inside its own git worktree. Integration is a merge step run by the coordinator AFTER all workers report success. Eliminates the cli.py-collision class of failures hit five times in v1.
- **Statelessness per agent invocation**: every Kimi/Claude/MiMo call is one-shot. The agent has NO accumulated session history. Context rot disappears.
- **Structured handoffs**: all inter-component IPC is JSON validated against Pydantic schemas. Four schemas: `WavePlan`, `WorkerTask`, `WorkerResult`, `RunState`.
- **Circuit-breaking at the key level**: the 4-key proxy (`harness proxy start`) tracks per-key state and routes around unhealthy keys. Goal: 24 in-flight even when one key is in cooldown.

### 10.6 Programmatic invocation from your agent

For programmatic use, the verbs are all CLI-callable via `subprocess`. There is no Python API equivalent for `coord` today — it's CLI-only.

```python
import subprocess, json

# Plan
subprocess.run(["harness", "coord", "plan",
                "--spec", "spec/wave-X.md"], check=True)

# Run with progress callbacks via `coord watch`
import threading
def tail():
    subprocess.run(["harness", "coord", "watch", "--run-id", run_id])
threading.Thread(target=tail, daemon=True).start()
subprocess.run(["harness", "coord", "run", "--spec", "spec/wave-X.md",
                "--max-workers", "24"], check=True)

# Inspect state
status = subprocess.run(["harness", "coord", "status", "--run-id", run_id,
                         "--format", "json"],
                        capture_output=True, text=True, check=True)
state = json.loads(status.stdout)
```

If you find yourself writing a lot of `subprocess.run(["harness", "coord", ...])` from inside an agent, that's a signal to file an SDK row to surface coord in Python.

---

## 11. When something escalates (L5)

The harness uses a 5-level severity scheme (L1 INFO → L5 FATAL). Only L5 demands operator action.

When an L5 fires, your operator (or you, if you're driving the loop) sees this banner:

```
============================================================
L5 ESCALATION — L5.observer.OBSERVER_RESTART_LOOP
============================================================
observer scheduler restart failed 3 consecutive times — the watchdog
cannot self-recover

ACTION: Inspect scheduler manually: on Windows run
`Get-ScheduledTask -TaskName XaxiuHarnessObserver*`; on Linux/Mac
run `crontab -l | grep HARNESS_OBSERVER`. Then run
`harness observer install-scheduler` with elevated privileges if needed.

Evidence:
  - latest register message: PowerShell exit code 1
  - cadence: every 60 min
  - daily retro at: 23:00
============================================================
```

Visually distinct: 60-char border + `L5 ESCALATION` header + `ACTION:` callout + optional evidence block. Don't suppress these.

`harness today` always surfaces the last 24h of L5 events.

---

## 12. Anti-patterns

- **DO NOT** call `harness.dispatch(..., return_mode="full")` as your default — that's the legacy behavior; you'll burn ~750KB context across 30 dispatches. Use the default summary mode + `.full()` when needed.
- **DO NOT** save `result.text` to long-term memory if `result.text` is `None` — call `.full()` first.
- **DO NOT** dispatch to `--backend claude` (no cross-engine value + ANTHROPIC_API_KEY pollution; use Claude in-session instead).
- **DO NOT** bypass the budget cap silently — `COST_MAX_PER_SESSION` env override exists but escalates to L5 when exceeded.
- **DO NOT** assume `harness coord` is a heavyweight one-off — it's idempotent + resumable. Re-running after a worker fails is the design.

---

## 13. The API surface, briefly

```python
# harness/__init__.py re-exports (validated by tests/test_docs_mention_all_sdk_fns.py):
dispatch(prompt, engine=None, *, return_mode='summary', timeout_sec=420.0,
         with_full_text=False, no_cache=False) -> DispatchResult

retrieve(dispatch_id, scope='summary'|'full'|'chunks', *,
         chunk_size_tokens=2000, project_root=None) -> str | list[str]

budget_status(*, since_hours=None, ledger_path=None) -> dict
    # Includes `unpriced_dispatches` count (P3 audit fix 2026-05-27).

review(document_path, *, lens_set=None, max_tokens=None, quick=False,
       out_dir=None, max_concurrent=3, progress_cb=None) -> ReviewResult
    # Multi-engine document review.  lens_set=None auto-picks from
    # file extension (.py→code-review, .md/.pdf→doc-review, else 'default').

capabilities() -> dict
    # Cheap introspection.  Returns {version, python_version, platform,
    # sdk_functions, cli_verbs, review (lens_sets+supported_extensions+
    # default_max_tokens+quick_max_tokens), engines (configured+
    # keys_present), audit (ledger_path+max_age_days)}.

# DispatchResult attributes (context-frugal defaults):
.success       bool
.engine_used   str
.dispatch_id   str
.summary       str        # ~300 chars; always populated
.truncated     bool       # True when full text is in cache, not in .text
.text          str | None # None by default; .full() populates
.error_excerpt str | None
.content_ref   str | None
.tokens_in, .tokens_out, .cost_usd
.fallback_chain  list[str]

.full() -> str           # lazy round-trip to cache + retrieve()

# ReviewResult attributes:
.synthesis_path        str    # path to SYNTHESIS.md
.out_dir               str
.document_text_length  int
.elapsed_s             float
.total_cost_usd        float
.successful_lenses, .failed_lenses  int
.lens_set_used         str
.max_tokens_used       int
.lens_results          list[dict]

# Exceptions:
HarnessSDKError              # base
ResultNotFoundError          # dispatch_id has no cached body
ResultCorruptedError         # cached payload malformed
```

Type stubs live in `src/harness/__init__.pyi` for IDE autocomplete. A CI gate (`tests/test_docs_mention_all_sdk_fns.py`) fails the build if anything in `harness.__all__` is missing from this section.

---

## 14. Hallucination-resistance checklist

Before claiming a verb / SDK function / behavior exists, verify:

1. **Trust the binary, not the doc.** Run `harness capabilities` for the live SDK + CLI surface, or `harness <verb> --help` for verb-level signatures.
2. **Check STATUS.csv for shipped status.** Rows tagged `shipped` are done; `todo` / `in_progress` are not. Don't claim a `todo` row is shipped.
3. **Use `harness audit show`** to verify dispatch history, not memory of what you "think happened" earlier in the session.
4. **CI gates that already protect you**:
   - `tests/test_docs_no_future_as_present.py` — fails if a doc references a non-registered CLI verb
   - `tests/test_docs_mention_all_sdk_fns.py` — fails if `harness.__all__` adds a public name this doc doesn't mention
   - `tests/test_install_verify.py` — fails if `pip install -e .` doesn't produce a working `harness` console script with the public SDK importable

If you propose a behavior and a CI gate isn't covering it, that's a row worth filing.

---

## 15. Where to look next

| For | Read |
|---|---|
| Operator-facing setup, daily commands, recovery procedures | [`OPERATOR_GUIDE.md`](OPERATOR_GUIDE.md) |
| Handing the harness to someone else | [`HANDOFF.md`](HANDOFF.md) |
| Multi-agent coord architecture (full spec) | [`spec/multi-agent-harness-architecture.md`](../spec/multi-agent-harness-architecture.md) |
| Empirical routing data | [`spec/engine-routing-empirical.md`](../spec/engine-routing-empirical.md) |
| Error taxonomy (L1-L5) | [`spec/errors.md`](../spec/errors.md) |
| What's shipped / queued / in-flight | [`coord/STATUS.csv`](../coord/STATUS.csv) |
| Project memory + operator directives | [`CLAUDE.md`](../CLAUDE.md) |

---

*Updated 2026-05-27 (W14 docs consolidation 7→3). Update this file when the SDK surface, the `coord` subcommands, or `agent-instructions` install behavior changes.*
