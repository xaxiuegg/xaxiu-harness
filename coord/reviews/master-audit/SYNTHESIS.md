# Master audit — 40-reviewer synthesis

_Dispatched: 40 personas (20 MiMo + 20 Kimi), elapsed 193.9s_

State snapshot fed to each reviewer is at `_state_snapshot.md` in this directory.

_OK responses: 40/40_


## Per-persona responses

### K01-ONBOARDING

_latency: 135941ms_

## Score
1. **Correctness** — 3/5. Preflight returns 0 fails but surfaces three unrelated warnings; a “successful” run still leaves the fresh clone in an unusable state (unregistered loops, dead engines, observer timeout).
2. **Robustness** — 3/5. `--fix` and `engines-heal` exist, yet the onboarding path scatters recovery across disparate commands rather than one resilient funnel.
3. **Operator-usability** — 2/5. A non-technical operator must independently decide to ignore warnings, run `--fix`, run `loop start`, or debug an observer timeout before the first healthy tick; DPAPI seeding is invisible and `--profile non_technical` is not the default.
4. **Test discipline** — 2/5. 1,576 unit tests pass, but the golden-path “clone → first green preflight” integration for a non-technical operator is unguarded.
5. **Risk** — 4/5. High probability the operator misses loop registration or DPAPI setup, misinterprets warnings as errors, and abandons or misconfigures the harness.

6. **Top blocker** — Wire `harness install` (already labeled a “first-run wizard”) into `preflight` so a fresh clone detects an uninitialized state and routes the operator through one idempotent command that sets the non-technical profile, registers the loop task, seeds DPAPI, and quarantines dead engines.
7. **Verdict** — SHIP-WITH-FIXES. The recovery primitives exist, but the hand-off from clone to first trustworthy preflight still demands debugging rather than reading.

### K02-DOCS-CLARITY

_latency: 59650ms_

## Score

1. **Correctness — 3**  
   CLI help and `harness today` are accurate, but the runbook omits DPAPI seeding paths and stop-hook behavior still confuses auditors, so docs do not fully match system reality.

2. **Robustness — 3**  
   Recovery flows (`preflight --fix`, `engines-heal`) are documented, yet the runbook lacks guidance on DPAPI/key-loss failure modes and hook noise, leaving operators unprepared for common faults.

3. **Operator-usability — 3**  
   Plain-language CLI output is strong, but a non-technical operator still cannot onboard cold: the runbook hides where secrets come from and `--profile non_technical` is not the default.

4. **Test discipline — 1**  
   No automated regression tests for README, runbook, or spec clarity; the only guard is the non-deterministic MiMo audit, which is process, not test coverage.

5. **Risk — 4**  
   A docs gap that blocks a non-technical operator from rotating keys or understanding hook noise is a near-term ship-blocker for unsupervised operation.

6. **Top blocker**  
   Add the DPAPI seeding section and `--profile non_technical` default instructions to `docs/OPERATOR_RUNBOOK.md` (the W10 todo already flagged) so setup and recovery are fully visible.

7. **Verdict — SHIP-WITH-FIXES**  
   Operator-facing surfaces are 80 % there, but the remaining 20 % are exactly the gaps that strand a non-technical user on first contact.

### K03-FAILURE-MODES

_latency: 123251ms_

## Score
1. **Correctness** — 3 — Core fix/heal flows work after the schema patch, but persistent STOPs on hook noise and audit prompt mean spec edges still fail MiMo validation.
2. **Robustness** — 2 — Bare `except Exception: continue` in quarantine paths silently swallowed a Pydantic schema violation, a catastrophic failure-mode pattern that will recur under engine churn.
3. **Operator-usability** — 3 — Runbook and plain-language status exist, yet a non-technical operator faces immediate warning fatigue from dead-engine alerts, observer timeouts, and unregistered loops.
4. **Test discipline** — 3 — 1576 tests pass and mutation gate is green, but the schema/quarantine mismatch between dict stubs and Pydantic production reveals a critical cross-form integration hole.
5. **Risk** — 4 — Silent swallowing + non-technical operator + daily engine death/cooldown churn creates high-probability, unrecoverable first-week failure modes with ship-blocking blast radius.

6. **Top blocker** — Land a single hardening PR that replaces every bare `except Exception: continue` in preflight/heal paths with typed error surfacing and adds a Pydantic-native integration test for `engine_health` quarantine writes.

7. **Verdict** — SHIP-WITH-FIXES — Operator scaffolding is in place, but silent failure modes and persistent audit/hook STOPs guarantee a non-technical operator hits an unrecoverable fault within days.

### K04-CLI-ERGONOMICS

_latency: 90785ms_

## Score

1. **Correctness — 2/5** Taxonomy is broken: ~38 top-level verbs (lens spec expected 22), `loop`/`loops` collide, `engines-heal` mirrors `engines heal`, and `doctor`/`preflight` overlap.
2. **Robustness — 2/5** No visible typo correction or subcommand-Levenshtein guard; plausible mis-typings like `harness engine cooldowns` fail opaquely.
3. **Operator-usability — 2/5** Non-technical operator faces an undifferentiated flat list; `spec-init`, `spec-register`, `spec-verify` are separate incantations instead of a `spec` family, and `--help` lacks workflow grouping.
4. **Test discipline — 1/5** 1,576 tests pass, yet no CLI-ergonomics regression coverage is evidenced (no `--help` snapshot tests, no subcommand-discovery assertions).
5. **Risk — 4/5** Every wave adds top-level verbs rather than nesting; operator-readiness foundation from W8 will be undermined by CLI sprawl.

**Three-verb discoverability spot-check:**
- `engines`: 1/5 — `heal`, `cooldowns`, `reliability` are hidden as hyphenated top-level aliases, not listed under `engines`.
- `observer`: 2/5 — 12 subcommands exist but top-level `--help` only gives an abstract tagline.
- `coord`: 4/5 — `plan`, `run`, `integrate`, `status` are explicitly advertised in the short help.

**Top blocker:** Reify a true noun/verb hierarchy (`harness engines heal`, `harness spec init`) and prune duplicate top-level aliases; group `--help` by operator workflow.

**Verdict:** SHIP-WITH-FIXES. W8 operator-readiness gains are real, but the flat CLI surface is a self-inflicted maze that will trap the non-technical operator.

### K05-HONEST-READINESS

_latency: 78523ms_

## Score

1. **Correctness — 3/5.** The schema bug proved quarantine silently failed; persistent STOPs on W8-STOP-HOOK and W8-AUDIT-PROMPT show spec gaps remain unclosed.
2. **Robustness — 2/5.** Observer probe times out by default, dead engines warn on every preflight, and the old `except Exception: continue` pattern shows failure modes were masked, not handled.
3. **Operator-usability — 2/5.** The runbook is readable, but a non-technical operator seeing daily yellow warnings for dead engines and observer timeouts will not know whether to restart, ignore, or escalate.
4. **Test discipline — 3/5.** 1576 tests are theater when the audit gate gives different verdicts on identical commits; persistent STOP rows mean regressions can hide in noise.
5. **Risk — 4/5.** Thirty days of unsupervised operation guarantees the operator will learn to dismiss warnings, then miss the next load-bearing failure because signal-to-noise is broken.

6. **Top blocker.** A guaranteed all-green `harness preflight` on a correctly seeded system, plus a single `harness doctor --repair` that resolves yellow warnings automatically without editing JSON or understanding engine health schemas.

7. **Verdict.** SHIP-WITH-FIXES. The operator has a playbook, but the harness currently trains them to ignore yellow warnings on startup—which is exactly how silent failures become outages.

### K06-DOGFOOD

_latency: 59303ms_

## Score

