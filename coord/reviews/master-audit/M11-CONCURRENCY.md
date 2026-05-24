<!-- name=M11-CONCURRENCY latency_ms=24293 error='' -->

## Score

1. **Correctness — 3/5**: Three distinct concurrency runtimes (ThreadPoolExecutor, asyncio, multiprocessing) share mutable state (engine_health.json, git index, pytest cache) with **no cross-model synchronization**. The schema fix (7081d93) corrected the *shape* of writes but not their *atomicity*.

2. **Robustness — 2/5**: `preflight --fix` does `git stash` + file mutation + engine_health write. If Task Scheduler fires the autonomous loop while an operator runs `preflight --fix` manually, both contend on the git working tree and the same JSON file. The `scheduled_tasks.lock` is your only guard, and nothing in the snapshot confirms it's checked before engine_health writes. The `except Exception: continue` that hid the schema bug is the *exact pattern* that hides races too.

3. **Operator-usability — 4/5**: Not the operator's problem to solve. The CLI verbs look clean.

4. **Test discipline — 2/5**: Zero evidence of concurrent stress tests. All 1576 tests are sequential. A single `concurrent.futures.ThreadPoolExecutor` submitting two `preflight --fix` calls against shared state would surface the race in seconds, yet it doesn't exist. Mutation sweeps fork processes that could mutate files mid-read by the main process — untested.

5. **Risk — 4/5**: Task Scheduler fires the autonomous loop on a cadence; `preflight --fix` is its first step. A manual `preflight --fix` from the operator during a scheduled tick is a plausible data race on `engine_health.json` and the git index. Silent corruption (like the quarantine bug, but concurrency-induced) is the likely failure mode.

## Top blocker

**Add an advisory file lock (`portalocker` or `fcntl`) around `engine_health.json` read-modify-write in `_check_dead_engines`, `engines heal`, and `preflight --fix`, plus a 3-line concurrent smoke test that submits two `preflight --fix` calls to a ThreadPoolExecutor and asserts no duplicate quarantine writes.** This is the only shared mutable state accessed from all three concurrency models with no happens-before guarantee today.

## Verdict

**SHIP-WITH-FIXES.** The operator-readiness work is genuinely load-bearing, but the unsynchronized engine_health writes under concurrent Task Scheduler + manual invocation are a data-race waiting to manifest as silent corruption — the same class of bug you just fixed.
