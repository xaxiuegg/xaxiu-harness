<!-- name=M08-ENGINE-RELIABILITY latency_ms=38757 error='' -->

## Score

1. **Correctness** — 3. Quarantine/recovery lifecycle now implements the spec post-schema-fix (7081d93), but a bug that silently swallowed every quarantine write for weeks proves the spec was unmet until very recently.

2. **Robustness** — 2. The `except Exception: continue` that hid the schema bug is a **pattern-level hazard**. One was found; the question is how many remain. DeepSeek is currently dead (`deepseek:5`) and recovery hasn't been demonstrated end-to-end in production — only manually verified with `--skip-engines`.

3. **Operator-usability** — 4. `engines-heal` exists, `harness today` surfaces the blocker, and the runbook documents recovery steps. Minor gap: key-rotation vs. quarantine decision isn't guided in the CLI output itself.

4. **Test discipline** — 2. Tests passed *throughout* the broken-quarantine period because the same `except Exception: continue` masked failures in test stubs too. The follow-through explicitly notes stubs had to be taught to match Pydantic forms — meaning tests were validating a different code path than production ran.

5. **Risk** — 3. DeepSeek is dead *right now*. The schema fix is <1 commit old, the non-det audit on ENGINES-HEAL means we can't rely on automated verification, and autonomous overnight loops will degrade silently if a second engine fails while the recovery path has an undiscovered bug.

6. **Top blocker** — Systematic grep for `except Exception` with bare `continue`/`pass` in every engine-health, quarantine, and dispatcher-fallback path. The schema bug proves these patterns hide load-bearing failures. Each hit needs a logged warning or explicit re-raise. Estimate: 2 hours, eliminates the entire category.

7. **Verdict** — **SHIP-WITH-FIXES.** The single-engine-collapse path exists and the schema bug is patched, but the silent-swallow pattern that hid it for weeks is a systemic defect that must be hunted before we can trust the recovery lifecycle under real autonomous load.
