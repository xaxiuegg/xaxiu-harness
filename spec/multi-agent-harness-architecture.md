# Multi-Agent Harness Architecture (v2 — Planner/Worker + Worktrees + Stateful Proxy)

> Operator brief 2026-05-21: 4 Kimi-API keys → 24 concurrent slots. Need a
> Planner/Worker pattern with isolated git worktrees, a stateful API proxy
> with circuit-breaking, and JSON-based structured handoffs. Goals:
> minimize context rot, maximize parallel throughput, resume from checkpoints.

This spec is the v2 evolution of `xaxiu-harness`. v1 (this session) is an
in-session Claude dev-manager hand-routing work to a small pool of Kimi
agents via markdown packets. v2 moves orchestration out of any single
Claude session, normalizes the IPC, and scales to the full 24-slot pool.

---

## 1 — Component map

```
                    +--------------------+
                    |     Coordinator    |  Process A (long-running daemon
                    | runs.json + locks  |  or invoked per-run; no model)
                    +----------+---------+
                               |
                  spawn        |       integrate
                  workers      |       results
                               v
       +-----------+-----------+-----------+-----------+
       |           |           |           |           |
       v           v           v           v           v
  +---------+ +---------+ +---------+ +---------+ +---------+
  | Planner | | Worker1 | | Worker2 | | Worker3 | | WorkerN |   (each in
  | (one    | | (Kimi)  | | (Kimi)  | | (Kimi)  | | (Kimi)  |   own worktree
  | -shot   | +----+----+ +----+----+ +----+----+ +----+----+   + own ctx)
  | Claude  |      |           |           |           |
  | or Kimi)|      v           v           v           v
  +----+----+   +----------------------------------------+
       |        |        Stateful API Proxy              |
       |        |  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐       |
       |        |  | K1  | | K2  | | K3  | | K4  |       |
       |        |  |6/6  | |3/6  | |0/6  | |6/6  |       |
       |        |  └─────┘ └─────┘ └─────┘ └─────┘       |
       |        |  Health: closed/half-open/open         |
       |        +----------------------+-----------------+
       |                               |
       +---------- WavePlan JSON ------+
                  WorkerTask JSON      |
                  WorkerResult JSON    v
                                  Kimi Moonshot API
```

Five components, four cross-process contracts (JSON), one shared state
file (`runs/<run_id>/run.json`).

---

## 2 — The four core principles

### 2.1 Isolation over coordination

Each worker writes inside its own git worktree at `worktrees/<run_id>/<worker_id>/`.
Workers never read or write the main checkout. Integration is a merge
step run by the coordinator AFTER all workers report success.

Eliminates the `cli.py`-collision class of failures we hit five times
in v1. No file is ever held by two workers simultaneously.

```
.harness/
├── runs/
│   └── 2026-05-21T04-13-bf9a/
│       ├── run.json              # overall run state (coordinator-owned)
│       ├── plan.json             # planner output (immutable after creation)
│       ├── checkpoints/
│       │   ├── worker-1.json     # per-worker resume state
│       │   ├── worker-2.json
│       │   └── ...
│       └── deliverables/
│           ├── worker-1.json     # structured worker output
│           └── ...
└── worktrees/
    └── 2026-05-21T04-13-bf9a/
        ├── worker-1/             # git worktree, branch wt/<run>/<worker>
        ├── worker-2/
        └── ...
```

### 2.2 Statelessness per agent invocation

Every Kimi/Claude call is a one-shot: prompt → response → exit. The
agent has NO accumulated session history between tasks. Context rot
disappears because there is no rotting context — each call starts fresh.

Long-running agentic behavior is rebuilt at the coordinator layer
through structured checkpoints, not by keeping a model warm.

### 2.3 Structured handoffs

All inter-component IPC is JSON validated against Pydantic schemas.
Freeform markdown packets become an INPUT to the planner — they may
exist as operator-readable specs — but every cross-process artifact is
typed JSON. Re-parsing failures are L4 schema violations, not "the
model emitted prose, hope for the best."

Four schemas (defined in §4):
1. `WavePlan` — planner output
2. `WorkerTask` — one row in the plan, given to one worker
3. `WorkerResult` — worker output (success/failure + deliverables)
4. `RunState` — coordinator's running view of the whole run

### 2.4 Circuit-breaking at the key level

The 4 API keys are not interchangeable — each carries its own per-IP
rate limits and recent-failure history. The proxy tracks per-key
state and routes around unhealthy keys. Goal: 24 in-flight at the
pool level even when 1 key is in cooldown.

