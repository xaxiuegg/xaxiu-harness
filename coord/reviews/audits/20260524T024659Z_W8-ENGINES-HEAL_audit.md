<!-- engine=mimo model=mimo-v2.5-pro task=W8-ENGINES-HEAL sha=6fbece001b67 latency_ms=89882 confidence=0.58 verdict=STOP — operator review required -->

# Wave 6 MiMo audit — task W8-ENGINES-HEAL

- Commit: `6fbece001b67` by xaxiuegg on 2026-05-23T19:37:43-07:00
- Message: W8 Track B — operator-readiness foundation shipped
- Confidence: **0.58**
- Verdict: **STOP — operator review required**
- Latency: 89882ms

## Raw MiMo audit response

```
{
  "task_id": "W8-ENGINES-HEAL",
  "criteria_met": false,
  "criteria_gaps": [
    "Acceptance criteria expects `harness engines heal` (subcommand of engines group) but implementation adds top-level `harness engines-heal` — naming mismatch with wave-6-plan spec, inconsistent with existing `engines reset` pattern.",
    "Criterion 'attempts key re-load from DPAPI' is only partially met: code checks key presence via `dpapi.has_secret` but does not actually reload the key into engine configuration — the key is presumed present but not loaded into active state.",
    "Criterion 'Integrates with the W6-C2 dead-engine alarm so the L4 toast can link to run this command' — no evidence in this commit that the alarm output links to `engines-heal`. Integration is limited to consuming `dead_engines()` function; no reciprocal link added to alarm code.",
    "Command does not appear in OPERATOR_RUNBOOK.md, so the operator may not discover it — acceptance criterion about 'one-command engine recovery' is not surfaced in the primary operator-facing document."
  ],
  "test_quality_concerns": [
    "All 8 tests monkeypatch every external dependency (`dead_engines`, `read_engine_health`, `dpapi.has_secret`, `update_engine_health`) — no real integration test with the actual engine alarm or DPAPI.",
    "No test covers exception paths: e.g., `dead_engines()` raising an exception, `read_engine_health()` returning corrupt data, or `update_engine_health()` failing. Code only has blanket `except Exception: click.echo; sys.exit(2)` — untested error handling.",
    "No test verifies that the 'recovering' status actually causes the dispatcher to retry — this is untrusted downstream behavior.",
    "`--engine` filter test only checks that one engine is in output and one is absent, but does not verify that only the filtered engine's actions are applied — missing assertion on update_calls length or contents."
  ],
  "new_debt": [
    "Imports from private module `harness._constants` (API_KEY_ENV_VARS) — creates coupling to private internals, no public API contract.",
    "Command `engines-heal` is a top-level verb rather than a subcommand of the existing `engines` group (`harness engines reset` already exists under `engines` group, creating inconsistency).",
    "Hardcoded glyphs and action strings in the output — no abstraction for i18n or consistency with other verbs' output style.",
    "`update_engine_health` call inside the loop uses `datetime.now(timezone.utc).isoformat()` — import at top of file would be cleaner; currently imports are inside the function body for `datetime` and `timezone`.",
    "No reversal-path test for the 'blocked' state (when key absent) — code prints 'no API key' but reversal instructions (e.g., `harness engines reset`) are only printed for 'quarantined' and 'recovering' actions, not for 'blocked'."
  ],
  "evidence_of_e2e_exercise": "None beyond commit message claim 'Smoke-tested in the current session's state (4 modified files, 2 dead engines, clean pytest cache). Output is operator-readable end-to-end.' No concrete output, no integration trace, no real-API run logs, no test with real DPAPI or alarm state. The tests are entirely unit-level with mocking.",
  "confidence": 0.58,
  "verdict": "STOP — operator review required",
  "one_line_summary": "Engines-heal implements core quarantine/recover/block logic with 8 mocked tests, but fails acceptance criteria on naming, missing key-reload action, no alarm-integration link, and no e2e evidence — confidence 0.58 below gate."
}
```
