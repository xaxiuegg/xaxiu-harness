# v1.0.0-rc.1 — 24h autonomous run spec

**Purpose**: Real-day-of-use test for the v1.0.0-rc.1 release candidate.
Operator opt-in via 20-agent panel Round 2 (commit 7a886c5).  Goal:
let the harness carry weight unattended for 24h and surface what
breaks.

**What the harness should do during the 24h window**:

## Hour 0 (now): bring up to baseline
- Verify observer is armed: `harness observer status` → armed=True
- Verify dev-loop state.json exists (or initialize via `harness loop init`)
- Verify cron entries are present (Linux/Mac) or Task Scheduler tasks are
  present (Windows)
- Take a baseline screenshot of the dashboard at http://localhost:8765
- Capture `harness today --since-hours 24` to baseline log

## Hours 1-22: hourly observer cycles
The cron-armed observer fires `harness observer cycle-now` every 60 min.
Each cycle:
- Scans recent git commits (last 20) for drift
- Checks STATUS.csv freshness
- Audits dispatch ledger for anomalies
- Raises HIGH/CRITICAL flags as needed → operator wakes to them in
  `harness today` or `harness observer flags`

## Hour 23: daily retro
Cron fires `harness observer daily-retro` at 23:00.  Wrapping up:
- Aggregate the day's flags
- Summarize dispatches + cost
- Note any L5 escalations
- Write `coord/observer/daily/YYYY-MM-DD.md`

## Hour 24: operator wake-up
Run `bash scripts/v1-rc1-24h-report.sh` to generate the
`coord/reviews/v1-rc1-24h-report.md` artifact.  Inspect:
- Observer cycle count (expect ~24)
- Flags raised + severity breakdown
- Dispatches fired + cost spent (expect <$1)
- L5 escalations (expect 0)
- Preflight state at wake (expect PASS or PASS-WITH-WARNINGS)
- Dashboard tail (any visible-but-not-flagged anomalies)

## Wave 12-B candidates the loop MAY work on if it gets to it

The operator-review-panel synthesis suggested these as Wave 12-B work.
The dev-loop is NOT required to land any of them during the 24h —
they're listed so the operator (or a future autonomous arc) knows
the backlog:

1. **W12-MYPY-STRICT-GATE-CI** (S, ~1-2h): add `mypy --strict
   src/harness/_sdk.py` to the GitHub Actions workflow
2. **W12-MORNING-EMAIL-BRIEF** (M, ~4h): SMTP/CLI sender that emails
   the operator a daily harness pulse at 07:00
3. **W12-LIVE-ENGINE-SMOKE-HARNESS** (M, ~3h): weekly CI step that
   exercises real Kimi + DeepSeek + MiMo (vs the current mock-only
   smoke)
4. **W12-DASHBOARD-COST-WIDGET-HTML** (M, ~3h): the /api/cost endpoint
   ships JSON but the dashboard HTML doesn't render it yet
5. **W12-DASHBOARD-L5-BANNER-HTML** (M, ~2h): same for /api/l5-events

## Safety constraints (the harness already enforces these)

- `COST_MAX_PER_SESSION=$5` — auto-escalate at 80% / refuse new
  dispatches at 100%
- L5 flags interrupt the operator-visible surface (preflight + today
  + dashboard)
- Watchdog detects stale observer; auto-restart attempted; L5 banner
  fired after 3 consecutive failures
- Engine cooldowns: 60min Kimi / 15-30min others on failure
- circuit breaker quarantines flapping engines

## Success criteria (what "the test passed" means)

- At least one observer cycle fires during the 24h
- No L5 escalations the operator wasn't already aware of
- Cost spent < $1 (observer cycles are cheap)
- Preflight at wake-up: PASS or PASS-WITH-WARNINGS (NOT FAIL)
- Operator can run `harness today` at wake-up and get a useful
  picture of what happened

## Failure modes the operator should look for

- Watchdog STALE (observer task hung / cron entry deleted)
- `harness today` crashes or shows tracebacks
- Dashboard at :8765 unreachable
- L5 escalation that didn't reach the operator
- Cost spike (>$2 in 24h would be suspicious)
- Anything in `coord/observer/flags/*.md` marked CRITICAL

## Why this is the right shape of test

The harness's primary value-prop is *unattended operation* — observer
catches drift, watchdog catches scheduler death, preflight catches
configuration rot, L5 banner catches the rest.  A 24h hands-off
window stresses every one of those primitives at once.  Anything that
breaks in 24h is something a real operator deploying v1.0 would also
hit.
