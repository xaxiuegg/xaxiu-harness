<!-- name=M11-CONCURRENCY latency_ms=36065 error='' -->

## Score

1. **Correctness** — 3/5. W9-STATE-ATOMIC-WRITES + W9-STATE-FILE-LOCK landed, but the snapshot gives no proof the atomic-write pattern covers all shared state paths (engine_health JSON, engine_performance_log.jsonl, STATUS.csv). The schema bug fix is correct but the `except Exception: continue` that hid it may still exist in other write paths.

2. **Robustness** — 2/5. Preflight ThreadPoolExecutor checks run in parallel, but preflight --fix + engines-heal can quarantine engines concurrently with no mutual exclusion on engine_health writes. Coord supervisors share state files; observer reads them on its own cadence — no happens-before between observer tick and coordinator flush. Stale lock detection for `scheduled_tasks.lock` after crash not mentioned anywhere.

3. **Operator-usability** — 4/5. Concurrency is invisible to the operator by design, but the runbook doesn't warn against running `preflight --fix` while the autonomous loop is live — a plausible footgun.

4. **Test discipline** — 2/5. 1576 tests are almost certainly sequential. Zero evidence of parallel-execution stress tests, lock-contention tests, or TOCTOU regression tests. Mutation canary is spot-check (3 mutants), not concurrency-aware.

5. **Risk** — 4/5. Five subsystems (preflight, coord, observer, mutation sweeps, scheduled tasks) touch overlapping state files. The W9 atomic-write commit is < 1 week old and unproven under concurrent load. Windows file-locking semantics (mandatory vs advisory) add platform-specific hazard. A silent corruption in engine_performance_log.jsonl would poison dispatch routing for days.

## Top blocker

Add a concurrency stress test (`test_parallel_state_safety`) that simultaneously runs preflight --fix, engines-heal, coord status, and observer tick against shared state files, asserting no data corruption, no silent drops, and no stale-lock deadlock. Without it, the W9 atomic-write fix is aspirational, not verified.

## Verdict

**SHIP-WITH-FIXES** — The W9 atomic-writes commit addresses the worst race but lacks a concurrent-execution regression test to prove it; one stress test closes the gap between "fixed in theory" and "verified under load."
