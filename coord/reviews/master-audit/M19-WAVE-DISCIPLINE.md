<!-- name=M19-WAVE-DISCIPLINE latency_ms=28512 error='' -->

## Score

1. **Correctness — 4/5.** The plan→execute→audit→closeout loop ran for W8: plan was authored post-panel, 8/8 items shipped, three audit sweeps ran, closeout committed. But the audit gate surfaced a load-bearing schema bug (EngineHealth Literal missing `quarantined`/`recovering`) that shipped in W7 and wasn't caught until W8 audit follow-through — the loop caught it late, not proactively.

2. **Robustness — 2/5.** The audit step itself is structurally unreliable: 3 rows flip PASS↔STOP with zero code change between sweeps 2 and 3. Two more persistently STOP across all three runs. A gate that gives different verdicts on identical input isn't a gate — it's a coin flip dressed as rigor. The discipline loop's weakest link is its own verification step.

3. **Operator-usability — 4/5.** Genuinely improved: `harness today` is readable, `preflight --fix` fixes things, runbook exists in non-Python language. The `--skip-engines` flag on preflight showing dead engines as `[OK]` even when the path is skipped is a minor confusion vector, but the operator trajectory is clearly upward.

4. **Test discipline — 3/5.** +32 tests in W8, 1576 total. But the schema bug — a Pydantic Literal silently rejecting writes behind `except Exception: continue` — shipped through W7 untouched. That's exactly the class of bug mutation testing or a type-checking lint should surface. Mutation kill rates weren't re-run in W8 either, so the top-5 table is stale since W7.

5. **Risk — 3/5.** The non-determinism isn't new (W6-PANEL precedent), but it's now affecting 3 of 8 W8 rows. Each wave that ships with a broken gate normalizes the breakage. W9's `avg-of-N` mitigation is the right bet, but until it lands, every future audit sweep is suspect.

6. **Top blocker.** Ship `W9-AUDIT-NONDETERMINISM-AVG` (the `--avg-of-N` flag) and re-run the W8 row set through it as a calibration baseline. If the averaged gate still flips, the problem is deeper than run variance. If it stabilizes, the discipline loop becomes trustworthy. Either way, you get signal. Without this, every future audit sweep is theater.

7. **Verdict — SHIP-WITH-FIXES.** W8's *deliverables* are solid and the operator trajectory is real, but the discipline loop's own audit gate is unreliable — fix the averaging before W9 closeout or the loop devolves into ritual without signal.