1. **Correctness** — 3: Heavy dogfooding, yet a load-bearing schema mismatch silently broke every quarantine write, and persistent STOPs on hook and audit prompt reveal unfilled spec gaps in the meta-layer.
2. **Robustness** — 3: Self-healing paths masked Pydantic failures with `except Exception: continue`; observer probes timeout; the audit gate flips verdict on unchanged code.
3. **Operator-usability** — 3: Runbook and `harness today` exist, but preflight still surfaces dead engines, observer timeouts, and unregistered loops—noise a non-technical operator cannot action.
4. **Test discipline** — 3: 1576 tests pass, yet the quarantine bug escaped because test stubs used dicts while production used Pydantic models; tests didn't match reality.
5. **Risk** — 4: The meta-layer is becoming a tower of indirection; silent failures in self-heal plus non-deterministic audits risk alert fatigue or missed regressions within 30 days.

**Top blocker**: Harden all self-healing exception handlers to emit L4 toasts on unexpected schema/validation errors, eliminating `except Exception: continue` in fix/heal paths.

**Verdict**: SHIP-WITH-FIXES — extensive dogfood usage is healthy, but the self-monitoring loop is too noisy and too silent in the wrong places; harden before operator handoff.

### K07-DEAD-CODE

_latency: 100269ms_

## Score
1. **Correctness**: 2 — Only ~60% of the ~30 listed verbs are live; the rest are stubs or pending-wave scaffolding (`swarm-verify` truncates mid-string, `observer` probe times out, W8-STOP-HOOK is persistently STOP).
2. **Robustness**: 2 — The `quarantined` write path was dead code masked by bare `except Exception: continue`; dead-engine handling fails silently without the schema patch.
3. **Operator-usability**: 3 — `today` and `preflight --fix` work, but the help surface mixes live features with unfinished scaffolding the non-technical operator cannot distinguish.
4. **Test discipline**: 2 — 1,576 tests missed the silently failing quarantine path, and W8 skipped the mutation sweep, leaving scaffolded modules unaudited.
5. **Risk**: 4 — A non-technical operator will invoke a stub verb or trust a broken hook; confusion or state corruption is a near-term ship blocker.
6. **Top blocker**: A `--stub-audit` gate that hides every CLI verb whose help text is truncated, times out in preflight, or references an unshipped Wave prefix.
7. **Verdict**: SHIP-WITH-FIXES — cull the dead verbs and hardened hooks before handing this surface to an operator.

### K08-PERFORMANCE

_latency: 58591ms_

## Score
1. **Correctness** — 4/5: Functionally accurate, but preflight `--skip-engines` consistently breaches the ~5 s expectation by >25 % with no documented variance.
2. **Robustness** — 3/5: Observer probe timeout still blocks the gate for 5.8 s instead of degrading gracefully; loops check is similarly synchronous and heavy.
3. **Operator-usability** — 3/5: A non-technical operator running frequent preflights faces 6+ second stalls with no progress feedback or "what's slow" breakdown beyond raw ms.
4. **Test discipline** — 2/5: Zero automated latency/SLO regression tests for preflight, dispatch, or audit gate; 1,576 tests cover behavior but not performance budgets.
5. **Risk** — 3/5: Serial 60–90 s audit per row plus preflight SLO erosion creates a hard throughput ceiling of roughly one small wave per session.

6. **Top blocker** — Add latency telemetry + a hard 5 s enforced budget to `preflight --skip-engines` (cache/background the loops and observer probes, surfacing slow checks asynchronously).
7. **Verdict** — SHIP-WITH-FIXES. The operator-readiness foundation is solid, but the preflight latency regression and missing dispatch/audit latency observability must be fixed before W9 scale.

### K09-COSTS-BUDGET

_latency: 47032ms_

## Score

1. **Correctness — 2**  
   `budget` CLI exists but snapshot shows no per-session cost attribution; ledger wiring is opaque.

2. **Robustness — 2**  
   No cost-cap alarms, overrun circuit breakers, or pricing-drift guards visible in preflight or `today`.

3. **Operator-usability — 1**  
   `harness today` omits spend entirely; a non-technical operator has no obvious one-command answer for session cost.

4. **Test discipline — 1**  
   1,576 tests cite zero ledger-reconciliation or cost-accuracy coverage; mutation table ignores budget modules.

5. **Risk — 3**  
   Silent spend accumulation across Kimi/DeepSeek/MiMo with no meter visibility is a credible 30-day bill shock.

6. **Top blocker**  
   Add a plain-language cost stanza to `harness today` (or a `harness budget --last-session` human output) so the operator can read spend without interpreting a ledger.

7. **Verdict**  
   SHIP-WITH-FIXES: plumbing is present but the operator lacks a single, human-readable command to answer "how much did this session cost."

### K10-MULTI-ENGINE

_latency: 162802ms_

## Score

1. **Correctness — 2**: `--engine-fill` is operator-configurable rather than locked to `aggressive`, so the “keep Kimi slots full” policy is optional, not enforced; `deepseek:5` persisted past threshold without auto-quarantine.
2. **Robustness — 3**: Dead-engine detection, quarantine schema, and heal commands exist, yet remediation still surfaces as a manual preflight warning instead of an autonomous circuit-break.
3. **Operator-usability — 3**: Non-technical operators can run `engines-heal` and `preflight --fix`, but receive no visibility into Kimi subscription slot utilization vs. queue depth.
4. **Test discipline — 2**: No cited tests assert cooldown backpressure or Kimi backfill behavior; W8 skipped engine-area mutation sweep after the schema fix.
5. **Risk — 3**: Subscription waste (idle Kimi) and repeated dead-engine hits (DeepSeek ×5) create concurrent cost and reliability exposure.

**Top blocker**: Harden `engine-fill` to default/aggressive and add a `kimi_slot_waste` preflight probe so queued work never sits while subscription capacity is idle.

**Verdict**: SHIP-WITH-FIXES — primitives are landed, but policy enforcement is manual and dead-engine auto-remediation stops one step short of full autonomy.

### K11-AUDIT-NONDETERMINISM

_latency: 112933ms_

## Score

1. **Correctness** — 3: Identical commits yield PASS↔STOP flips; the gate cannot reliably separate correct code from incorrect.
2. **Robustness** — 3: The harness tolerates runtime faults, but the audit layer fails under model jitter, producing fragile verdicts.
3. **Operator-usability** — 2: A non-technical operator sees binary PASS/STOP in `harness today` that swing 0.40→0.85→0.40 with no code change; the signal is unusable.
4. **Test discipline** — 4: Strong unit and mutation coverage catch code regressions, yet no test guards against audit-prompt variance.
5. **Risk** — 4: Alert fatigue from noise will desensitize the operator to real blockers or waste cycles chasing phantom gaps.

6. **Top blocker** — Ship `W9-AUDIT-NONDETERMINISM-AVG` as `--avg-of-N=3` with variance-aware labels (HARD PASS / HARD STOP / REVIEW) in `harness today`.
7. **Verdict** — SHIP-WITH-FIXES: The harness is operationally sound, but the audit gate's noise floor currently exceeds its signal, so it must be calibrated with averaged sweeps before PASS/STOP labels are actionable.

### K12-REPLAY

_latency: 58534ms_

## Score

1. **Correctness** — 2. Help text claims v1/v2 reconstruction, yet no spec, sample output, or runbook step confirms it tells the right story.
2. **Robustness** — 2. No evidence of handling missing logs, partial coord runs, or v1/v2 schema drift; likely raw-dump or silent failure.
3. **Operator-usability** — 1. The non-technical operator has zero runbook guidance on when to invoke it, and the CLI description promises data, not decision archaeology.
4. **Test discipline** — 1. None of the 1,576 visible tests cover replay; regressions in reconstruction logic would slip through undetected.
5. **Risk** — 3. When a coord run fails, the operator will need narrative context and instead find an undocumented data hose, forcing escalation.

6. **Top blocker** — Add `replay --human` (plain-language timeline: what was decided, why, by whom) and an OPERATOR_RUNBOOK section naming the exact failure signature that triggers invocation.
7. **Verdict** — SHIP-WITH-FIXES. Daily pulse and preflight are operator-ready, but `replay` is a dark corner: it answers neither when to use it nor how to understand the output.