---

## 3 — Per-component design

### 3.1 Coordinator (`harness coord`)

**Role**: orchestrate a run from start to finish.

**Invocation**:
```bash
harness coord run \
    --spec spec/wave-X.md            \
    --max-workers 24                 \
    --planner-engine claude          \
    --worker-engine swarm/kimi-api   \
    --resume                         # picks up runs/<latest>/run.json if present
```

**Loop** (mirrors `harness.loops.runner.tick` but multi-tick):
1. Acquire `runs/<run_id>/run.lock` (fcntl/PIDLock).
2. Load `run.json` or create from spec.
3. If `plan.json` missing → invoke Planner (§3.2).
4. For each `WorkerTask` in plan with state ∈ `{pending, partial}`:
    - Ensure worktree exists (create if not).
    - Read `checkpoints/<worker>.json` to determine resume point.
    - Launch worker (§3.3) with stdin = `WorkerTask` + `resume_from` context.
5. Poll workers via `psutil` + checkpoint mtimes; stale workers (no
   mtime update in 5min AND no in-process indicator) → restart.
6. When all workers report `state="completed"` → invoke Integrator (§3.5).
7. Release lock; write final `run.json` state.

**Resume**: any restart re-enters step 1; the lock guards against
concurrent coordinators on the same `run_id`. Workers are idempotent
within their own worktree (see §3.3).

### 3.2 Planner (`harness coord plan`)

**Role**: take a spec + current repo state, output a `WavePlan` with
N independent `WorkerTask` entries.

**One-shot**: planner runs once per run. If the plan turns out to be
wrong mid-run (worker fails with `needs_replan: true`), the coordinator
calls planner again with the failure context.

**Prompt template** (planner sees this — JSON-output enforced):

```
SYSTEM: You are the planner for a multi-agent dev harness. Given the
spec below, decompose into 1-12 independent worker tasks. Each task
must touch a disjoint set of files (you will list them in `write_set`).
Tasks may declare dependencies via `depends_on`. Emit a single JSON
object matching the WavePlan schema. No prose, no commentary.

SPEC:
<<<spec markdown here>>>

REPO INVENTORY (file paths + sizes):
<<<truncated tree>>>

Emit JSON.
```

**Output**: `plan.json` (immutable after creation; replans become
`plan.v2.json`, etc.).

**Engine choice**: Claude for first plan (judgment), Kimi for cheap
replans.

### 3.3 Worker (`harness coord work`)

**Role**: execute one `WorkerTask` inside its worktree, write a
`WorkerResult` JSON, exit.

**Invocation** (one-shot per worker; the coordinator re-invokes on
each tick if work remains):
```bash
harness coord work \
    --run-id <id> --worker-id worker-3 \
    --task-json runs/<id>/plan.json#tasks[2] \
    --resume-from runs/<id>/checkpoints/worker-3.json
```

