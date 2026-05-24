<!-- engine=mimo model=mimo-v2.5-pro task=W9-AUDIT-NONDETERMINISM-AVG sha=99d316a838f7 avg_of_n=3 mean_confidence=0.80 stdev_confidence=0.04 min=0.78 max=0.85 pass_count=3/3 successful_runs=3/3 verdict=PASS -->

# MiMo audit (avg of 3) — task W9-AUDIT-NONDETERMINISM-AVG

- Commit: `99d316a838f7` by xaxiuegg on 2026-05-23T22:09:29-07:00
- Message: W9-AUDIT-NONDETERMINISM-AVG: --avg-of-N flag on the audit gate
- Runs requested: 3
- Runs successful: 3
- **Mean confidence: 0.80** (stdev 0.04, min 0.78, max 0.85)
- Per-run pass count (≥ 0.70): 3/3
- **Final verdict (mean-gated): PASS**

## Per-run details

### Run 1 — confidence 0.78 (PASS) — auditor: mimo (40940ms)

```
```json
{
  "task_id": "W9-AUDIT-NONDETERMINISM-AVG",
  "criteria_met": true,
  "criteria_gaps": [],
  "test_quality_concerns": [
    "No integration test for the N>1 parallel dispatch path through main() — only pure helpers are unit-tested. The commit message mitigates this by noting existing audit_wave8_all.py + manual sweeps exercise the end-to-end flow, but there is no regression guard against breakage in the ThreadPoolExecutor wiring, as_completed ordering, or the N>1 main() control flow.",
    "No test for argparse edge case: --avg-of-N < 1 returns exit code 2.",
    "No test for the failed-run-excluded-from-mean path where all-but-one run fails and the surviving run's confidence is exactly the gate boundary (0.7).",
    "get_engine() is called inside each thread with no visible thread-safety guarantee (e.g., singleton caching, DPAPI file I/O). If get_engine mutates shared state, concurrent N>1 runs could corrupt. Not tested, not documented as safe."
  ],
  "new_debt": [
    "The _dispatch_with_fallback function duplicates the engine-init-try/fallback-to-deepseek pattern from the old main() but as a clean extraction — no net new duplication, but the fallback chain (mimo → deepseek) is still not itself tested beyond the existing integration tests.",
    "The _PLAN_BY_TASK_PREFIX table is now 13 entries and grows with each wave. A future wave-prefix-scan would be cleaner but this is pre-existing debt, not newly introduced."
  ],
  "evidence_of_e2e_exercise": "None in this commit. The commit message references existing audit_wave8_all.py + manual sweeps as the integration surface, but no new smoke output, real-API trace, or integration log is included. The STATUS.csv row was updated to 'shipped' which suggests the author ran the script, but no audit report artifact (the avg*.md file itself) is included in the commit or referenced as evidence.",
  "confidence": 0.78,
  "verdict": "PASS",
  "one_line_summary": "All 8 acceptance criteria met; pure helpers are well-tested (19 tests); main concern is no regression test for the parallel dispatch path and no e2e evidence beyond STATUS.csv status change."
}
```
```

### Run 2 — confidence 0.78 (PASS) — auditor: mimo (48512ms)

```
```json
{
  "task_id": "W9-AUDIT-NONDETERMINISM-AVG",
  "criteria_met": true,
  "criteria_gaps": [],
  "test_quality_concerns": [
    "No test for --avg-of-N < 1 rejection path (code exists at line 'if args.avg_of_n < 1' but no unit test)",
    "No test for as_completed ordering (result ordering is nondeterministic, which affects which run is 'Run 1' etc. — acceptable but worth documenting)",
    "parse_audit_response regex \\{[\\s\\S]*\\} would span across two JSON objects if MiMo emitted two, yielding JSONDecodeError→(0.0, '?', {}) — low-probability edge case"
  ],
  "new_debt": [
    "Hardcoded 'engine=mimo' in _format_single_report HTML comment even when deepseek fallback was used (line: f'engine=mimo model=mimo-v2.5-pro') — metadata mismatch if fallback fires",
    "total_latency computed but only printed to console, not persisted in report file — minor loss of aggregate timing data"
  ],
  "evidence_of_e2e_exercise": "STATUS.csv row updated to 'shipped' with detailed notes including test-count delta (1576→1595). Commit message references the W8 sweep evidence (3 rows flipping PASS↔STOP) that motivated the change. No audit report artifact, smoke log, or actual --avg-of-N run output included in the commit. Evidence is code+tests-only; e2e exercise is plausible but not explicitly documented.",
  "confidence": 0.78,
  "verdict": "PASS",
  "one_line_summary": "All 8 acceptance criteria met; pure helpers enable real unit testing (19 tests, not stubs); ThreadPoolExecutor capped at 5; mean-gating with failed-run exclusion; report format correct; only gap is lack of explicit e2e smoke evidence and minor engine-metadata mismatch in single-report fallback path."
}
```
```

### Run 3 — confidence 0.85 (PASS) — auditor: deepseek (fallback) (82140ms)

```
{
  "task_id": "W9-AUDIT-NONDETERMINISM-AVG",
  "criteria_met": true,
  "criteria_gaps": [],
  "test_quality_concerns": [
    "No integration test for the parallel execution path (ThreadPoolExecutor usage); relies on manual sweeps as stated in commit message, but no automated smoke test exercises the script end-to-end with --avg-of-N > 1."
  ],
  "new_debt": [
    "The single-run report header hardcodes 'Wave 6 MiMo audit' even for W7/W8/W9 task IDs. Cosmetic debt — does not affect functionality but may mislead operators reviewing W9 audits."
  ],
  "evidence_of_e2e_exercise": "Commit message references manual sweeps exercising the end-to-end flow, but no automated integration test is included in this commit. The pure helpers are unit-tested thoroughly.",
  "confidence": 0.85,
  "verdict": "PASS",
  "one_line_summary": "All acceptance criteria met: --avg-of-N flag, parallel execution with capped ThreadPoolExecutor, pure aggregate_runs() helper, mean-gated exit code, correct report path and layout, failed-run exclusion, and 19 unit tests covering parsing, aggregation, formatting, and plan routing."
}
```