### K13-SESSION-HANDOFF

_latency: 78512ms_

## Score

1. **Correctness — 3**: `harness today` and the runbook provide static handoff context, but the snapshot shows no `session` output proving a proactive, actionable transfer recommendation fires when the loop yields.
2. **Robustness — 3**: `heartbeat` and `panic-dump` are present, yet if the loop crashes before emitting a handoff, the operator has no persistent loop-exit artifact to consult.
3. **Operator-usability — 4**: The plain-language `today` pulse and single-page runbook let a non-technical operator self-orient, though they must actively pull status rather than receiving a pushed handoff.
4. **Test discipline — 2**: With 1,576 tests and no visible coverage of `harness session` or handoff logic, a regression in transfer signaling would likely slip through undetected.
5. **Risk — 3**: A non-technical operator could fail to notice the loop has yielded control, leading to stalled work or unreviewed changes sitting idle.

**Top blocker:** Force the loop exit path to invoke `harness session --handoff` and write a persistent `SESSION_HANDOFF.md` checklist (shipped blockers, next required operator action).

**Verdict:** SHIP-WITH-FIXES — operator pull-based tools exist, but the loop still lacks an unmissable, push-style transfer packet that screams "take the wheel now."

### K14-LOOP-PRODUCTION

_latency: 62571ms_

## Score

1. **Correctness** — 3/5. `harness loop` verbs exist, yet preflight treats an unregistered loop as a warn-level notice, and the snapshot shows no `loop status` output confirming accurate self-reporting.
2. **Robustness** — 2/5. W5-M’s PID-sentinel covers coordinators, not the loop; zero evidence of auto-restart, state rehydration, or Task Scheduler watchdogging for the dev-loop process itself.
3. **Operator-usability** — 3/5. `harness loop start` is discoverable, but a non-technical operator has no proven `status` signal to distinguish “running” from “zombie,” and the runbook’s loop-recovery section is unverified.
4. **Test discipline** — 2/5. 1,576 tests pass, yet neither the audit sweeps nor the mutation manifest mention loop lifecycle coverage; there is no kill+restart regression test.
5. **Risk** — 4/5. Silent loop death halts all autonomous progress; without durable execution, the entire W8 operator-readiness stack is moot because the engine simply stops.

6. **Top blocker** — Harden `harness loop` into a supervised background task (e.g., Task Scheduler with auto-restart on failure) and add an integration test that SIGKILLs the loop process, then asserts `harness loop status` returns `running` within 30s.
7. **Verdict** — SHIP-WITH-FIXES. The loop primitive is callable but not operator-grade until it demonstrably survives a kill+restart without manual intervention.

### K15-COORD-V2-MATURITY

_latency: 60620ms_

## Score

1. **Correctness** — 2. Worktree and checkpoint primitives compile, but the integrator leaves the progress-stream broken after observer timeout and dead-engine quarantine, so unattended runs silently stall.
2. **Robustness** — 2. No cascading-fault recovery: a single engine death plus observer timeout collapses the unattended loop because neither auto-restarts nor fails over to a degraded-but-up state.
3. **Operator-usability** — 3. CLI surface is friendly, yet the non-technical operator must manually patch loop registration and observer health every morning—unattended autonomy is still aspirational.
4. **Test discipline** — 3. High unit count misses the overnight unattended scenario; the schema-silent-failure and persistent hook STOPs show the integration harness lacks a 24h bootstrap regression suite.
5. **Risk** — 4. Within 30 days an unattended run will halt on unregistered tasks or unhealed engines, confirming v2 coord is demo-ware with prod aspirations.

6. **Top blocker** — `harness install` must auto-register the dev-loop Task Scheduler entry and couple the observer to a watchdog that self-restarts on timeout, eliminating the two manual preflight warnings permanently.

7. **Verdict** — SHIP-WITH-FIXES. Multi-agent coordination is structurally sound, but the absence of self-bootstrapping loop and observer recovery means unattended operation remains a supervised demo, not production.

### K16-SPEC-CULTURE

_latency: 71940ms_

## Score

1. **Correctness — 2**: W8-STOP-HOOK’s spec claimed exclusions absent until follow-through commit `7081d93`, and the `EngineHealth.status` Literal omitted `quarantined`/`recovering` that production code was already writing.
2. **Robustness — 3**: Failure modes (schema rejection, hook noise) are patched in follow-throughs rather than anticipated in the original spec.
3. **Operator-usability — 3**: Runbook and `harness today` exist, but DPAPI seeding is invisible (W10 todo) and W8-OPERATOR-RUNBOOK criteria are soft enough to flip PASS/STOP.
4. **Test discipline — 4**: 1,576 tests catch code regressions, yet persistent STOPs on spec-audit rows prove acceptance criteria aren’t crisp enough to be spec-driven or automatable.
5. **Risk — 4**: W9’s 14-row backlog will amplify spec debt if implementation continues to outpace `spec/*.md`.

**Top blocker**: Gate every W9 row on a frozen `spec/*.md` that passes `harness spec-verify` before code is written; retroactively patch W8-STOP-HOOK and W8-PREFLIGHT-FIX specs to match commit `7081d93`.

**Verdict**: SHIP-WITH-FIXES — Spec culture is retroactive-edit, not lead; freeze specs pre-implementation or spec debt will outpace test coverage.

### K17-AUTHORITY-DISCIPLINE

_latency: 71760ms_

## Score
1. **Correctness**: 3 — Persistent STOPs on W8-STOP-HOOK and W8-AUDIT-PROMPT were overridden by precedent; the sole external check on dev authority is already compromised.
2. **Robustness**: 2 — Observer probe times out in preflight, MiMo flips PASS/STOP on identical code, and W8 skipped the full mutation sweep, so drift detection is unreliable.
3. **Operator-usability**: 4 — Runbook, `today`, and `preflight --fix` make daily ops accessible, yet the non-technical operator still cannot independently validate Claude's commits.
4. **Test discipline**: 3 — 1576 tests catch functional regressions, but coverage does not enforce boundaries on the dev-manager's unilateral authority.
5. **Risk**: 5 — Unilateral commit/push authority with a flaky, non-blocking observer is a ship-blocker; nothing stops a slow-motion authority failure.

6. **Top blocker**: Fix the observer probe timeout and make the audit gate truly blocking: require `--avg-of-3` MiMo runs ≥0.75 before any Wn row ships, with zero "accepted-as-shipped" waivers.
7. **Verdict**: SHIP-WITH-FIXES — Operator-facing features are ready, but the discipline layer is decorative until the observer is reliable and audit STOPs cannot be overridden.

### K18-SCOPE-CREEP

_latency: 50118ms_

## Score

1. **Correctness** — 3. Individual features pass local audits, but systemic correctness frays under 40+ CLI verbs and 309 tracker rows, as shown by the EngineHealth schema/quarantine mismatch that silently failed for multiple waves.
2. **Robustness** — 2. Broad surface breeds hidden rot: `except Exception: continue` masked total quarantine failure, and 1,576 tests failed to catch a Pydantic rejection that broke `preflight --fix` and `engines-heal`.
3. **Operator-usability** — 2. New `today` and runbook are helpful, yet the 40+ visible verbs still overwhelm a non-technical operator and the readiness panel voted no.
4. **Test discipline** — 2. Test count grew +32, but mutation kill rates barely clear the ≥3 gate; quantity is covering shallow coverage as scope expands.
5. **Risk** — 4. Every wave adds more verbs, state, and tests without retiring old ones; the harness is sprawling toward an unmaintainable "mini-OS" instead of converging on an operator-shippable core.