**What happens inside**:
1. `cd worktrees/<run>/worker-3`
2. Read `task-json` → `WorkerTask`
3. Read `resume-from` if present → continue from `last_completed_step`
4. For each step in `task.steps`:
    a. Build a fresh prompt with ONLY the files in `task.read_set`
       (no full-repo dump, no chat history).
    b. Call the proxy (§3.4) to dispatch one Kimi call.
    c. Parse response. Apply edits via patch (typed FILE/REPLACE
       blocks, not free-form output).
    d. Write checkpoint: `{last_completed_step, files_modified,
       tests_passed, elapsed_seconds}`.
    e. Run `pytest` over `task.test_set` only (worker doesn't
       know about other workers' tests).
5. If all steps done → emit `WorkerResult{state="completed",
   files_modified, commit_sha (worker's own commit on its branch),
   test_summary}`.
6. If a step fails → emit `WorkerResult{state="failed",
   failed_step, error_tag, needs_replan: <bool>}`.
7. Exit.

**Context budget**: each step's prompt MUST fit in 30k tokens. The
planner is responsible for sizing steps small enough. If a worker
detects context overflow at runtime, it emits `needs_replan: true`
with the offending step.

**Idempotence**: the worker can be killed at any point and restarted
by the coordinator; the checkpoint tells it where to resume.

### 3.4 Stateful API Proxy (`harness coord proxy`)

**Role**: interpose between every Kimi/Claude API call and the actual
API endpoint. Routes across 4 keys with circuit-breaking. Persists
state so it survives proxy restarts.

**Why a proxy, not just a router function**: workers are independent
processes. They cannot share an in-memory routing table. Either every
worker re-reads a global state file (race-prone) OR a single proxy
process owns the state. The proxy is one Python process listening on
`localhost:7879`, exposing the OpenAI-compatible API surface that
Kimi-API expects.

**Per-key state** (persisted to `.harness/proxy_state.json`):

```json
{
  "k1": {
    "key_alias": "moonshot-k1",
    "in_flight": 6,
    "max_concurrent": 6,
    "circuit_state": "closed",          # closed|half_open|open
    "recent_outcomes": ["success", "success", "timeout"],
    "consecutive_failures": 0,
    "cooldown_until": null,             # iso8601 when circuit_state == open
    "total_dispatched": 1247,
    "total_failed": 23,
    "avg_latency_ms": 14200,
    "last_used_at": "2026-05-21T04:14:01Z"
  },
  "k2": { ... },
  "k3": { ... },
  "k4": { ... }
}
```

**Routing algorithm** per inbound request:
1. Pool = keys with `circuit_state ∈ {closed, half_open}`.
2. Filter `in_flight < max_concurrent`.
3. Sort by `in_flight` ascending, then `avg_latency_ms` ascending.
4. If pool empty → return `L4.network.E_ALL_KEYS_SATURATED` (worker
   should backoff + retry; this is NOT failure, it's slot
   contention).
5. Pick top key, increment `in_flight`, forward request.

**Circuit-breaker state machine** (per key):

```
[closed] --on N consecutive failures--> [open]
   ^                                       |
   |   on first success after cooldown     | wait `cooldown_seconds`
   |                                       v
[half_open] <--single test request------ [open]
```

- `closed` → normal routing.
- `open` → never routed; cooldown timer.
- `half_open` → exactly ONE in-flight allowed; success → closed, fail → open.

**Failure classification** (which outcomes trip the breaker):
- HTTP 401, 403 → `auth_failure` → open immediately (key is bad)
- HTTP 429 → `rate_limit` → half_open after 60s cooldown
- HTTP 5xx → `server_error` → half_open after 30s cooldown
- Timeout (> packet timeout) → `timeout` → half_open after 60s
- Schema/refusal (200 OK but bad content) → does NOT trip breaker
  (per-key issue ≠ per-request issue)

**Smoothing**: only `consecutive` failures trip; `total_failed`
without consecutive is informational only.

**Operator CLI**:
```
harness proxy start [--port 7879]
harness proxy stop
harness proxy status                   # per-key health table
harness proxy reset-circuit <key_alias>
harness proxy quarantine <key_alias>   # force open, no auto-recovery
```

### 3.5 Integrator (`harness coord integrate`)

**Role**: merge all worker worktrees back to the main checkout,
run final pytest, commit, push.

**Algorithm**:
1. Read `WorkerResult` for every worker.
2. If any failed → write `run.json::state = "failed"`, exit; do NOT
   merge.
3. For each worker in dependency order:
    a. `git fetch <worktree>` → fetch the worker's branch into main.
    b. `git merge --no-ff <worker-branch>` — may conflict (rare;
       planner is supposed to ensure disjoint write_sets, but
       integrator validates).
    c. On conflict → `git merge --abort`, write failure JSON,
       surface as `L4.integration.E_UNEXPECTED_CONFLICT` to
       coordinator. Coordinator decides: replan or operator escalate.
4. Run full `pytest`.
5. If green: commit (single squash commit or N-commit fast-forward,
   depending on `integrate_strategy`).
6. Push.
7. Tear down worktrees.

**Safety**: Integrator runs with `HARNESS_ALLOW_AUTO_INTEGRATE`
required (env var, default false). Without it, integrator stops at
step 5 and writes a "ready to commit" report for operator review.

---

## 4 — JSON schemas

### 4.1 `WavePlan`

```python
class WavePlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str = Field(pattern=r"^\d{8}T\d{6}-[a-z0-9]{4}$")
    spec_path: str
    created_at: str
    planner_engine: Literal["claude", "kimi", "kimi-api", "deepseek"]
    planner_model: str | None = None
    tasks: list[WorkerTask]
    integration_strategy: Literal["squash", "merge", "rebase"] = "squash"
    notes: str = ""
```

### 4.2 `WorkerTask`

```python
class WorkerTask(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str = Field(pattern=r"^worker-\d+$")
    title: str
    description: str            # 1-3 sentences max
    read_set: list[str]         # file paths the worker may READ
    write_set: list[str]        # file paths the worker may WRITE (planner enforces disjointness)
    test_set: list[str]         # pytest paths for the worker's local validation
    depends_on: list[str] = Field(default_factory=list)  # other worker_ids
    steps: list[WorkerStep]     # ordered, atomic, individually-checkpointable
    estimated_kimi_minutes: int = 10
    max_context_tokens: int = 30000
```

### 4.3 `WorkerStep`

```python
class WorkerStep(BaseModel):
    model_config = ConfigDict(extra="forbid")
    step_id: str
    kind: Literal["edit", "create", "delete", "test", "shell"]
    instruction: str            # what the model should do this step
    target_files: list[str]     # subset of write_set
    expected_diff_lines: int    # planner's estimate (worker validates)
    required_tests: list[str] = Field(default_factory=list)
```

### 4.4 `WorkerResult`

```python
class WorkerResult(BaseModel):
    model_config = ConfigDict(extra="forbid")
    worker_id: str
    run_id: str
    state: Literal["completed", "failed", "needs_replan", "in_progress"]
    started_at: str
    finished_at: str | None
    steps_completed: list[str]  # step_ids
    files_modified: list[str]
    test_summary: TestSummary
    commit_sha: str | None      # worker's branch HEAD
    error_tag: str | None       # L<n>.<domain>.<code> if state=="failed"
    diagnostic: str = ""
    tokens_used: int = 0
    elapsed_seconds: int = 0
```

### 4.5 `RunState` (coordinator's view)

```python
class RunState(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    spec_path: str
    state: Literal["planning", "running", "integrating", "completed", "failed", "paused"]
    plan_path: str              # runs/<id>/plan.json
    started_at: str
    last_tick_at: str
    workers: dict[str, WorkerStatus]   # worker_id -> live status
    integrator_status: IntegratorStatus | None = None
    escalations: list[Escalation] = Field(default_factory=list)
```

---

## 5 — Context-rot mitigation rules

1. **Per-step context cap**: every model call ≤ 30k tokens of prompt.
   Planner subdivides steps that exceed this.
2. **No accumulated history**: every model call starts from blank;
   prior step results are passed forward only as small structured
   summaries in the next prompt, NOT as conversation history.
3. **read_set is the budget**: a worker may read ONLY the files
   declared in `read_set` (enforced at the prompt-builder layer).
   The planner is responsible for setting read_set minimally.
4. **Diff verification**: after each step, worker computes
   `len(diff_lines)` and compares against `expected_diff_lines`. If
   off by >50%, the worker stops + marks `needs_replan`.
5. **No "go ask the user" fallbacks** in worker prompts. Workers
   must complete or fail with a structured error. Coordinator
   handles operator surfacing.

---

## 6 — Resume from checkpoints

Every layer writes a checkpoint:

| Layer | Checkpoint file | Triggers |
|---|---|---|
| Coordinator | `runs/<id>/run.json` | every tick + every state transition |
| Worker | `runs/<id>/checkpoints/worker-N.json` | after every step |
| Proxy | `.harness/proxy_state.json` | after every routing decision (debounced 5s) |

**Restart behavior**:
- Coordinator: `harness coord run --resume` loads run.json, restarts
  workers whose state ∈ `{partial, in_progress}` from their checkpoints.
- Worker: on launch, reads checkpoint → starts from `last_completed_step + 1`.
- Proxy: on launch, loads proxy_state.json; `in_flight` counts get
  reset to 0 (true in-flight requests are gone) but `circuit_state`,
  `consecutive_failures`, `cooldown_until` persist (the failure
  signal that opened the breaker is real even after restart).

---

## 7 — Failure modes + recovery

| Class | Example | Handler |
|---|---|---|
| Single API timeout | Kimi-API call exceeds packet timeout | Proxy trips half_open; worker retries via another key |
| Single key auth fail | API returns 401 | Proxy opens that key permanently; alerts coordinator |
| All 4 keys saturated | 24 in-flight slots all busy | Worker backs off (60s), proxy returns slot-contention error |
| Worker stuck | No checkpoint mtime update >5min | Coordinator kills + restarts from last checkpoint |
| Worker dies on context overflow | Pre-flight check fails | Worker emits `needs_replan`, coordinator re-invokes planner with overflow info |
| Integrator merge conflict | Planner mis-estimated write_sets | Coordinator rolls back merge, marks `L4.integration`, requests replan |
| pytest red on integration | Cross-worker regression | Coordinator marks `L4.testing`, surfaces failing tests; no commit |
| Proxy crashes | Network restart, OS update | Coordinator detects via missing PID; restarts proxy + replays in-flight workers from their checkpoints |
| Coordinator crashes | OS crash / power loss | `harness coord run --resume` recovers from run.json + checkpoints |
| All 4 keys quarantined | All keys exhausted/banned | L5; operator action: rotate keys via `harness env --reset` |

---

## 8 — Performance budget (the 24-slot math)

- 4 keys × 6 concurrent = 24 slots
- Avg Kimi call latency this session: ~15s (observed in the proxy
  state above; varies 10-25s)
- Steady-state throughput: 24 / 15s = **1.6 dispatches/sec sustained**
- 1-hour wall-clock = ~5,760 dispatches = ~5,760 × 30k tokens
  ≈ 173M input tokens × $0.15/M = **$26/hr at peak load**
- Realistic with circuit-breaker disruptions, planner waits,
  integration cycles: **~60% of peak = $15/hr**

Compare v1 (this session, hand-routed): ~10 dispatches over 4 hours
= 0.0007 dispatches/sec — three orders of magnitude lower. v2 doesn't
just unlock parallel headroom; it changes the cost model.

Operator-controllable knobs (env / adapter YAML):

```yaml
coord:
  max_workers: 24                          # full pool default
  worker_engine: swarm/kimi-api            # 4-key proxy backend
  planner_engine: claude                   # one-shot Claude per plan
  context_rot_token_cap: 30000             # per-step prompt budget
  worker_step_timeout_seconds: 300         # individual step max
  worktree_root: .harness/worktrees        # where worktrees live
  integration_strategy: squash             # squash | merge | rebase
  allow_auto_integrate: false              # operator gates the merge
proxy:
  port: 7879
  state_path: .harness/proxy_state.json
  circuit:
    open_after_consecutive: 3
    half_open_cooldown_seconds: 60
    auth_failure_permanent: true
  routing:
    strategy: least_loaded                 # least_loaded | round_robin | random
```

---

## 9 — Roadmap to ship v2

Estimated ~8-12 multi-hour Kimi-CLI dispatches OR ~3-4 days of inline
Claude work. Split into 4 sub-waves to fit Kimi's 1200s per-dispatch
budget:

| Sub-wave | Scope | Estimated agents |
|---|---|---|
| v2/A | Proxy module + state schema + 4-key routing + circuit breaker | 2 (proxy.py + tests) |
| v2/B | WorkerTask/WavePlan/WorkerResult JSON schemas + planner module | 2 (schemas + planner) |
| v2/C | Worker module + worktree management + checkpoint writer | 3 (worker.py + worktree.py + checkpoint.py) |
| v2/D | Coordinator + integrator + CLI (harness coord run/plan/work/integrate) | 4 (orchestrator + integrator + CLI + tests) |

Each sub-wave can use ~6 parallel Kimi workers via the existing
swarm subcommand — so v2/A through v2/D realistically lands in
~4 hours of clock time if all parallel slots fire cleanly.

Bootstrapping problem: v2 is built BY v1. The first iteration of v2
uses v1's hand-coordinator (Claude in-session) + Kimi via the new
proxy (which we built in v2/A). Once v2/D ships, v2 starts building
itself, with v1 demoted to "human override mode."

---

## 10 — What v2 explicitly drops vs v1

- **No more markdown packets as IPC.** Markdown specs are still
  human-authored input, but the coordinator's planner immediately
  converts them to `WavePlan` JSON. Cross-process talk is JSON.
- **No more "same Kimi session does N things in sequence."** Every
  step is a fresh call. Long-running agentic loops happen at the
  coordinator level via checkpoints, not in-model.
- **No more cli.py serialization.** Worktrees solve it.
- **No more 1200s-timeout-but-landed pattern.** Workers report
  status structurally; the timeout is the budget per STEP (~5min
  default), not per WORKER.
- **No more shared in-flight slot tracking via state.json.** The
  proxy owns the slot count; state.json drifting becomes
  impossible by design.

---

## 11 — What v2 explicitly keeps from v1

- STATUS.csv (renamed `tracker.csv` to avoid collision with v1)
- Observer + L1-L5 escalation taxonomy
- HarnessError class hierarchy
- DPAPI secrets storage (extended to per-key DPAPI for 4 Kimi keys)
- Dashboard (becomes the operator UI for the coordinator)
- `harness loop` (becomes the wrapper that fires `harness coord run`
  on cadence)
