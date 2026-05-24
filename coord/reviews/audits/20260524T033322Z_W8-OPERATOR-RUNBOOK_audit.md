<!-- engine=mimo model=mimo-v2.5-pro task=W8-OPERATOR-RUNBOOK sha=6fbece001b67 latency_ms=58357 confidence=0.58 verdict=STOP — operator review required -->

# Wave 6 MiMo audit — task W8-OPERATOR-RUNBOOK

- Commit: `6fbece001b67` by xaxiuegg on 2026-05-23T19:37:43-07:00
- Message: W8 Track B — operator-readiness foundation shipped
- Confidence: **0.58**
- Verdict: **STOP — operator review required**
- Latency: 58357ms

## Raw MiMo audit response

```
```json
{
  "task_id": "W8-OPERATOR-RUNBOOK",
  "criteria_met": false,
  "criteria_gaps": [
    "Morning sequence header claims '3 commands' and bold text says 'Three commands every morning', but only 2 non-optional harness commands are shown (preflight + today); morning-brief is explicitly optional ('optionally run ... most days harness today is enough'). The cd row is navigation, not a command. Spec requires EXACTLY 3-5.",
    "README link is on line 4 (the first non-heading, non-blank, non-quote content line), not the README's literal first line as spec requires. Acceptable 'above the fold' but violates 'first line' wording.",
    "Runbook references 'harness engines heal' (space-separated) in the remediation section, but the actual CLI verb registered is 'engines-heal' (hyphenated, per cli.py @cli.command(name='engines-heal')). An operator typing 'harness engines heal' would get an error."
  ],
  "test_quality_concerns": [
    "harness today tests mock _all_check_callables (a private function) to avoid real preflight execution — never exercises the actual preflight integration path, only verifies click output formatting against stubs.",
    "harness engines-heal tests are well-structured (8 scenarios covering quarantine/recover/blocked/dry-run/filter/reversal) but all rely on monkeypatched dead_engines and read_engine_health — no test exercises the real state layer or DPAPI integration.",
    "No test for the bare except clause in engines_heal_cmd when dpapi.has_secret() raises (currently silently sets key_present=False — operator gets a false 'blocked' diagnosis when DPAPI is actually down, not missing a key).",
    "No test for the bare except in today_cmd's audit-parsing path (import re inside try block) or the 'couldn't run preflight' fallback path.",
    "harness today preflight section calls run_all in a ThreadPoolExecutor but the result is unused (pre_results is populated but the severity loop iterates over pre_results, not the run_all return). The variable shadowing (pre_results vs results) suggests last-minute refactoring."
  ],
  "new_debt": [
    "harness today accesses preflight._all_check_callables() — private API with underscore prefix. If preflight internals refactor, today silently breaks.",
    "engines_heal_cmd silently swallows exceptions from dpapi.has_secret() (except Exception: key_present = False). DPAPI outage → operator sees 'blocked, no API key' instead of 'DPAPI error, check secrets service'. No logging or stderr.",
    "harness today creates its own ThreadPoolExecutor for preflight checks despite run_all() existing as the public API. Duplicated orchestration logic.",
    "Operator runbook was clearly written in two passes (original 3-command sequence with morning-brief + engines-heal, then edited to swap morning-brief for today). The '3 commands' claim survived the edit but the content didn't — stale documentation."
  ],
  "evidence_of_e2e_exercise": "Commit message claims 'Smoke-tested in the current session's state (4 modified files, 2 dead engines, clean pytest cache). Output is operator-readable end-to-end.' — but provides no actual command output, no terminal log, no screenshot, no test fixture with realistic output. The 27 new tests are all unit tests against mocked dependencies. No integration test or recorded smoke session is included in the commit or referenced artifact.",
  "confidence": 0.58,
  "verdict": "STOP — operator review required",
  "one_line_summary": "Runbook has stale '3 commands' claim (only 2 shown), README link is line 4 not line 1, engines-heal CLI name mismatch in doc, and tests are mock-only with no e2e smoke evidence — plus today CLI accesses private preflight internals and engines-heal silently swallows DPAPI errors."
}
```
```
