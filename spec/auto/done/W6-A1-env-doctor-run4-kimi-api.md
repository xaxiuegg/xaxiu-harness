# env-doctor-check (W6-A1 run 4, kimi-api worker) — extend `harness doctor` with env-var inventory

## Planner guidance (W6-A1 directive)

**This change MUST be done by ONE worker (single `write_set` covering BOTH files) because the tests in `tests/test_doctor.py` depend on the implementation in `src/harness/doctor.py`. Splitting across workers causes test failures because workers run in isolated worktrees that don't inherit each other's changes.**

A single worker with `write_set: ["src/harness/doctor.py", "tests/test_doctor.py"]` is the correct shape.

## Context

The harness ships `harness doctor` which runs preflight checks: python version, git, DPAPI, secrets presence, coord/ writability, Task Scheduler reachability. The secrets check conflates DPAPI + env var presence into one boolean.

A non-technical operator on a new machine often hits the case where their API keys are in env vars (not DPAPI) and `doctor` doesn't show which ones. Per `feedback_no_env_value_leak_in_shell_checks`, we must NEVER print values — only presence.

## Goal

Add a new doctor check named `env_var_inventory` that:

1. Iterates the canonical env-var names: `KIMI_API_KEY`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY`.
2. For each, reports `SET` or `UNSET` — NEVER the value.
3. Returns a single Diagnosis whose `message` is space-separated like: `KIMI:SET DEEPSEEK:SET ANTHROPIC:UNSET GEMINI:UNSET OPENAI:UNSET`
4. Severity is `"ok"` when at least one is SET, `"warn"` when none.
5. Add the check to `run_all()` so it appears in `harness doctor` output.

## Acceptance

- `pytest tests/test_doctor.py -q` stays green (existing tests must still pass).
- New tests for `_check_env_var_inventory` covering:
  - all keys SET → severity ok
  - mixed (some SET) → severity ok
  - all UNSET → severity warn
  - message format includes every canonical key with `:SET` or `:UNSET`
- `harness doctor` output shows a new row for `env_var_inventory`.
- NO test or message ever embeds the actual env-var value.

## File scope

- `src/harness/doctor.py` — add `_check_env_var_inventory()` and include it in `run_all()`. Keep new code under 40 LOC.
- `tests/test_doctor.py` — add 4 new tests.

Both files modified by ONE worker. Stdlib + existing harness internals only.

## Output format (engine must emit FILE/REPLACE blocks)

For each file modification, output ONE block in this exact format (no other narration around the blocks):

```
FILE: <relative/path/from/repo/root>
<<<<<<< SEARCH
<exact existing text to find>
=======
<replacement text>
>>>>>>> REPLACE
```

For ADDING new content to an existing file, use an EMPTY SEARCH block (append idiom):

```
FILE: tests/test_doctor.py
<<<<<<< SEARCH
=======
<new test code here>
>>>>>>> REPLACE
```

For CREATING a new file (not needed here — both files exist), same format with empty SEARCH.

## Why this spec exists

W6-A1 is the operator's turn-1 objective from the prior session that drifted. Run 4 retries with `swarm/kimi-api` as the worker engine after 3 mimo runs hit silent_no_op (engine returned text but 0 FILE/REPLACE blocks parsed). Handoff engine reliability matrix shows kimi-api 3/3 post-W5-V.
