### Verdict
`BLOCKED`

### Confidence
0.92

The harness cannot be used on a real project tomorrow on its **target platform** (Windows, cp1252 console). The single most critical path — `harness preflight` — crashes before producing output. Every Unicode-emitting CLI verb is a trap. This is not a "polish" issue; it's a **launch-day crash** on the only platform the developer has tested against.

---

### Top-3 concrete recommendations

**1. Fix the systemic `UnicodeEncodeError` on Windows cp1252 consoles — every `click.echo()` that emits `→`, `✓`, `α`, or any non-Latin-1 character is a crash.**

The fix is a one-line encoding wrapper or `PYTHONIOENCODING=utf-8` injection at the top of `cli.py:main()`. Three independent evidence files prove it:

| Broken command | Character | Evidence file |
|---|---|---|
| `harness preflight` | `→` (U+2192) | `04_preflight.txt` line 24 |
| `harness --help` | `α` (U+03B1) | `06_harness_help.txt` line 24 |
| `harness agent init --dry-run` | `✓` (U+2713) | `15_agent_init_dry.txt` line 24 |

- **Evidence**: files 04, 06, 15 — each ends with the identical `UnicodeEncodeError: 'charmap' codec can't encode character … in encoding_table`
- **Effort**: **S** (30 min). Add `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` in `main()`, or wrap `click.echo` via a helper that catches `UnicodeEncodeError` and strips offending glyphs. The existing `l5_escalation.py` render functions already work — the bug is purely in the CLI output layer.

---

**2. Dashboard v2 routes (`/api/loop`, `/api/cost`, `/api/preflight-latency`, `/api/l5-events`) return `404 Not Found` — Wave 11 work is invisible on the only visual surface.**

Four of five dashboard API endpoints tested return `{"detail":"Not Found"}`. The one that works (`/api/status`) shows a flat list with no Wave 11 awareness. The screenshot confirms: zero cost widget, zero L5 banner, zero latency histogram, zero recent commits — three days stale with two zombie dispatches.

| Endpoint | Response | Evidence file |
|---|---|---|
| `/api/loop` | `{"detail":"Not Found"}` | `09_dashboard_api_loop.json` |
| `/api/cost` | `{"detail":"Not Found"}` | `12_dashboard_api_cost.json` |
| `/api/preflight-latency` | `{"detail":"Not Found"}` | `13_dashboard_api_preflight_latency.json` |
| `/api/l5-events` | `{"detail":"Not Found"}` | `14_dashboard_api_l5_events.json` |

- **Evidence**: files 00, 09, 12, 13, 14
- **Effort**: **M** (2–4 hours). The backend modules (`cost_widget.py`, `preflight_latency.py`, `l5_escalation.py`) exist and work at the CLI level. The gap is wiring them into `app.py` as routes and updating the dashboard HTML/JS. `W11-DASHBOARD-AS-DEFAULT-SURFACE` was deferred to W15+, which is honest — but a dashboard that **partially** renders stale data and **partially** 404s is worse than no dashboard. Either wire the routes or remove the dashboard-serve verb from the operator runbook.

---

**3. `preflight --fix` cannot remediate the `pytest_cache` failure because `fix_git_clean()` emits the `→` character before the fix hint — the crash happens inside the fix path, not just the report path.**

Evidence 04 shows the preflight check listing completed, then the crash occurs on `click.echo(f"     → Run to fix:  {r.fix}")` at `cli.py:2255`. This means the auto-remediation feature (W8-PREFLIGHT-FIX) that was designed to be the **#1 operator readiness blocker fix** is itself blocked by bug #1. The operator is stuck in a loop: preflight fails → `--fix` crashes → manual `pytest` required → but which 8 tests? (`lastfailed has 8 tokens` is all they're told).

- **Evidence**: `04_preflight.txt` — the traceback at `cli.py:2255` is the `→` fix-hint line, not the check-result line. The `[X] pytest_cache` row printed successfully; it's the remediation card that kills the process.
- **Effort**: Covered by fix #1 above (same root cause). But independently, `fix_pytest_cache()` should also **print the actual `lastfailed` test names** instead of the opaque `last