6. **Top blocker** — A published CLI verb freeze + retirement plan: demote or merge half the current commands (e.g., collapse `engines-*` into `engines`, move observer/orchestrator under `harness admin`) before W9 adds any new user-facing verbs.
7. **Verdict** — SHIP-WITH-FIXES. W8 shipped genuine operator-readiness wins, but the additive trajectory is unsustainable; scope must freeze and consolidate now or it will never converge.

### K19-INTERACTION-FRICTION

_latency: 69205ms_

## Score
1. **Correctness** — 3: Specs are met but validating them costs three MiMo sweeps per row due to non-determinism.
2. **Robustness** — 3: Runtime heals engines, yet the audit gate itself flakes, forcing manual operator-Claude rescue turns.
3. **Operator-usability** — 3: Runbook exists, but shipping still requires spec → dispatch → three audit rounds; not yet half the friction.
4. **Test discipline** — 3: Tests catch code regressions, but no test fails when the audit process itself regresses to three turns.
5. **Risk** — 4: Next-wave scale will multiply audit STOP noise into operator fatigue and tangible ship delays.

6. **Top blocker** — Ship W9-AUDIT-NONDETERMINISM-AVG with a `--avg-of-N 3` default so one dispatch replaces three manual audit sweeps.
7. **Verdict** — SHIP-WITH-FIXES: Operator-readiness is real, but the audit approval pipeline still consumes three operator turns per feature; halve that and it's production-grade.

### K20-NEXT-WAVE

_latency: 64593ms_

## Score

1. **Correctness — 3**  
Persistent STOPs on W8-STOP-HOOK and W8-AUDIT-PROMPT mean the detection layer does not yet meet its own spec; the schema-bug fix proves silent failures were slipping through.

2. **Robustness — 3**  
`except Exception: continue` masked a load-bearing schema mismatch for an unknown duration; observer probes time out; detection noise undermines failure response.

3. **Operator-usability — 4**  
Preflight --fix, `today`, engines-heal and the runbook clear W8 readiness blockers, though `--profile non_technical` still is not the default.

4. **Test discipline — 3**  
1576 tests pass and mutation rates exceed gates, yet the quarantine path had zero coverage for the invalid-Literal rejection that silently broke every health write.

5. **Risk — 4**  
W9 must stack-rank detection > operator UX > engine reliability > v2 maturity > scope reduction; without a deterministic audit gate, regressions slip in silently or reviewer trust collapses under false-positive fatigue.

## Top blocker

Ship `W9-AUDIT-NONDETERMINISM-AVG` and eliminate the two persistent STOP rows so the audit gate becomes a trustworthy signal rather than a source of noise.

## Verdict

SHIP-WITH-FIXES — operator readiness is good enough to proceed, but W9 must not layer new features atop an audit gate that cries wolf (or stays silent on real wolves).

### M01-INSTALL

_latency: 23674ms_

## Score

1. **Correctness** — 3. Preflight runs and `--fix` resolves git/pytest issues, but dead_engines warns immediately on a fresh clone where no keys exist yet; that's an expected state, not a real failure, yet the operator sees `[!]` with no "you need keys first" context.

2. **Robustness** — 2. The schema bug (Literal rejected `quarantined`/`recovering` silently swallowed by bare `except Exception`) is exactly the failure mode a fresh-install reviewer fears most — the fix shipped, but the pattern recurs: `_check_dead_engines` still fires on a keyless clone, observer times out because it's not running, loops warn because nothing's registered. Three warnings at first boot, none explained.

3. **Operator-usability** — 2. There is **no cold-start path visible in this snapshot**. No `pip install -e .`, no `pyproject.toml`, no "clone → install → run" sequence. The operator runbook (`docs/OPERATOR_RUNBOOK.md`) exists but isn't referenced until the final line of `harness today`. A non-technical operator cloning this repo doesn't know whether to run `pip install`, `poetry install`, or `python -m harness` directly. The CLI entry point is `python -m harness` — not mentioned anywhere in the preflight output.

4. **Test discipline** — 4. 1576 tests, mutation kill rates above gate, the schema bug caught by audit. But the `except Exception: continue` pattern that hid the quarantine bug is a test-discipline smell — the fix addressed the symptom, and no new test asserts "quarantined status actually persists."

5. **Risk** — 3. The cold-start story is invisible to the snapshot audience. Every new operator will hit the same wall: clone, stare at CLI help, guess at installation, get three warnings they can't interpret.

6. **Top blocker** — Add a `README.md` or `docs/COLD_START.md` with the exact 5-command path: clone → `pip install -e .` → set 3 API keys → `harness preflight --fix --skip-engines` → `harness today`. Without it, the operator runbook is unreachable.

7. **Verdict** — **HOLD.** The harness works once bootstrapped, but there is literally zero documentation for the first 5 minutes after clone — the exact window this lens audits.

### M02-CLI-COMPLETENESS

_latency: 49816ms_

## Score

| Dimension | Score | Justification |
|---|---|---|
| **Correctness** | 4 | Core verbs work as specced. Schema bug was load-bearing and got fixed. `doctor`/`preflight` split is semantically unclear in the help tree. |
| **Robustness** | 3 | Quarantine flow silently failed until caught; no `rollback` or `observer reset` for stuck states; `--skip-engines` is a manual escape hatch, not auto-degrade. |
| **Operator-usability** | 3 | `today`, `preflight --fix`, `engines-heal` are good on-ramps. But 22 top-level verbs + 60+ subcommands is high discovery friction for non-technical profile. `--profile non_technical` isn't the default. |
| **Test discipline** | 4 | 1576 tests, mutation kill rates ≥3 on all top-5 modules. Audit gate catches real regressions (schema bug). |
| **Risk** | 3 | Verb explosion makes the CLI hard to navigate blind. Missing lifecycle gap: no `rollback` for bad dispatches, no `upgrade` for harness updates, no key-rotation verb for the dead-engines path. |

## Top blocker

**Consolidate `doctor` into `preflight` and add `harness rollback`.** `doctor` and `preflight` are 80%+ overlapping (both check git, python, secrets); the split forces the operator to guess which one to run. A single `preflight` with `--fix` and `--quick` flags covers both. Meanwhile, the dead-engines fix mentions "rotate keys" but there's no `harness keys rotate` or `harness rollback <dispatch-id>` — a bad overnight dispatch currently has no undo path except `panic-dump` + ping engineering. Either verb closes a real lifecycle gap.

## Verdict

**SHIP-WITH-FIXES.** The CLI covers install → daily run → recover → retro → debug, but the 22-verb surface is bloated (4 verbs could be folded into `engines` subcommands; `doctor`/`preflight` should merge) and the missing `rollback` leaves a production hole that `replay` doesn't fill — `replay` reconstructs, it doesn't undo.

### M03-OPERATOR-DAILY

_latency: 20023ms_

## Score

