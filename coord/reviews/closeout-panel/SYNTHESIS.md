# Wave 6 closeout panel — 10-reviewer synthesis

_Dispatched: 5 MiMo + 5 Kimi personas via `scripts/run_closeout_panel.py`.
First run (118s) returned all 5 MiMo + K4 full + K5 partial; K1/K2/K3
came back with empty text.  Diagnosis: Kimi `reasoning_content`
exhausts low `max_tokens` budgets before reaching `content`.  Retry
(`scripts/run_closeout_panel_retry.py`) at the engine default of 32K
recovered all 3, plus a separate K5 retry for the partial._

Each persona reviewed `coord/reviews/wave-6-closeout.md` with a
different framing so the panel surfaces diversity, not groupthink.
Per-persona responses are in this directory as `<name>.md`.

## Tally on documented options

| Reviewer | A3 (mutation sweep, 0.60) | C2 (dead-engine alarm, 0.62) |
|---|---|---|
| M1 skeptical-engineer | **B** | **A** |
| M2 product-manager | **B** | **A** |
| M3 operator-advocate | **A** | **A** |
| M4 qa-specialist | **B** | **A** |
| M5 architect | **B** | **A** |
| K1 cost-conscious | **A** | **A** |
| K2 risk-officer | **B** | **A** |
| K3 loop-researcher | **A** | **B** |
| K4 pragmatist | **A** | **A** |
| K5 devils-advocate | **B** | **B** |

**A3: 6 B / 4 A** — slight majority require-more-work.
**C2: 8 A / 2 B** — strong accept.

## Panel-surfaced unconsidered options

Six distinct third-paths emerged (clustered across reviewers):

1. **Partial scope for A3** — gate only `worker.py` (the 0.0-kill core
   coord module) before close; defer `concrete.py`/`orchestrator.py`
   to W7.  (M2, M5, M1)

2. **Conditional close + W7 backlog lock** — accept A3 and C2 now, but
   bind Wave 7 kickoff to remediation: `W7-MUTATION-*` must hit ≥3
   kill rate before any `W7-B1-RETROFIT` or new feature work begins.
   (K4, K2, K3 as "module quarantine")  Came up independently from 3
   reviewers — strongest panel signal.

3. **Scope-shift / dependency-order** — merge A3 debt with the B1
   retrofit since EngineTransport will reshape the very modules being
   mutation-tested; mutation-test the refactored shape, not the
   current one.  (M5 "Wave 6.5", M4, M1)  Second strongest signal.

4. **Time-boxed retry** — 15-20 min per failing artifact, ship
   regardless of outcome, ticket the gap.  (K1, K4 on C2, M3)

5. **Delegate to a different engine** — have DeepSeek (which scored
   17.3 on dispatcher.py) write the test improvements for the
   0.0-kill modules; have Kimi write C2 behavioral tests; have the
   audit script auto-queue Wave 7 rows.  (M3, M4, K3)

6. **Reality-check the metric itself** (devils-advocate K5) — before
   writing more tests, audit recent post-mortems and run a production
   log replay through the alarm in shadow mode (`test_alarm_shadow.py`)
   to compute false-positive / false-negative rates.  If the alarm
   doesn't match real engine deaths, the feature is solving the wrong
   problem.

## Next-session recommendation tally

| Recommendation | Votes |
|---|---|
| `worker.py` real-assertion tests (mutation kill 0.0 → ≥3) | 5 (M1, M2, M4, K2, K4) |
| `worker.py` budget hook fix (`input_tokens=0`) | 2 (M3, M5) |
| Dispatcher behavioral test for alarm integration | 1 (K1) |
| Planner auto-includes hook tests when alarm-class files added | 1 (K3) |
| Production-log shadow replay (`test_alarm_shadow.py`) | 1 (K5) |

Half the panel converges on `worker.py` work; the 2 budget-hook votes
are in the same file.  Pattern: make `worker.py` the focal point of
Wave 7.

## Recommended composite move (synthesis)

Three patterns the panel agrees on point to one composite move that
the closeout's binary framing didn't surface:

1. **Accept C2 as shipped** (8/10).  The 2 dissenters (K3, K5) want
   operational validation (behavioral / shadow replay), not more unit
   tests — K5's shadow-replay idea is the most actionable critique and
   belongs in Wave 7, not in C2's closing.

2. **Accept A3 conditionally with the K4/K2 lock** — `W7-MUTATION-WORKER`
   must hit ≥3 kill rate before any `W7-B1-RETROFIT` or new feature
   work begins.  This converts "follow-up row" (deferral) into
   "blocker on next work" (mitigation).

3. **Open Wave 7 with the `worker.py` budget hook** (quick win,
   restores token-tracking integrity), then immediately write the
   `worker.py` real-assertion tests (the strongest single panel
   vote), then re-run the mutation sweep on the now-instrumented
   module to validate the script itself.

## Per-persona responses

See individual files in this directory:

- [M1-skeptical-engineer.md](M1-skeptical-engineer.md)
- [M2-product-manager.md](M2-product-manager.md)
- [M3-operator-advocate.md](M3-operator-advocate.md)
- [M4-qa-specialist.md](M4-qa-specialist.md)
- [M5-architect.md](M5-architect.md)
- [K1-cost-conscious.md](K1-cost-conscious.md) _(retry pass — initial empty)_
- [K2-risk-officer.md](K2-risk-officer.md) _(retry pass — initial empty)_
- [K3-loop-researcher.md](K3-loop-researcher.md) _(retry pass — initial empty)_
- [K4-pragmatist.md](K4-pragmatist.md)
- [K5-devils-advocate.md](K5-devils-advocate.md) _(retry pass — initial truncated)_

## Loop-mechanic finding (not in the operator-facing synthesis)

The retry sequence surfaced a real Kimi-routing bug for future runs:
when a script overrides `max_tokens` to a small value (the original
`run_closeout_panel.py` passed 4000; the first retry pass overrode
to 2500), Kimi's `reasoning_content` consumes the full budget before
emitting `content`, returning `success=True` with empty text.

The check at `concrete.py:429` (`parsed_anything = bool(content_chunks)
or bool(reasoning_chunks) or usage_info is not None or bool(finish_reason)`)
correctly recognises usage as "something parsed" and returns success,
but downstream callers that only inspect `resp.text` see an empty
string with no error to act on.

Two W7 candidates:

- **Surface `reasoning_only` as a distinct EngineResponse state** so
  callers can detect this failure mode and retry with a larger budget
  rather than silently consuming the empty text.
- **Default `max_tokens` to >=16K when dispatching to Kimi** unless
  the caller explicitly opts to a lower cap.  Most callers don't know
  Kimi reserves reasoning budget; a sensible floor would prevent the
  silent-empty footgun.
