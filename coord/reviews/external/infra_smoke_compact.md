# Infrastructure smoke evaluation request — 2026-05-22 post-migration

You are reviewing the **post-migration infrastructure smoke test results** of
xaxiu-harness (multi-engine LLM dispatch harness, Claude-managed).  Your job
is independent assessment.

## Context (compact)

Earlier today operator caught: (a) observer was "armed but blind" — all 7 prior
auto-cycles returned `dispatch_success: false, error: unsupported_force_engine`;
(b) engines weren't running properly via various paths.  Both root-caused +
fixed: cycle.py was passing `swarm/deepseek` but `dispatch_packet` only
accepts bare backends; observer adapter YAML was missing.

Then the project was migrated from `D:/Projects/xaxiu-harness/` (shared
Claude Code memory dir) to `D:/xaxiu-harness-standalone/` (isolated memory
dir, 43 of 51 entries carried).  Old location archived.

## Smoke results (just ran from new location)

```
A. Direct HTTP probes (4 engines):
  ✓ kimi-k2.6        200 OK in  8.3s
  ✓ deepseek-v4-flash 200 OK in  1.4s
  ✓ mimo-pro-sgp     200 OK in  1.4s  (Token Plan SGP gateway)
  ✓ mimo-std-sgp     200 OK in  2.0s

B. dispatch_packet (in-process):
  ✓ force_engine=kimi      → engine_used=kimi      ('OK')        in 3.2s
  ~ force_engine=deepseek  → engine_used=KIMI      ('OK')        in 4.0s   ← deepseek failed → fell through chain
  ✓ force_engine=mimo      → engine_used=mimo      ('OK')        in 6.3s

C. worker.run_worker (mocked engine, real wiring): PASS in 33ms

D. observer:
  ✓ cycle-now (real dispatch via swarm/mimo): PASS in ~34s, response='[]' (clean audit, no flags)
  ✓ observer-state.json: armed=True, total_cycles=8

E. coord plan (real, --engine mimo, spec/samples/env-doctor-check.md):
  ✓ PASS in 31.2s → 2-task wave plan

F. CLI verb sanity:
  ✓ doctor, observer status, observer flags, budget summary, engines, coord --help

Pytest at new location: 1 224 / 1 224 green in 101.9s.

Total: 16 PASS, 1 driver-side issue (my smoke script bug, not harness).
```

## Known dispatcher behavior (interesting)

Category B confirms: `dispatch_packet(force_engine="deepseek")` returned
`engine_used=kimi`.  Even with `force_engine` set, the dispatcher iterates
the full fallback chain when the primary engine returns success=False.
Earlier engine reviews (MiMo Pro + DeepSeek themselves) both flagged this
as a top fix candidate.

DeepSeek HTTP probe (Cat A) succeeded with 200 OK in 1.4s for the bare
HTTP call.  So the failure in Cat B was inside `dispatch_packet`'s
classify_response / guards layer — the response was scored as failure
even though the raw HTTP succeeded.  Worth investigating separately.

## Your job

Be terse and specific.  Answer these 4 questions:

1. **Is the infrastructure now fit for autonomous dev-loop work?**  (yes/no/conditional, 2 sentences)
2. **What's the #1 risk if I leave the project running unattended for 8 hours?**  (one specific failure mode + likelihood)
3. **The DeepSeek-via-dispatch_packet engine_used=kimi result is concerning — diagnose.**  (where's the false-failure? guards.classify_response? response.success? something else?)
4. **One-line top change to ship next** (single sentence).

Output: markdown, ~60–120 lines max.  No preamble, use the 4 numbered headings.
