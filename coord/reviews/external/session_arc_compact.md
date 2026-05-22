# Meta-review request — xaxiu-harness session 2026-05-22 (compact)

You are reviewing **process structure** of a multi-engine LLM dispatch harness.

## Context (compact)

- xaxiu-harness lets one human ("operator") use Kimi K2.6 / DeepSeek V4 Flash / Xiaomi MiMo (Pro + V2.5) as a coordinated dev team.  Claude (in Claude Code session) is the dev manager.
- Memory rules say Claude should DISPATCH work to engines (planning, packets, validation, merge, summaries only — 30 LOC ceiling).
- Operator override `feedback_xaxiu_harness_full_dev_authority` lifts the per-action approval gate but NOT the dispatch-first rule (`feedback_plan_first_dispatch_default`, saved today).
- 51 memory entries live in `~/.claude/projects/D--Projects/memory/` — shared across xaxiu-harness AND warehouse projects on disk.

## Session arc (what actually happened today)

1. Battle-test exposed 8 coord-pipeline defects. Claude fixed all 8 INLINE.
2. Engine fixes (timeout 120→600 s, DeepSeek thinking-ON default, MiMo SGP endpoint, max_tokens=32768). Inline.
3. Wave 2 (4 more defects: trusted_source, mimo Literals, run-id autogen, integrator squash). Inline.
4. Operator caught the inline drift: *"you decided to pivot in fixing certain areas yourself instead of having sub agents do it"*.
5. Corrective dispatch: 4 packets (`spec/samples/wave1-*.md`) → 3 shipped via engines (Kimi K2.6 + MiMo Pro + Kimi K2.6), 1 failed all engines.
6. Operator question: *"is this the true possible speed?"*

## Discovered structural issues during audit (already factual)

- **53% memory mis-scope**: 27 of 51 memory entries are warehouse-only, but all 51 load into every xaxiu-harness session.
- **Cross-project hook leak**: warehouse's `check-csv-stale.sh` fires inside xaxiu-harness sessions ~15 times today.
- **Dispatcher fallback even with force_engine**: `dispatch_packet(force_engine='kimi')` still iterates the full chain on failure, so a 60 s engine timeout becomes 120-240 s before returning.
- **Budget meter silent**: `(no dispatches)` despite ~30 real dispatches today — `record_dispatch` not being called from `dispatch_packet`'s main path.
- **10 KB packet ceiling**: all 3 engines disconnected at 60-69 s when asked to review a 10 KB packet.  Server-side timeout, not our client.

## Your job

Answer these 5 questions, terse + specific:

1. **Was the inline drift mostly Claude's role-discipline gap, or also a packet/dispatcher gap?**  (one paragraph)
2. **Throughput ceiling.** If Claude perfectly dispatched from minute 1, what's the realistic feature count in 8 hours?
3. **Memory + hook scoping fix.** Best path: per-project memory dirs / tagged filter / migration to new folder?  Pick one, justify in 3 lines.
4. **Packet shape evolution.** Read-set embedding + cli.py anchor-windowing worked.  What's the NEXT failure mode? (e.g. 10 KB review-packet → server disconnect at 60 s.)
5. **One-line top change to ship next.**

Output: markdown, no preamble.  ~80–200 lines.  Use the 5 numbered sections above as headings.  Be terse.
