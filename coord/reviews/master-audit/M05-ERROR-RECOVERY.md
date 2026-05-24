<!-- name=M05-ERROR-RECOVERY latency_ms=54254 error='' -->

## Score

1. **Correctness** — 4. The load-bearing schema bug (`EngineHealth.status` silently rejecting `quarantined`/`recovering`) was real, found, and fixed in `7081d93`. The quarantine→recover→clear flow now works end-to-end. Deduction: the bug existed for at least one wave before detection.

2. **Robustness** — 3. The `except Exception: continue` pattern that masked the schema bug is a code-smell the fix didn't fully extinguish — similar silent-swallow patterns elsewhere could hide future failures. The `preflight --fix` L4 toast path now works, which is good. But the operator has no instrumentation to detect "fix ran but didn't actually fix."

3. **Operator-usability** — 3. `engines-heal`, `today`, and `preflight --fix` are genuinely operator-driveable. But `git_clean` shows `[X]` after `--fix` with the same message — the operator runs the documented fix and still fails, with only a "Commit or stash" hint and no `preflight --fix` auto-resolution. **That is a dead-blocker for a non-technical operator.**

4. **Test discipline** — 3. 32 net tests added; the schema bug was caught by audit, not by tests. Tests assert "no exception" but not "engine_health row actually mutated" — the same class of silent-failure gap that caused the original bug.

5. **Risk** — 3. The `git_clean` dead-blocker is live right now (exit code 4 in preflight output). If the operator encounters it during an autonomous-mode start, they're stuck unless they know git.

6. **Top blocker** — **Make `git_clean` auto-fixable by `preflight --fix`**: stash dirty tracked files (or at minimum run `git stash push -m "preflight auto-stash"`). Right now the fix function exists but the preflight output still says "Run to fix: Commit or stash" — the operator runs `preflight --fix`, sees `[FIXED] git_clean`, reruns preflight, sees the same `[X]`, and is dead.

7. **Verdict** — **SHIP-WITH-FIXES.** The `git_clean` fix is a one-commit task and the only real operator-blocking dead-end in the snapshot; everything else is auditable noise or cosmetic.
