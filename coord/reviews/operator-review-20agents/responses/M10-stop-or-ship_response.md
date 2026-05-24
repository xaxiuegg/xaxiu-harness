### Verdict

`BLOCKED`

### Confidence

0.88

### Top-3 concrete recommendations

1. **Fix the Windows cp1252 Unicode crash — it kills every CLI command with Unicode glyphs on the primary platform.** `preflight`, `--help`, `agent init --dry-run`, and remediation-card rendering all traceback on `\u2192`/`\u2713`/`\u03b1` before they finish outputting. This is a zero-effort fix (wrap `click.echo` with `errors='replace'` or switch to ASCII fallbacks `->`/`[ok]`/`a`), but until it lands the harness is literally uninstallable on a stock Windows terminal. *Evidence*: files 04 (preflight crash on `\u2192`), 06 (`--help` crash on `\u03b1`), 15 (`agent init --dry-run` crash on `\u2713` — "files ARE created but traceback comes AFTER the writes" per the quickstart's own known-issues caveat). **Effort: S (≤2 hours).**

2. **8 failed pytest tokens in the cache must be cleared and replaced with a green run.** Preflight gates on `pytest_cache` (check = `[X] FAILED`), and the current state blocks the autonomous-mode preflight gate from ever passing. A v1.0 RC whose own readiness check fails is a contradiction. Run the suite, fix or mark-xfail the 8 failures, verify a full green. *Evidence*: file 04 line `pytest_cache: last run had failures (lastfailed has 8 tokens)`. **Effort: S–M (1–4 hours depending on root cause).**

3. **Kill the stale dashboard loop and wire the 4 missing v2 API endpoints.** The dashboard loop hasn't ticked since 2026-05-21 (3 days stale), `Active Dispatches` shows 2 entries from that date, and the four most important Wave 11 surfaces (`/api/loop`, `/api/cost`, `/api/preflight-latency`, `/api/l5-events`) all return `404 Not Found`. An operator opening `localhost:8765` sees a dead system. The backend code for cost widget, L5 banners, and latency tables exists; it just isn't routed. *Evidence*: file 00 (dashboard screenshot: stale loop, missing widgets), file 09 (`{"detail":"Not Found"}`), file 12 (`{"detail":"Not Found"}`), file 13 (`{"detail":"Not Found"}`), file 14 (`{"detail":"Not Found"}`). **Effort: M (half-day: fix loop scheduler + 4 route wires + smoke test).**

### Operator vote

`WAIT-FOR-WAVE-12`

The harness body is solid — 2141 tests green, 12/11 rows shipped, SDK validated against 3 real engines, ~30× context-cost reduction proven. But shipping an RC whose CLI crashes on every Windows terminal with Unicode output, whose preflight fails its own gate, and whose dashboard pretends it's May 21st is a trust-destroying move. None of these are deep architectural problems; one focused day of plumbing clears all three. Ship after that.

### Single quote from evidence

> `UnicodeEncodeError: 'charmap' codec can't encode character '\u2713' in position 0: character maps to <undefined>`