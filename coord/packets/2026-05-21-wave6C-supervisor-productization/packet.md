# Packet: Wave 6/C — Real supervisor implementations (productize 4 NoOp placeholders)

## Mission

Replace the four `_NoOpSupervisor` placeholders in `src/harness/loops/supervisors.py` with real implementations that consume `harness.engines.dispatcher.dispatch_packet` for judgment work. Closes the Wave 6 caveat noted in the feature roster — the loop becomes truly autonomous instead of just the TestingSupervisor.

Disjoint from BUDGET-METER (harness/budget.py + cli.py) and GEMINI-ADAPTER (harness/engines/*); these can all run in parallel via swarm.

## In-scope MODIFY files

- `src/harness/loops/supervisors.py` — replace `_NoOpSupervisor("creativity")`, `("developing")`, `("integrating")`, `("process_improvement")` with real classes
- `tests/test_loops_supervisors.py` — extend with new tests (mocked dispatcher) for each new supervisor

## In-scope NEW files

NONE. All work lands in the existing supervisors module.

## Implementations

### CreativitySupervisor

Generates new improvement ideas using the in-session Claude engine (default) or Kimi (operator override). Reads wave_plan + recent commits, asks the engine to produce 1-3 ideas with scoring, queues the top idea above threshold 60 into `phase_cursors.creativity.queue`.

```python
class CreativitySupervisor(BaseSupervisor):
    phase = "creativity"

    def __init__(self, engine: str = "claude-in-session"):
        self.engine = engine

    def run(self, state, *, project, now, **kwargs):
        # Build context: recent commits + wave_plan + parked ideas (avoid duplicates)
        # Compose prompt asking for 1-3 ideas in strict JSON:
        #   [{"id":"...", "title":"...", "description":"...",
        #     "strategic_score":0-100, "operator_alignment_score":0-100,
        #     "estimated_loc":int, "estimated_kimi_minutes":int, "risk":"low|med|high"}]
        # For engine="claude-in-session", skip the dispatch and return a no-op result
        # with a log_summary explaining the supervisor needs an external engine.
        # For engine="kimi" or "kimi-api": invoke dispatch_packet with a synthesized
        # prompt file (write to tmp packet), parse JSON response, validate scores.
        # Append top idea to phase_cursors.creativity.queue.
        # write_set=["phase_cursors.creativity"]
```

### DevelopingSupervisor

Picks the next `wave_plan` entry with status=`queued` AND deps met, drafts a packet using the engine (or reuses an existing packet file if present), and dispatches via `xaxiu-swarm`. Updates `active_dispatches` + sets wave status to `in_progress`.

```python
class DevelopingSupervisor(BaseSupervisor):
    phase = "developing"

    def run(self, state, *, project, now, **kwargs):
        # If active_dispatches has phase=="developing", no-op (wait for completion).
        # Else pick next eligible wave:
        #   - state.wave_plan filtered to status=="queued" AND all depends_on in done
        # If existing packet at coord/packets/<wave-id>-*/packet.md, reuse.
        # Else dispatch a "draft a packet for wave X" Kimi call (Wave 6/D scope).
        # Run `xaxiu-swarm dispatch --backend kimi ...` via subprocess.Popen
        # so it's truly fire-and-forget; capture the bg task_id for active_dispatches.
        # write_set=["active_dispatches","wave_plan"]
```

### IntegratingSupervisor

Mechanical — no engine call needed. For each `pending_merges` entry, run `bin/parse-swarm-status.py` + `git diff --stat` + `pytest`; if all green, commit + push; remove from pending_merges.

```python
class IntegratingSupervisor(BaseSupervisor):
    phase = "integrating"

    def run(self, state, *, project, now, **kwargs):
        # For each entry in state.phase_cursors.integrating.pending_merges:
        #   - skip if block_commit==True
        #   - run subprocess.run(["python", "bin/parse-swarm-status.py", entry["output_file"], ...])
        #   - run subprocess.run(["python", "-m", "pytest", "tests/", "-q"], cwd=project)
        #   - if both green: subprocess.run(["git", "add", "."], cwd=project) and commit + push
        #   - update wave_plan entry status="done" + completed_at
        # write_set=["wave_plan","phase_cursors.integrating"]
```

For v1 the commit-on-pytest-green path is gated behind an env var `HARNESS_ALLOW_AUTO_COMMIT=true` so the operator opts in explicitly (safety guard for un-attended runs).

### ProcessImprovementSupervisor

Reads recent log.jsonl + commits, dispatches an audit prompt to engine, parses findings into P1/P2/P3 tiers per the prototype `coord/dev_loop/supervisors/process_improvement.md`. P1 fixes applied inline (small text edits to coord/dev_loop/*.md), P2 logged as packet draft, P3 appended to memory pointer.

```python
class ProcessImprovementSupervisor(BaseSupervisor):
    phase = "process_improvement"

    def run(self, state, *, project, now, **kwargs):
        # Read last 30 log.jsonl entries via harness.state.jsonl_log.read_recent_entries
        # Read git log --oneline -10
        # Compose audit prompt: "Identify 1-5 process findings; classify as P1/P2/P3"
        # For engine="claude-in-session": no-op (needs external engine like creativity)
        # For engine="kimi" or "deepseek": dispatch + parse JSON findings
        # Apply P1 findings (small text patches) inline
        # Write P3 findings to phase_cursors.process_improvement.findings_log
        # write_set=["phase_cursors.process_improvement"]
```

## Registry update

Replace the `_NoOpSupervisor` instances in `_SUPERVISORS`:

```python
_SUPERVISORS: dict[str, BaseSupervisor] = {
    "testing": TestingSupervisor(),
    "creativity": CreativitySupervisor(engine="claude-in-session"),
    "developing": DevelopingSupervisor(),
    "integrating": IntegratingSupervisor(),
    "process_improvement": ProcessImprovementSupervisor(engine="claude-in-session"),
}
```

Keep `_NoOpSupervisor` class around — it's still useful as a fallback for unknown phases via `run_supervisor`.

## Tests required

Each supervisor gets at least 3 tests:
1. Happy path (engine call mocked → JSON response → expected state_diff)
2. Engine failure / empty response → SupervisorResult with escalation
3. write_set populated correctly

Target ≥12 new tests across the four classes.

CreativitySupervisor + ProcessImprovementSupervisor with engine="claude-in-session" should be tested for "no-op + clear log_summary" behavior since they can't dispatch.

IntegratingSupervisor with `HARNESS_ALLOW_AUTO_COMMIT=false` (default) should be tested for "no commit attempted, just validation summary".

## Acceptance criteria

1. `_SUPERVISORS` has no `_NoOpSupervisor` instances for the four named phases.
2. Each supervisor's `run` returns a non-empty `write_set` when it makes progress.
3. `python -m pytest tests/ -q` shows ≥488 + new tests, all green.
4. `harness loop tick` against a fresh state.json still works end-to-end (smoke).
5. Single commit: `feat(loops): real CreativitySupervisor/DevelopingSupervisor/IntegratingSupervisor/ProcessImprovementSupervisor (Wave 6/C)`.

## Reference

- `src/harness/loops/supervisors.py` — current code with TestingSupervisor + _NoOpSupervisor placeholders
- `coord/dev_loop/supervisors/*.md` — prototype prose specs for each supervisor
- `src/harness/engines/dispatcher.py::dispatch_packet` — engine dispatch entry
- `src/harness/state/jsonl_log.py::read_recent_entries` — log reader for process_improvement
- Memory `feedback_full_automation_until_wave_plan_empty` — DevelopingSupervisor must keep dispatching until wave_plan empty

## Output format

1 modified module + 1 modified test file + 1 commit.
