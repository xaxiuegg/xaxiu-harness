# wave1-session-ok-to-stop-json — JSON output for `harness session ok-to-stop`

## Context (for the planner)

`harness session ok-to-stop` exits 0/1 and emits a single text line
explaining the gate decision.  The Chat Observer's `premature_stop`
pattern + downstream automations (dashboard, CI, future
`coord run-prep`) want the decision parts as structured JSON.

The current text contract is:
```
OK-TO-STOP: <reason>             # exit 0
NOT-YET: <reason>                # exit 1
```

## Goal

Add a `--json` flag that emits:
```json
{
  "ok_to_stop": true,
  "reason": "session-handoff recommendation STRONGLY",
  "production_queued": 0,
  "creativity_fired_within_minutes": 12,
  "approval_file_present": false
}
```
…then exit 0 or 1 as today.  The reason field is the single sentence
the text mode prints; the rest are the inputs that drove the decision.

## Acceptance

- `python -m pytest tests/test_session_ok_to_stop.py -q` stays green.
- 4 new tests via `CliRunner`:
  1. `--json` happy path → parseable JSON with `ok_to_stop: true`,
     exit 0.
  2. `--json` NOT-YET path → `ok_to_stop: false`, exit 1, reason set.
  3. JSON includes the three input fields above.
  4. Existing text mode is unchanged (assert one expected substring).

## File scope

- `src/harness/cli.py` — extend the `session ok-to-stop` click command
  with `--json`.  Keep new code under 35 LOC.
- `src/harness/session/` — if the gate's internal `decide()` already
  returns a structured record, reuse it.  If not, refactor minimally
  so both text + JSON paths derive from one source.

DO NOT change the gate's decision logic — only the output channel.
