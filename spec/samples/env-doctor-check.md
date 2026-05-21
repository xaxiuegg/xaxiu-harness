# env-doctor-check — extend `harness doctor` with env-var inventory

## Context (for the planner)

The harness ships `harness doctor` (Phase 6 / FIRST-RUN-DOCTOR) which
runs preflight checks: python version, git, DPAPI, secrets presence,
coord/ writability, Task Scheduler reachability.  The secrets check
already conflates DPAPI + env var presence into one boolean output.

A non-technical operator on a new machine often hits the case where
their API keys are in env vars (not DPAPI) and `doctor` doesn't show
which ones.  Per the load-bearing memory `feedback_no_env_value_leak_in_shell_checks`,
we must NEVER print the values — only presence.

## Goal

Add a new doctor check named `env_var_inventory` that:

1. Iterates the canonical env-var names: `KIMI_API_KEY`, `DEEPSEEK_API_KEY`,
   `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `OPENAI_API_KEY` (the 4
   xaxiu-supported keys plus OpenAI for forward compat).
2. For each, reports SET or UNSET — NEVER the value.
3. Returns a single Diagnosis whose `message` is a comma-separated
   summary like: `KIMI:SET DEEPSEEK:SET ANTHROPIC:UNSET GEMINI:UNSET OPENAI:UNSET`
4. Severity is `"ok"` when at least one is SET, `"warn"` when none.
5. Add the check to `run_all()` so it appears in `harness doctor` output.

## Acceptance

- `python -m pytest tests/test_doctor.py -q` stays green (existing tests
  must still pass since we're adding, not modifying, behaviour).
- New test(s) for `_check_env_var_inventory` covering:
  - all keys SET → severity ok
  - mixed (some SET) → severity ok
  - all UNSET → severity warn
  - message format includes every canonical key with `:SET` or `:UNSET`
- `harness doctor` output shows a new row for `env_var_inventory`.
- NO test or message ever embeds the actual env-var value.

## File scope

- `src/harness/doctor.py` — add `_check_env_var_inventory()` and include
  it in `run_all()`.  Keep new code under 40 LOC.
- `tests/test_doctor.py` — add 4 new tests.

DO NOT modify any other module.  DO NOT touch DPAPI helpers.  Stdlib +
existing harness internals only.
