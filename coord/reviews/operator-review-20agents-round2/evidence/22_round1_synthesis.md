# 20-agent operator-review synthesis

**Date**: 2026-05-24
**Operator directive**: "spin up 10 mimo & 10 kimi agents to conduct
[operator-review], wait for its review then proceed [Wave 12 + real
day use]. I need you to actually ask agents to test use it and take
screenshot then evaluate from there"
**Method**: 20 personas (10 Kimi + 10 MiMo) given 21 evidence files
(CLI outputs, dashboard screenshot, docs, audit history, fresh-clone
crash trace) and asked to vote `READY` / `NEEDS-WORK` / `BLOCKED`
plus `APPROVE-AND-SHIP` / `WAIT-FOR-WAVE-12` / `ESCALATE-TO-HUMAN`.

## Vote tally

| Persona | Verdict | Operator vote | Confidence |
|---|---|---|---|
| K01-fresh-agent | NEEDS-WORK | WAIT-FOR-WAVE-12 | 0.55 |
| K02-operator-cli | NEEDS-WORK | WAIT-FOR-WAVE-12 | 0.75 |
| K03-non-technical-operator | NEEDS-WORK | WAIT-FOR-WAVE-12 | 0.35 |
| K04-dashboard-ux | NEEDS-WORK | WAIT-FOR-WAVE-12 | 0.82 |
| K05-security | NEEDS-WORK | WAIT-FOR-WAVE-12 | 0.70 |
| K06-test-coverage-honesty | BLOCKED | WAIT-FOR-WAVE-12 | 0.45 |
| K07-cost-truthfulness | — | (empty; engine returned 0 bytes after consuming 66K input) | — |
| K08-windows-cp1252 | NEEDS-WORK | WAIT-FOR-WAVE-12 | 0.90 |
| K09-onboarding-friction | NEEDS-WORK | WAIT-FOR-WAVE-12 | 0.72 |
| K10-real-day-of-use | NEEDS-WORK | WAIT-FOR-WAVE-12 | 0.62 |
| M01-architecture | NEEDS-WORK | WAIT-FOR-WAVE-12 | 0.82 |
| M02-spec-vs-reality | NEEDS-WORK | WAIT-FOR-WAVE-12 | 0.78 |
| M03-operator-decision-support | NEEDS-WORK | WAIT-FOR-WAVE-12 | 0.82 |
| M04-agent-context-economy | NEEDS-WORK | WAIT-FOR-WAVE-12 | 0.82 |
| M05-test-use-blockers | BLOCKED | WAIT-FOR-WAVE-12 | 0.92 |
| M06-wave-12-priorities | BLOCKED | WAIT-FOR-WAVE-12 | 0.82 |
| M07-failure-mode-surface | NEEDS-WORK | APPROVE-AND-SHIP (conditional on encoding fix) | 0.88 |
| M08-real-vs-vaporware | NEEDS-WORK | WAIT-FOR-WAVE-12 | 0.82 |
| M09-comparative-tooling | NEEDS-WORK | WAIT-FOR-WAVE-12 | 0.68 |
| M10-stop-or-ship | BLOCKED | WAIT-FOR-WAVE-12 | 0.88 |

**Score**: 0 unconditional APPROVE-AND-SHIP, 1 conditional APPROVE,
18 WAIT-FOR-WAVE-12, 1 empty response.

**Mean confidence**: 0.72 across 18 substantive responses.

## Unanimous priority signals

### #1: Fix Windows cp1252 Unicode crash (19/19 personas flag it)

Three distinct CLI entry points die with `UnicodeEncodeError` on Windows
console (cp1252 codepage):

| Command | Crash glyph | Location | Evidence |
|---|---|---|---|
| `harness preflight` | `→` (U+2192) | preflight remediation card | 04 line 32-41 |
| `harness --help` | `α` (U+03B1) | Greek-letter engineering marker | 06 line 24 |
| `harness agent init` | `✓` (U+2713) | success summary checkmark | 15 line 24 |

