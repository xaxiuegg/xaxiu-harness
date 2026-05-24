<!-- name=M01-INSTALL latency_ms=23674 error='' -->

## Score

1. **Correctness** — 3. Preflight runs and `--fix` resolves git/pytest issues, but dead_engines warns immediately on a fresh clone where no keys exist yet; that's an expected state, not a real failure, yet the operator sees `[!]` with no "you need keys first" context.

2. **Robustness** — 2. The schema bug (Literal rejected `quarantined`/`recovering` silently swallowed by bare `except Exception`) is exactly the failure mode a fresh-install reviewer fears most — the fix shipped, but the pattern recurs: `_check_dead_engines` still fires on a keyless clone, observer times out because it's not running, loops warn because nothing's registered. Three warnings at first boot, none explained.

3. **Operator-usability** — 2. There is **no cold-start path visible in this snapshot**. No `pip install -e .`, no `pyproject.toml`, no "clone → install → run" sequence. The operator runbook (`docs/OPERATOR_RUNBOOK.md`) exists but isn't referenced until the final line of `harness today`. A non-technical operator cloning this repo doesn't know whether to run `pip install`, `poetry install`, or `python -m harness` directly. The CLI entry point is `python -m harness` — not mentioned anywhere in the preflight output.

4. **Test discipline** — 4. 1576 tests, mutation kill rates above gate, the schema bug caught by audit. But the `except Exception: continue` pattern that hid the quarantine bug is a test-discipline smell — the fix addressed the symptom, and no new test asserts "quarantined status actually persists."

5. **Risk** — 3. The cold-start story is invisible to the snapshot audience. Every new operator will hit the same wall: clone, stare at CLI help, guess at installation, get three warnings they can't interpret.

6. **Top blocker** — Add a `README.md` or `docs/COLD_START.md` with the exact 5-command path: clone → `pip install -e .` → set 3 API keys → `harness preflight --fix --skip-engines` → `harness today`. Without it, the operator runbook is unreachable.

7. **Verdict** — **HOLD.** The harness works once bootstrapped, but there is literally zero documentation for the first 5 minutes after clone — the exact window this lens audits.