1. **Correctness** — 4. Core mechanics (preflight, engines-heal, today) work, but audit non-determinism undermines reliability of the "done" signal.
2. **Robustness** — 4. Survives dead engines and schema bugs; audit flips (STOP↔PASS) with no code changes indicate fragile self-assessment.
3. **Operator-usability** — 3. Daily pulse (`today`) and one-command recovery (`preflight --fix`) land, but weekly/monthly cadences aren't supported by existing verbs—operator has no clear "what next" beyond daily.
4. **Test discipline** — 4. 1576 tests, solid coverage; but the audit layer itself (the system's own judgment) is non-deterministic, which tests don't catch.
5. **Risk** — 3. Operator trust erodes if audits flip without cause; the `status --human` alias and `preflight --fix` are load-bearing for adoption.

## Top blocker
Stabilize audit verdicts: either average-of-N sweeps or binary pass/fail thresholds. Non-determinism destroys operator confidence in the "done" signal—the system cannot self-assess reliably.

## Verdict
SHIP-WITH-FIXES: The operator-readiness foundation is usable for daily tasks, but inconsistent audit verdicts require a deterministic gating mechanism before the system can be trusted for autonomous cycles.

### M04-OBSERVABILITY

_latency: 33174ms_

## Score

1. **Correctness** — 3/5. Surfaces reflect state but `harness today` truncates after 110 items; operator can't see the full picture without digging into STATUS.csv.
2. **Robustness** — 3/5. Observer probe timeout shows one retry warning; preflight shows fixable warnings. No proactive alerting when surfaces degrade.
3. **Operator-usability** — 2/5. `harness today` is friendly, but default profile is technical, STATUS.csv is raw 309-row CSV, and dashboard requires manual start/stop. Non-technical operator must switch contexts.
4. **Test discipline** — 3/5. Observer has tests; status tracker is tested. Mutation testing covers dispatch and integration but observability surfaces not prioritized in mutation sweeps.
5. **Risk** — 2/5. Scattered surfaces mean operator might miss a quiet failure until it escalates. Not a ship-blocker but friction.

## Top blocker
Set `--profile non_technical` as the default so `harness today`, preflight, and status automatically show the human-friendly format without requiring the operator to remember a flag.

## Verdict
SHIP-WITH-FIXES — Observability is functional but the operator has to toggle between friendly and technical views; a default profile flip and a persistent dashboard would cut the digging in half.

### M05-ERROR-RECOVERY

_latency: 23231ms_

## Score

**Correctness**: 4/5 — Engine schema fix and preflight --fix work, but persistent audit STOPs on 2 rows suggest spec-compliance gaps in error recovery pathways.

**Robustness**: 3/5 — The schema bug fix shows critical error paths are now surfaced, but audit non-determinism could mask future recovery failures.

**Operator-usability**: 4/5 — `preflight --fix`, `engines-heal`, and runbook give clear recovery actions, but audit noise might undermine operator confidence.

**Test discipline**: 4/5 — +32 tests for W8, but mutation sweep not re-run means recovery-path regression detection is lagging.

**Risk**: 3/5 — Persistent audit failures could erode trust in error recovery guidance; operators may bypass recommended fixes.

**Top blocker**: Resolve the persistent STOP on W8-STOP-HOOK audit. If the audit gate itself can't reliably validate noise reduction, how can operators trust it to surface real error recovery needs?

**Verdict**: SHIP-WITH-FIXES — Core recovery flows work, but audit reliability issues need fixing before operators can confidently rely on the guidance system.

### M06-AUDIT-GATE

_latency: 58824ms_

## Score

| # | Dimension | Score | Justification |
|---|-----------|-------|---------------|
| 1 | Correctness | 3 | Gate caught real regressions (schema bug, MUTATION-ORCH), but ~30% of STOPs on unchanged code are false positives (ENGINES-HEAL, STATUS-HUMAN, OPERATOR-RUNBOOK flips). The 0.65–0.75 confidence band is a coin-flip zone. |
| 2 | Robustness | 2 | Same commit + same auditor → different verdict. Three flips across sweeps 2→3 with zero code diff. The gate is non-deterministic at the decision boundary, which is the *only* place reliability matters. |
| 3 | Operator-usability | 2 | A non-technical operator sees STOP/STOP/PASS on ENGINES-HEAL and can't distinguish "real regression" from "MiMo rolled a different number." Trust erodes fast. |
| 4 | Test discipline | 3 | The gate is eating its own dogfood — 3 sweeps, flip-tables published, `--avg-of-N` queued in W9. But no integration test asserts stability on fixed input, so the noise floor is only *documented*, not *eliminated*. |
| 5 | Risk (audit-gate lens) | 3 | Not a ship-blocker yet because operator precedent (W6-PANEL) already absorbed the noise. But if W10+ rows hit the 0.65–0.75 band, every wave gets a "3 STOPs — is it real?" cycle. W9-AUDIT-NONDETERMINISM-AVG is the critical path. |

**False-positive rate:** ~20–24% (4–5 of ~21 sweeps gave STOP on code unchanged since last PASS).
**False-negative rate:** Cannot be measured from this data — there's no independent "ground truth" audit to compare against. At least one TP (schema bug) proves the gate *can* catch silent failures. But a silent false negative is, by definition, silent.

## Top blocker

Ship **W9-AUDIT-NONDETERMINISM-AVG** (`--avg-of-N`) and **require it** for all Wn closeout verdicts. A single averaged score ≥0.70 = PASS, below = STOP. This collapses the flip-flop noise into one number and makes the audit gate auditable itself.

## Verdict

**SHIP-WITH-FIXES.** The gate catches real regressions (2 hard-PASS lifts prove it), but ~20–24% false-positive noise on unchanged code makes individual STOP verdicts unreliable — the operator cannot distinguish signal from MiMo non-determinism without the `--avg-of-N` stabilizer shipping in W9.

### M07-MUTATION-COVERAGE

_latency: 28836ms_

## Score

**Correctness (3):** The ≥3 gate is met for all 5 hot modules — the spec says what it says and the code delivers. But the spec itself is narrow: 5 modules out of ~40 production files get mutation coverage. The gate is correct *for its scope*; the scope is insufficient.

**Robustness (2):** W8 did not re-run the sweep. W9-MUTATION-MANIFEST has 3 warm-tier modules with `last_sweep_sha=null`. Three of the five tracked modules had 0.00 kill rate as recently as W6 and only recovered because they were explicitly targeted. No mechanism auto-fires a mutation run when a hot-module file changes — regressions land silently until the next manual sweep.

**Operator-usability (2):** A non-technical operator has no CLI verb to see which modules are mutation-tracked, what the kill rates are, or whether a sweep is stale. `harness today` and `harness status human` surface test counts and audit verdicts but not mutation coverage. The operator cannot distinguish "covered and green" from "never tested."

**Test discipline (3):** Tests exist that *generate* mutation scores, and 1576 tests pass. But 0 tests assert that the mutation manifest is consistent (e.g., "every `src/harness/**/*.py` appears in at least one tier"). The gate itself — "≥3 kill rate" — has no property-test verifying it's applied on every CI run or preflight cycle.

**Risk (3):** The sustainable bar is the real question. ≥3 is fine for a codebase with 5 tracked modules. At 10 modules, you need 10 sweeps. At 20, the sweep cost dominates. No tier graduation policy exists — modules never move from warm to hot. W10-FRESH-CANARY-MODULES is queued but unshipped, meaning 3 manifest gaps persist.

**Top blocker:** Execute `W10-FRESH-CANARY-MODULES` immediately (3 canary runs, ~30 min total) to populate `last_sweep_sha` for the 3 warm-tier nulls. Then add a preflight check: `mutation_manifest_completeness` that fails if any tier has `null` sha older than 7 days. This makes the ≥3 gate *self-enforcing* rather than manually refreshed.

**Verdict:** SHIP-WITH-FIXS. The gate works for the 5 modules it covers; the coverage gap and stale-sweep risk are real but addressable in one focused session.

### M08-ENGINE-RELIABILITY

_latency: 38757ms_

## Score

1. **Correctness** — 3. Quarantine/recovery lifecycle now implements the spec post-schema-fix (7081d93), but a bug that silently swallowed every quarantine write for weeks proves the spec was unmet until very recently.

2. **Robustness** — 2. The `except Exception: continue` that hid the schema bug is a **pattern-level hazard**. One was found; the question is how many remain. DeepSeek is currently dead (`deepseek:5`) and recovery hasn't been demonstrated end-to-end in production — only manually verified with `--skip-engines`.

3. **Operator-usability** — 4. `engines-heal` exists, `harness today` surfaces the blocker, and the runbook documents recovery steps. Minor gap: key-rotation vs. quarantine decision isn't guided in the CLI output itself.

4. **Test discipline** — 2. Tests passed *throughout* the broken-quarantine period because the same `except Exception: continue` masked failures in test stubs too. The follow-through explicitly notes stubs had to be taught to match Pydantic forms — meaning tests were validating a different code path than production ran.

5. **Risk** — 3. DeepSeek is dead *right now*. The schema fix is <1 commit old, the non-det audit on ENGINES-HEAL means we can't rely on automated verification, and autonomous overnight loops will degrade silently if a second engine fails while the recovery path has an undiscovered bug.

6. **Top blocker** — Systematic grep for `except Exception` with bare `continue`/`pass` in every engine-health, quarantine, and dispatcher-fallback path. The schema bug proves these patterns hide load-bearing failures. Each hit needs a logged warning or explicit re-raise. Estimate: 2 hours, eliminates the entire category.

7. **Verdict** — **SHIP-WITH-FIXES.** The single-engine-collapse path exists and the schema bug is patched, but the silent-swallow pattern that hid it for weeks is a systemic defect that must be hunted before we can trust the recovery lifecycle under real autonomous load.

### M09-SECURITY-POSTURE

_latency: 35131ms_

## Score

**Correctness — 4/5**: DPAPI key storage, JSONL+redaction logging, and `panic-dump` scrubbing are present and functionally correct. The redaction integrity gate (W9) landed. However, the DPAPI *seed* path is undocumented and unverified — `doctor` reports DPAPI as readable but never explains provenance, a gap acknowledged only as a W10 todo.

**Robustness — 2/5**: The EngineHealth `except Exception: continue` pattern that silently failed every quarantine write is a **class defect**, not a one-off. No evidence anyone audited DPAPI reads, redaction pipelines, or key-rotation paths for the same swallow-and-continue pattern. One such block in a redaction path means secrets leak to JSONL permanently with zero surface signal.

**Operator-usability — 3/5**: `harness env` reports per-key presence, `status --human` is readable, and the runbook is single-page. But a non-technical operator hitting a DPAPI seeding failure has no remediation path — `doctor` says "readable" without explaining where keys originate. Invisible until production breaks.

**Test discipline — 3/5**: 1576 tests + redaction integrity gate are solid foundations. Missing: DPAPI failure-mode tests, redaction pattern coverage completeness (does every new log sink inherit redaction?), and file-permission enforcement assertions (`0600` mentioned in the prompt but not in any shipped row I can verify).

**Risk — 4/5**: The silent-failure pattern is proven to hide load-bearing security bugs. The injection scanner question is unanswered — I see no explicit injection-scanning primitive in the CLI tree or shipped rows. Trust on `env` means any process inheriting the operator's environment sees all API keys; no scoping or least-privilege boundary exists.

**Top blocker**: Run a targeted grep for every `except Exception: continue` (and `except: pass`) in security-sensitive modules — DPAPI, redaction, key rotation, state writes — and replace each with explicit `logging.error` + surface to operator. The EngineHealth bug proves this pattern silently breaks security guarantees; the same class of bug is almost certainly hiding in a redaction path.

**Verdict**: SHIP-WITH-FIXES — the silent-failure audit is non-negotiable; one leaked API key in a JSONL log is an irreversible exposure.

### M10-STATE-ATOMICITY

_latency: 31126ms_

## Score

1. **Correctness**: 2 — W8 schema bug proves state writes silently swallowed failures for *weeks*; `except Exception: continue` is the anti-pattern that corrupts silently.
2. **Robustness**: 2 — W9-STATE-ATOMIC-WRITES committed but no evidence of write-temp+fsync+rename pattern; kill-9 during `engine_performance_log.jsonl` append or `engine_health` update leaves partial/truncated state with zero detection.
3. **Operator-usability**: 1 — `doctor`/`preflight` never validates state-file integrity; a corrupted `engine_health.json` silently feeds bad routing until operator notices phantom cooldowns weeks later.
4. **Test discipline**: 2 — no kill-9/mid-write simulation tests; the quarantine bug was caught by *audit sweep*, not by 1576 tests — that's a red flag for state-write coverage specifically.
5. **Risk**: 3 — silent state corruption during autonomous overnight loops can compound: one bad `engine_health` write → phantom quarantine → routing misbehavior → operator discovers Monday.

## State-atomicity specifics unresolved

- `db.sqlite`: no WAL-mode or journal-mode evidence; `PRAGMA integrity_check` absent from preflight.
- `*.json` files: JSONL append is natively non-atomic; `*.json` writes need write-replace pattern explicitly.
- `YAML configs`: PyYAML `safe_dump` to same path = truncate-then-write = data loss on kill-9.
- `StateFileCorruptError`: **never observed** in any sweep, test, or log — meaning either (a) it doesn't exist as a class, or (b) it exists but has zero test coverage. Either is a gap.

## Top blocker

Add `state_integrity` to preflight: validate every `state/*.json` parses, `db.sqlite` passes `PRAGMA integrity_check`, and all YAML configs load — *before* any autonomous dispatch fires. Without this, the W9 atomic-write commit is unverifiable in production.

## Verdict

**HOLD** — W9 landed atomic-write infrastructure but zero integration tests prove it works under kill-9, and the preflight gate has no state-integrity check to catch corruption before autonomous loops consume bad data.

### M11-CONCURRENCY

_latency: 36065ms_

## Score

1. **Correctness** — 3/5. W9-STATE-ATOMIC-WRITES + W9-STATE-FILE-LOCK landed, but the snapshot gives no proof the atomic-write pattern covers all shared state paths (engine_health JSON, engine_performance_log.jsonl, STATUS.csv). The schema bug fix is correct but the `except Exception: continue` that hid it may still exist in other write paths.

2. **Robustness** — 2/5. Preflight ThreadPoolExecutor checks run in parallel, but preflight --fix + engines-heal can quarantine engines concurrently with no mutual exclusion on engine_health writes. Coord supervisors share state files; observer reads them on its own cadence — no happens-before between observer tick and coordinator flush. Stale lock detection for `scheduled_tasks.lock` after crash not mentioned anywhere.

3. **Operator-usability** — 4/5. Concurrency is invisible to the operator by design, but the runbook doesn't warn against running `preflight --fix` while the autonomous loop is live — a plausible footgun.

4. **Test discipline** — 2/5. 1576 tests are almost certainly sequential. Zero evidence of parallel-execution stress tests, lock-contention tests, or TOCTOU regression tests. Mutation canary is spot-check (3 mutants), not concurrency-aware.

5. **Risk** — 4/5. Five subsystems (preflight, coord, observer, mutation sweeps, scheduled tasks) touch overlapping state files. The W9 atomic-write commit is < 1 week old and unproven under concurrent load. Windows file-locking semantics (mandatory vs advisory) add platform-specific hazard. A silent corruption in engine_performance_log.jsonl would poison dispatch routing for days.

## Top blocker

Add a concurrency stress test (`test_parallel_state_safety`) that simultaneously runs preflight --fix, engines-heal, coord status, and observer tick against shared state files, asserting no data corruption, no silent drops, and no stale-lock deadlock. Without it, the W9 atomic-write fix is aspirational, not verified.

## Verdict

**SHIP-WITH-FIXES** — The W9 atomic-writes commit addresses the worst race but lacks a concurrent-execution regression test to prove it; one stress test closes the gap between "fixed in theory" and "verified under load."

### M12-V2-COORD

_latency: 25255ms_

## Score

| Dimension | Score | Justification |
|---|---|---|
| **Correctness** | 3 | Coord modules pass tests and mutation gate, but W8 skipped the full mutation sweep—no fresh proof that orchestrator→integrator→worker contracts still hold after W8 refactors. |
| **Robustness** | 2 | The EngineHealth schema bug (silently swallowed by `except Exception: continue`) proves the integrator path has untested silent-failure modes. Coord's checkpoint/progress-stream contracts have no explicit invariant tests for partial-write scenarios. |
| **Operator-usability** | 3 | `harness today` surfaces dispatch-level events but **zero coord-level visibility**—the operator can't see where in the plan→worker→integrate cycle a run stalled. `coord status` exists in `--help` but isn't surfaced in the daily pulse. |
| **Test discipline** | 3 | 1576 tests pass, kill rates ≥3 on coord modules, but the mutation sweep is stale (last ran W7). No contract-level tests verifying the single-worker directive is enforced across worktree boundaries. |
| **Risk** | 3 | Cross-worker contract drift is the live risk: if worker A's output schema drifts from what integrator B expects, there's no explicit schema-contract assertion at the boundary. The `except Exception: continue` pattern that hid the EngineHealth bug may exist elsewhere in coord paths. |

## Top blocker

**Add explicit schema-contract tests at each coord boundary** (planner→worker output spec, worker→integrator result spec, integrator→coordinator summary spec). One integration test per boundary asserting the Pydantic models round-trip cleanly would catch the class of silent-failure bugs the EngineHealth incident exemplified. This alone would lift Robustness from 2→4 and Risk from 3→1.

## Verdict

**SHIP-WITH-FIXES** — Coord correctness is demonstrated at the module level but unproven at the contract level; one boundary-contract test suite per handoff point closes the gap the EngineHealth bug exposed.

### M13-PROXY-SAFETY

_latency: 24628ms_

## Score

**Through the PROXY SAFETY REVIEWER lens:**

| Dimension | Score | Justification |
|-----------|-------|---------------|
| **Correctness** | 3 | Proxy exists as CLI primitive (`harness proxy`), 4-key rotation + circuit breaker spec'd; but W9-PROXY-FAILURE-MATRIX (afed9ba) never proves the proxy is safer than direct HTTPS — it catalogs failure modes without showing the attack surface delta. |
| **Robustness** | 2 | Circuit breaker + auto-quarantine-on-flap is the right architecture, but **no evidence of adversarial key-exhaustion testing** — what happens when all 4 keys are quarantined simultaneously? The fallback path is unspecified in the snapshot. |
| **Operator-usability** | 2 | `harness --help` shows `proxy` with zero detail. Non-technical operator can't tell if proxy is active, healthy, or in circuit-open state. No `proxy status` surfaced in `harness today` or `preflight`. |
| **Test discipline** | 3 | 1576 tests, mutation kill ≥3 on engine modules; but proxy-specific failure-matrix tests (flap detection, key-exhaustion, circuit-open → half-open transitions) aren't evidenced. W9-PROXY-FAILURE-MATRIX commit name suggests analysis, not validation. |
| **Risk** | 4 | **If the proxy silently degrades to passthrough or blocks all traffic on 4-key exhaustion, it's strictly worse than direct HTTPS** — it adds latency and a single point of failure without proving the threat model it defends against is real. No kill-switch for direct-fallback is documented. |

## Top blocker

Ship a **proxy failure-mode matrix that proves the proxy's attack surface is smaller than direct HTTPS** — specifically: (a) what threat model justifies 4-key rotation vs. 1 key, (b) simultaneous-key-exhaustion behavior, and (c) circuit-open fallback to direct HTTPS or explicit halt. Without (a), the proxy is complexity theater.

## Verdict

**HOLD.** The proxy adds a single point of failure and key-management complexity but hasn't demonstrated it's safer than the thing it replaces — the failure-matrix commit catalogs modes without proving the net security delta is positive.

### M14-OBSERVER-DESIGN

_latency: 36144ms_

## Score
1. **Correctness** — 3. Observer is implemented and tested, but probe timeout in preflight indicates runtime reliability gaps.
2. **Robustness** — 3. Retries on next preflight are good, but persistent timeout suggests deeper responsiveness or scheduling issues.
3. **Operator-usability** — 2. 12 subcommands and technical timeout warnings overwhelm non-technical operators; needs clearer guidance.
4. **Test discipline** — 4. 41 tests cover observer functionality; timeout may be environmental rather than code defect.
5. **Risk** — 3. Observer is critical for authority audit; unreliability could allow escalations to slip or cause false alarms.

6. **Top blocker** — Fix observer probe timeout so preflight reliably shows `[OK] observer`; likely requires adjusting cadence, increasing timeout, or optimizing observer cycle.
7. **Verdict** — SHIP-WITH-FIXES. Observer integrity is load-bearing for autonomous-loop safety and must be dependable before wider rollout.

### M15-DASHBOARD-UX

_latency: 22038ms_

## Score

| Row | Score | Justification |
|---|---|---|
| **Correctness** | 2 | Dashboard is invoked exactly once (`harness dashboard-serve`) — zero visibility into what it renders, which APIs it hits, or whether it matches the operator's mental model. Correctness is unassessable. |
| **Robustness** | 2 | WebSocket at 7878 with no mention of reconnect handling, backpressure, or stale-state detection. `harness today` shows live engine warnings but no indication the dashboard mirrors this state. |
| **Operator-usability** | 3 | CLI surface (`today`, `doctor`, `engines-heal`) is well-designed for non-technical use. But the dashboard — the *visual* operator surface — has zero documented UX flow. Non-technical operator will likely ignore it. |
| **Test discipline** | 1 | No dashboard API tests, no WebSocket integration tests, no schema contract tests for `/v2/*` endpoints. The 1576 tests cover engine/coord/audit logic but not the presentation layer. |
| **Risk** | 4 | A cost panel the operator can't read is worse than none — it creates false confidence. If the dashboard silently drops WebSocket updates during an engine-dead event, the operator learns about it from CLI, not the thing they're staring at. |

## Top blocker

Ship a **one-page dashboard UX spec**: what each panel shows (status, cost, escalations, engine health), the /v2/* contract, and a screenshot/mockup. Without it, the dashboard is a code artifact nobody audits because nobody can articulate what it *should* do. This single doc would lift Correctness + Test discipline by ≥1 each.

## Verdict

**HOLD for dashboard scope.** The CLI operator surface is production-grade; the dashboard is an invisible, untested, undocumented black box running on a non-technical operator's machine. Ship the CLI; freeze dashboard until a reviewer can actually evaluate what it surfaces.

### M16-TEST-QUALITY

_latency: 32151ms_

## Score

**Correctness: 4/5** — Tests pass and mutations kill, but the `EngineHealth` schema bug *survived* 1544 tests undetected because `except Exception: continue` swallowed it. Behavioral correctness was asserted; error-path correctness was not.

**Robustness: 3/5** — The schema-bug silent-failure pattern (`except Exception: continue`) is the smoking gun. It means tests *did* exercise quarantine writes, but Pydantic validation errors were swallowed before any assertion could fire. Happy-path robust: yes. Failure-path robust: demonstrably not.

**Operator-usability: 4/5** — `harness today` and `harness preflight` are clean, plain-language surfaces. Irrelevant to my lens directly, but readable error messages reduce support load, which frees test-budget time.

**Test discipline: 3/5** — 1576 passing is table stakes. The real question is **mutation kill rate coverage**: only 5 modules swept (W6), no W7/W8 re-sweep despite 8 new rows shipping. Three random modules I'd audit:

| Module (random pick) | Rating | Why |
|---|---|---|
| `engines/heal.py` (W8-ENGINES-HEAL) | ⚠️ Weak | Quarantine writes passed through the broken `EngineHealth` schema — tests only passed because exceptions were swallowed. Behavioral? Mock-heavy with dict stubs vs Pydantic production paths. |
| `preflight/fix.py` (W8-PREFLIGHT-FIX) | ✅ Decent | 3 fix functions + `FixOutcome` struct; L4 toast wiring tested. But `--skip-engines` path masks what actually fires in production. |
| `cli/status_human.py` (W8-STATUS-HUMAN) | ⚠️ Untested edge | CLI output formatting rarely gets snapshot/diff tests; `--since-hours N` boundary likely only mocked. |

**Risk: 3/5** — The `except Exception: continue` pattern is almost certainly duplicated elsewhere. Without a W7/W8 mutation sweep, I can't confirm kill rates held. Dead test code: the old `observer_tick` stub (removed in W5) and any W7-era quarantine tests that assert on the *pre-fix* `Literal["up","degraded","down"]` schema are now testing a dead contract — they pass vacuously.

## Top blocker

**Run a targeted mutation sweep on `engines/heal.py` and `preflight/fix.py` with the new `quarantined`/`recovering` states.** The fix landed, but the test that *would have caught the original bug* still doesn't exist — no test asserts that `engine_health.json` actually contains the expected status after `--fix`. Add one behavioral integration test that reads the file post-fix and asserts on the written value. This lifts test discipline from 3→4 and correctness from 4→5.

## Verdict

**SHIP-WITH-FIXES.** The silent-exception-into-schema-mismatch bug class is real and likely repeated; one integration test that asserts on *file contents* post-quarantine-write closes the gap that let 1544 tests miss a load-bearing bug for an entire wave.

### M17-DOCS-ACCURACY

_latency: 33745ms_

## Score

1. **Correctness** (3/5) — Docs claim "8/8 shipped" but the audit roll-up itself shows persistent STOPs on 2 rows; `harness today` shows 27 STOPs total — the closeout normalizes this as "non-determinism" rather than calling it what it is: the audit gate is unreliable.
2. **Robustness** (3/5) — Schema bug fix is real and load-bearing, but `preflight --skip-engines` snapshot still shows `dead_engines` as `[!]` — if the fix works, this output contradicts the claim. The doc's "manual verification" assertion can't be reproduced from the snapshot.
3. **Operator-usability** (4/5) — `harness today` is genuinely plain-language. Runbook exists. But 40+ CLI verbs in `--help` overwhelm a non-technical operator, and W10-PROFILE-AWARE-DEFAULTS confirms the profile default still isn't landed.
4. **Test discipline** (3/5) — +32 tests for 8 shipped items is thin. Mutation kill rate wasn't re-run in W8 despite the closeout calling it out. Persistent STOPs on W8-STOP-HOOK and W8-AUDIT-PROMPT suggest the audit infrastructure itself lacks regression coverage.
5. **Risk** (3/5) — Governance risk: the doc frames audit non-determinism as "accepted per W6-PANEL precedent," effectively making the quality gate advisory-by-default. If the gate doesn't gate, what does?

## Top blocker

Resolve the persistent STOPs on W8-STOP-HOOK and W8-AUDIT-PROMPT — either fix them or formally downgrade the audit gate from "required for done" to "advisory" in CLAUDE.md. Right now the doc simultaneously claims every row must pass audit *and* ships rows that never pass. That's a spec-vs-practice lie that will confuse every future session.

## Verdict

**SHIP-WITH-FIXES** — the operator-readiness Track B deliverables (preflight --fix, today, engines-heal, runbook) are genuinely useful and address real W8-panel blockers, but the closeout doc overstates certainty by packaging audit failures as "non-determinism" rather than unresolved gaps, and the audit gate itself needs a policy fix before it can be trusted as a quality control.

### M18-STATUS-CSV-DISCIPLINE

_latency: 30397ms_

## Score

| Criterion | Score | Justification |
|---|---|---|
| **Correctness** | 3 | STATUS.csv *tracks*, but 3 rows shipped with non-det audit verdicts violate the "every Wn gets a MiMo audit before done" policy — ship status contradicts policy. |
| **Robustness** | 2 | No staleness detection; a row can sit `todo` forever or flip audit verdicts indefinitely with no automated flag or operator-visible warning. |
| **Operator-usability** | 3 | Notes are long and commit-SHA-heavy; a non-technical operator skimming 309 rows gets signal-buried in noise. Header says "~280 rows" — file is 309. |
| **Test discipline** | 2 | No test asserts STATUS.csv schema invariants (valid transitions, non-empty updated-date, audit-verdict consistency). `W9-ONCOMMIT-HOOK-CRLF` touches the CSV hook but doesn't validate semantic integrity. |
| **Risk** | 3 | Tracker drift is silent — next wave inherits stale `shipped` rows whose audit verdicts are "Non-det (PASS once, STOP twice)". Confidence compounds, not resets. |

## Top blocker

**Enforce a hard rule: rows cannot be marked `shipped` unless their audit verdict is deterministic PASS (≥2 consecutive sweeps, same commit).** Add a `harness status lint` subcommand that checks: (a) every `shipped` row has an associated PASS verdict in its note or audit log, (b) no row's `Updated` timestamp is >72h stale for `in_progress` rows, (c) header row count matches actual row count. The 3 non-det rows (ENGINES-HEAL, STATUS-HUMAN, OPERATOR-RUNBOOK) should be re-classified `shipped-pending-audit` until the `--avg-of-N` gate (W9) lands and confirms them. This single lint would lift Correctness from 3→4 and Risk from 3→2.

## Verdict

**SHIP-WITH-FIXES** — The tracker *exists* and *renders*, but it's drifted into "commit every action, audit later" territory; the non-det shipped rows and the stale header count are live symptoms, not hypotheticals.

### M19-WAVE-DISCIPLINE

_latency: 25821ms_

## Score — Wave Discipline Lens

| Dimension | Score | Justification |
|---|---|---|
| **Correctness** | 3/5 | Loop is formally followed (plan→execute→audit→closeout) but audit verdicts are non-deterministic — 3 rows flip PASS↔STOP on identical code, making the gate decorative rather than load-bearing. |
| **Robustness** | 2/5 | The `except Exception: continue` in quarantine writes shipped undetected until audit sweep 2; audit non-determinism means real bugs and noise are indistinguishable at gate time. |
| **Operator-usability** | 4/5 | Runbook, `harness today`, `preflight --fix`, `engines-heal` — all genuine operator-readiness lifts. Persistent STOPs on these rows are auditor noise, not UX gaps. |
| **Test discipline** | 3/5 | 1576 tests, +32 net. But zero tests caught the silent EngineHealth schema failure; the audit (not the test suite) found the load-bearing bug. |
| **Risk** | 3/5 | Non-deterministic audit gates risk two failure modes: (a) real bugs get PASS-by-luck and ship; (b) clean code gets STOP-by-luck and blocks. Both compound across waves. |

## Top Blocker

**Ship W9-AUDIT-NONDETERMINISM-AVG (`--avg-of-N`) and re-run the 3 non-det rows as the validation case.** Until the audit gate produces stable verdicts on unchanged code, the plan→execute→audit→closeout loop has a broken leg — operators can't trust the audit as a shipping decision.

## Verdict

**SHIP-WITH-FIXES.** The wave-discipline loop is structurally sound — all 8 rows shipped, closeout doc is thorough, follow-through commits address real bugs — but the audit gate's non-determinism degrades it from a reliable quality gate to a coin flip, which will erode operator trust if left unresolved into W9+.

### M20-RISK-PROFILE

_latency: 38180ms_

## Score
1. **Correctness** 3 — Core ops work, but 2 persistent audit STOPs and 3 non-det rows indicate spec-misalignment in the detection/audit layer.
2. **Robustness** 3 — Schema bug fix was load-bearing and good. However, MiMo audit non-determinism is a major fragility; the system's quality gate is probabilistic.
3. **Operator-usability** 4 — Runbook, `preflight --fix`, and `harness today` are solid wins. The persistent STOPs on the runbook and status human (non-det) suggest residual gaps.
4. **Test discipline** 4 — +32 tests, mutation canary running. The audit non-determinism itself is a testing problem that W9 aims to address.
5. **Risk** 4 — **Audit gate unreliability** is the top risk. 3 of 8 W8 rows have non-deterministic PASS/STOP verdicts with no code change, making the gate untrustworthy for holding the line. This directly threatens correctness.

**Top blocker**: Ship the `--avg-of-N` audit flag (W9-AUDIT-NONDETERMINISM-AVG) and use it as the default gate. Until the audit verdict is stable, the harness cannot be trusted to catch real regressions.

**Verdict**: SHIP-WITH-FIXES. The operator-readiness foundation is valuable, but the audit layer's non-determinism is a critical weakness that must be stabilized before claiming production readiness.