All three crash AFTER the work completes (files are written, preflight
checks run) but the operator sees a Python traceback as their final
output. Multiple personas independently identified this as the
"single highest-ROI fix" (M06) and the "true blocker" (M07).

**Fix paths** (all proposed by reviewers):
- Wrap `click.echo` with a `errors='replace'` UTF-8 helper
- `sys.stdout.reconfigure(encoding='utf-8', errors='replace')` in
  `cli.py::main()`
- Replace literal Unicode glyphs with ASCII fallbacks (`->`, `[ok]`,
  `alpha`)
- Add a CI step running `python -m harness --help` and `harness
  preflight --skip-engines` on `windows-latest` to catch regressions

Effort: **S** (30 min - 2 hours, depending on chosen approach).

### #2: Dashboard 404s on every Wave 11 endpoint (16/19 flag it)

The dashboard at http://localhost:8765 renders:
- Loop status with "Last tick 2026-05-21T00:02:35Z" — **3 days stale**
- Active Dispatches with stale entries from May 21
- Status Summary (329 shipped) — correct but static
- **Zero** Wave 11 surfaces:
  - No cost widget (`/api/cost` → 404)
  - No L5 banner (`/api/l5-events` → 404)
  - No preflight latency (`/api/preflight-latency` → 404)
  - No loop API (`/api/loop` → 404)

K04 (dashboard-ux, conf 0.82): "How bad is this gap from a
shipped-but-invisible perspective?" → "The backend modules exist and
work at the CLI level. The gap is wiring them into `app.py` as routes
and updating the dashboard HTML/JS."

M02 (spec-vs-reality, conf 0.78): "A dashboard that **partially**
renders stale data and **partially** 404s is worse than no dashboard.
Either wire the routes or remove the dashboard-serve verb from the
operator runbook."

Effort: **M** (2-4 hours; backend routes already exist, need
`include_router` lines + HTML template work).

### #3: Stale-loop detection / hidden-failure UX (8/19 flag it)

Dashboard says "Tick=11" with the loop "armed" but hasn't ticked
since May 21. A new operator opening localhost:8765 sees a healthy-
looking system that's actually dead. The watchdog primitive exists
(W11-OBSERVER-WATCHDOG-RECOVERY) but only watches the observer,
not the dev loop.

M03: "An operator staring at this dashboard sees a dead system."
M07: "Make watchdog status human-parseable — add elapsed-time-ago
and one-line verdict" (current output: `stale_seconds: 1209.651516`).

Effort: **M** (90 min for loop-watchdog + today integration + stale-
run cleanup verb).

## Secondary signals (mentioned 3-5 times)

4. **mypy --strict gate missing in CI** (M02, M06) — spec named it as
   W11-PYTHON-SDK-API-IMPL acceptance criterion but no CI step exists.
   Effort: S (~1-2 hours).

5. **AGENT_QUICKSTART.md `pip install -e .` likely untested** (K09) —
   all internal test invocations use `PYTHONPATH=src python -m` instead.
   Effort: S (~30 min to verify + correct doc).

