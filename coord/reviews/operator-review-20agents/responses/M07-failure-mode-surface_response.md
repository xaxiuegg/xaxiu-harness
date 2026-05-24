### Verdict

`NEEDS-WORK`

### Confidence

0.88

The harness has strong failure-mode *intent* — the L5 banner contract is genuinely good, `harness today` reads well, and the cost widget is operator-grade. But a single Windows encoding bug (cp1252 + Unicode characters) crashes **three separate commands the operator must run daily**, and the dashboard is three days stale with zero Wave 11 surfaces. These are fixable in <1 day but they're not cosmetic — they break the primary surface on the only platform the operator actually uses.

### Top-3 concrete recommendations

1. **Fix the Unicode/cp1252 encoding crash on Windows console output.** Three commands (`preflight --fix`, `--help`, `agent init`) die with `UnicodeEncodeError` because `click.echo()` writes Unicode arrows (→), Greek (α), and checkmarks (✓) to a cp1252 console. The fix is a single `click.echo(..., err=True)` wrapper or `PYTHONIOENCODING=utf-8` bootstrap in `cli.py::main()`, or replacing all Unicode literals with ASCII equivalents. This is the only true blocker — the operator literally cannot run `harness --help` on Windows without a traceback.
   - Evidence: `04_preflight.txt` line 23 (`\u2192`), `06_harness_help.txt` line 23 (`\u03b1`), `15_agent_init_dry.txt` line 23 (`\u2713`)
   - Effort: **S** (one file, ~30 lines, ASCII substitution or encoding wrapper)

2. **Refresh the dashboard to surface at least cost-widget + L5 banner + loop staleness.** The dashboard screenshot (evidence 00) shows a loop last ticked **three days ago** with no cost widget, no L5 banner, and no preflight latency — all of which have shipped JSON endpoints (evidence 02, 07, 05). An operator glancing at `localhost:8765` sees a stale, featureless page and has no idea Wave 11 shipped. The v2 API routes exist (`/v2/runs`, `/v2/cost-panel`) but the HTML frontend doesn't call them.
   - Evidence: `00_dashboard_screenshot.png` (binary; description confirms all Wave 11 surfaces missing), `12_dashboard_api_cost.json` / `14_dashboard_api_l5_events.json` both return `{"detail":"Not Found"}`
   - Effort: **M** (HTML template work wiring existing JSON endpoints into the frontend; no backend changes)

3. **Make watchdog status human-parseable — add elapsed-time-ago and one-line verdict.** The watchdog output (`03`) is machine-shaped: `stale_seconds: 1209.651516` with no context. The operator has to do mental math (1209s ÷ 60 = ~20 min ago) and know the cadence (60 min) to judge whether that's fine. Compare this to the excellent cost-widget format ("$0.26 / $5.00 budget — 16% offload [ok]"). The watchdog deserves the same treatment: "`Watchdog: OK — last cycle 20m ago (cadence: 60m)`" or "`Watchdog: STALE — last cycle 4h ago (expected: every 60m)`".
   - Evidence: `03_observer_watchdog.txt` (6 raw key-value lines, no verdict, no elapsed-time-ago)
   - Effort: **S** (add `watchdog_summary()` one-liner; wire into `harness today` and the watchdog-status CLI)

### Operator vote

`APPROVE-AND-SHIP` — conditioned on the encoding fix landing first. The dashboard and watchdog polish can trail into Wave 12 without blocking the RC. But `harness --help` dumping a traceback on Windows is disqualifying for a v1.0 label.

### Single quote from evidence

```
UnicodeEncodeError: 'charmap' codec can't encode character '\u2192' in position 5
```
— `04_preflight.txt`, the operator's very first preflight interaction after Wave 11 crashes before printing the fix hint.