6. **`.env` precedes DPAPI; attacker first-move is `cat .env`** (K05) —
   not a regression (it's the resolution order we picked) but
   AGENT_QUICKSTART.md should warn Windows users to migrate to DPAPI
   after setting initial keys. Effort: S.

7. **8 pytest cache "lastfailed" tokens block preflight green** (K01,
   M10) — preflight gates on `pytest_cache` check; current state is
   `[X] FAILED`. Clean the cache or surface which tests failed.
   Effort: S.

8. **`fix_pytest_cache()` should print actual `lastfailed` test names**
   not opaque "8 tokens" (M05). Effort: S.

## What the agents got RIGHT that confirms the SDK is solid

- M01: "The SDK core composes cleanly... E2E proof validates real
  round-trips with ~30× context-cost reduction."
- M04: "The arithmetic checks out. 142 bytes ≈ 35.5 tokens. The
  measurement is real."
- M03: "The SDK core (dispatch/retrieve/budget_status) is genuinely
  production-ready."
- M09: Table-form comparison shows the harness's unique strengths
  (multi-engine orchestration, autonomous pipeline, Python SDK,
  L5 watchdog, preflight gate, context-frugal returns, cross-platform
  observer, mutation canary, 20-agent audit panel) vs Claude Code
  CLI / Cursor / Aider — all 12 are unique to xaxiu-harness.

The SDK is shippable; the **surfaces** are not.

## Operator decision-support synthesis (M03 + M06)

**APPROVE (ship as-is for Python SDK consumers)**:
- `harness.dispatch()`, `.retrieve()`, `.budget_status()` Python SDK
- The 12/12 Wave 11 production rows landed and tested
- W5-E E2E proof + AGENT_QUICKSTART.md proven flow

**VETO (do not call this v1.0 RC)**:
- CLI on Windows (3 entry points crash)
- Dashboard claiming it works (3 days stale + 4× 404)
- "Mostly shipped" SESSION-2026-05-24-CLOSEOUT — needs the Unicode
  fix at minimum before operator review can land

**DEFER**:
- morning-email-brief, dashboard polish beyond minimum
- Live-engine smoke harness (one mock E2E proof + the in-session
  E2E I ran today is enough for now)
- installer MSI / GUI (W15+)

## Recommended next-cycle sequencing

Wave 12 = **operator-blocker triage**, not feature expansion:

1. **Wave 12-A (today, 2-4h): kill the three crashes + 4 dashboard 404s**
   - W12-WINDOWS-CP1252-FIX (S, ~30 min)
   - W12-DASHBOARD-WIRE-V2-ROUTES (M, ~2-3h)
   - W12-CI-WINDOWS-CLI-SMOKE (S, ~1h)

2. **Wave 12-B (next day, 2-4h): observability + honesty**
   - W12-LOOP-STALENESS-WATCHDOG (M, ~90 min)
   - W12-WATCHDOG-HUMAN-FORMAT (S, ~30 min)
   - W12-PYTEST-CACHE-DETAIL (S, ~30 min)
   - W12-MYPY-STRICT-GATE-CI (S, ~1-2h)

3. **Wave 12-C (after 12-A/B land, ½ day): re-fire the 20-agent panel**
   - Goal: at least 8/20 vote APPROVE-AND-SHIP
   - If yes → cut v1.0 RC tag, proceed to real-day-of-use
   - If no → another triage cycle

4. **Wave 13 (deferred): operator-UX expansion**
   - morning-email-brief
   - dashboard polish beyond minimum
   - GUI start wizard
   - Installer MSI

## Direct quotes that ground the verdict

> "UnicodeEncodeError: 'charmap' codec can't encode character '→'
> in position 5: character maps to <undefined>"
> — evidence 04_preflight.txt (the same error appears in 06 + 15)

> "NOTABLE GAPS: NO cost widget, NO L5 banner, NO preflight latency,
> NO recent commit list — none of the Wave 11 work is surfaced."
> — evidence 00_dashboard_screenshot.png description

> "A dashboard that **partially** renders stale data and
> **partially** 404s is worse than no dashboard."
> — M02-spec-vs-reality

> "Shipping an RC whose CLI crashes on every Windows terminal with
> Unicode output, whose preflight fails its own gate, and whose
> dashboard pretends it's May 21st is a trust-destroying move. None
> of these are deep architectural problems; one focused day of plumbing
> clears all three. Ship after that."
> — M10-stop-or-ship

## Conclusion

The 20-agent panel verdict is unambiguous: **the SDK is ready, the
operator surfaces are not**. None of the issues are deep architectural
problems. One focused half-day of plumbing closes the gaps and earns
the v1.0 RC label.

**Recommended next move**: Wave 12-A (Unicode + dashboard wires +
Windows CI smoke). Then re-fire the panel. Only proceed to real-day-of-
use after the panel votes APPROVE-AND-SHIP at the threshold.
