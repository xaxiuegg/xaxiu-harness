# Master audit — 40-reviewer synthesis

_Dispatched: 40 personas (20 MiMo + 20 Kimi), elapsed 213.2s_

State snapshot fed to each reviewer is at `_state_snapshot.md` in this directory.

_OK responses: 40/40_


## Per-persona responses

### K01-ONBOARDING

_latency: 72271ms_

## Score

1. **Correctness — 2/5** — `env-wizard`, `--fix`, and the runbook exist, but no golden path is surfaced at clone time; the operator must independently discover docs/OPERATOR_RUNBOOK.md and learn about `--fix` after already failing.
2. **Robustness — 2/5** — Preflight fails hard (exit code 4, opaque jargon) on a fresh machine with missing API keys or an uninitialized DPAPI store, rather than auto-invoking the wizard or offering one-command recovery.
3. **Operator-usability — 2/5** — Thirty-plus CLI verbs in `--help` overwhelm first contact; a non-technical operator lacks a visible 3-step funnel and must hunt for the handful of commands that matter for day one.
4. **Test discipline — 2/5** — 1,576 unit tests pass, yet no CI job simulates a fresh Windows clone → first green `harness preflight` end-to-end, so onboarding bit-rot is invisible until a human attempts it.
5. **Risk — 4/5** — The fail-rate of a first unassisted attempt is likely 60–80%; operators will abandon before they find the buried runbook.

6. **Top blocker** — Add a root `README.md` with a literal copy-paste quickstart (or a `harness onboard` verb that chains dependency check → `env-wizard` → `preflight --fix`), collapsing the decision tree to one command.

7. **Verdict** — **SHIP-WITH-FIXES**: the operator primitives are real but undiscoverable; the first 60 seconds after clone still leaks non-technical users.

### K02-DOCS-CLARITY

_latency: 72061ms_

## Score

1. **Correctness — 4** — Docs track shipped behavior (runbook links `engines heal`, DPAPI section uses analogies), but advanced W9/W10 flags risk outrunning runbook coverage.
2. **Robustness — 3** — Inline fix hints and dead-engine recovery exist, yet no unified troubleshooting matrix guides operators through cascading failures.
3. **Operator-usability — 4** — Plain-language `today` pulse and non-technical DPAPI prose hit the audience, though the 29-verb CLI tree buries the daily-driver subset.
4. **Test discipline — 3** — `lint-spec` + SHA verification catch structural spec drift, but README/runbook prose lacks automated regression coverage beyond noisy MiMo audit.
5. **Risk — 2** — Rapid W9/W10 CLI expansion threatens runbook currency; non-deterministic audit noise masks real doc-debt signal.

**Top blocker** — A curated "Operator Daily Driver" quick-reference card (≤7 verbs) extracted from the 29-command CLI tree; current surface area overwhelms the non-technical audience the runbook targets.

**Verdict** — SHIP-WITH-FIXES: Audience-aware docs foundation is strong, but verb sprawl and fragmented troubleshooting guidance need consolidation before non-technical operators can self-serve reliably.

### K03-FAILURE-MODES

_latency: 104845ms_

## Score
1. **Correctness — 4** — Top 7 modes (freq×impact): 1) git_clean hard-blocks autonomy (blast: loop off, recovery: `preflight --fix`, TTR 2m), 2) observer probe timeout (blast: daily `[!]` fatigue, recovery: re-run preflight, TTR 1m), 3) dead_engine quarantine silent-fail (blast: dispatch storm, recovery: `engines heal`, TTR 3m), 4) stash-needed dirty tree (blast: auto-block, recovery: `--fix`, TTR 2m), 5) DPAPI/secrets missing (blast: total auth fail, recovery: `env-wizard`, TTR 10m), 6) audit STOP noise (blast: false alarm, recovery: rerun/ignore, TTR 5m), 7) canary false-positive (blast: revert panic, recovery: manual review, TTR 15m). All mapped to CLI verbs except 6/7.
2. **Robustness — 3** — Modes 2 and 6 are chronic flapping warnings with no backoff; mode 3 was a silent schema failure now patched but revealed `except: continue` swallowing.
3. **Operator-usability — 4** — Runbook and `harness today` give non-technical recovery paths for modes 1–5; modes 6–7 still require engineering context to interpret.
4. **Test discipline — 4** — 1576 tests caught mode 3 once surfaced; no automated test for mode 2 observer-timeout race or mode 6 MiMo variance.
5. **Risk — 3** — Modes 2+6 will fire daily; within 30 days the operator will normalize ignoring `[!]` and STOPs, masking a real mode 1/3/5 failure.

6. **Top blocker** — Harden the observer probe with retry/backoff and downgrade its preflight result from `[!]` to soft advisory so mode 2 stops crying wolf.
7. **Verdict** — SHIP-WITH-FIXES — High-frequency failure modes have fast CLI recovery, but daily flapping warnings (modes 2, 6) will erode operator trust before day 30 without a quieter gate.

### K04-CLI-ERGONOMICS

_latency: 85454ms_

## Score

1. **Correctness** — 3. Functional, but the flat 38-verb surface with fractured namespaces (`engines-heal` vs `engines`, `spec-init` with no `spec` group) breaches the ergonomic consistency implied by operator-readiness specs.
2. **Robustness** — 2. No visible typo tolerance or collision guard; a non-technical operator mistyping `engine` instead of `engines` gets no corrective nudge.
3. **Operator-usability** — 1. `--help` is an ungrouped wall; three random samples: `coord` hints at subcommands in its description (2/5), `engines` hides `heal`/`cooldowns` as hyphenated top-level commands (1/5), and `observer` lists 12 subcommands with zero top-level hint (1/5).
4. **Test discipline** — 1. Thousands of tests exist, yet none enforce CLI taxonomy, help formatting, or verb-naming conventions.
5. **Risk** — 4. High probability of operator confusion between `engines-heal` and `engines heal`, missing `--fix` flags, and inability to browse commands without the runbook open.

6. **Top blocker** — Collapse hyphenated top-level verbs into nested subcommands (`harness engines heal`, `harness spec init`, `harness env wizard`) and add logical groups to `--help`.
7. **Verdict** — SHIP-WITH-FIXES: the core works, but the flat CLI namespace is a daily tax on the non-technical operator that directly undermines Track B goals.

### K05-HONEST-READINESS

_latency: 176929ms_

## Score

1. **Correctness** — 3. Core flows function, but persistent audit STOPs on STOP-HOOK and AUDIT-PROMPT show the harness still fails its own spec on gating code.
2. **Robustness** — 3. Preflight shows an observer probe timeout and a git_clean hard fail; the silent schema bug reveals overly broad exception swallowing that may hide other failures.
3. **Operator-usability** — 2. A non-technical operator will freeze or panic when preflight returns FAIL, an observer warning, and 27 unexplained audit STOPs in their daily pulse.
4. **Test discipline** — 3. 1576 tests missed a load-bearing Pydantic Literal mismatch that silently broke every quarantine write because production exception paths were unexercised.
5. **Risk** — 4. The observer is the only independent check on unsupervised full-dev authority; its timeout is a ship-blocker that blinds the operator to runaway automation.

**Top blocker:** Harden the observer probe to eliminate timeouts and guarantee `harness preflight --fix` exits cleanly green without operator interpretation; autonomy cannot start on a yellow-red gate.

**Verdict:** HOLD — a non-technical operator cannot be left alone for 30 days when the oversight layer is flaky and the daily dashboard dumps undifferentiated STOP noise on them.

### K06-DOGFOOD

_latency: 62500ms_

## Score

**Correctness — 3**  
Ships features reliably, but the audit gate persistently STOPs its own hook and prompt tuning, indicating the spec-to-verification loop is self-inconsistent.

**Robustness — 3**  
Healing, fallback, and quarantine exist, yet `except Exception: continue` swallowed schema violations and the observer probe times out—silent failures in the self-monitoring layer.

**Operator-usability — 4**  
`today`, `status human`, and the runbook are genuinely accessible, but audit non-determinism forces a non-technical operator to ignore red flags, eroding trust.

**Test discipline — 3**  
1576 tests and a mutation canary show volume, yet the `EngineHealth` schema regression and audit-flip noise both escaped automated detection in the meta-layer.

**Risk — 3**  
The harness is becoming a tower of indirection where process (STATUS.csv at 310 rows, audit panels, canary manifests) could outpace product; audit drift threatens autopilot legitimacy.

**Top blocker**  
Ship `W9-AUDIT-NONDETERMINISM-AVG` with `--avg-of-N ≥ 3` and hard-fail only on consensus, eliminating MiMo noise so the audit gate can judge itself.

**Verdict**  
SHIP-WITH-FIXES: the dogfood loop is productive but the meta-layer currently cannot reliably audit its own audits, creating a recursive credibility gap.

### K07-DEAD-CODE

_latency: 183679ms_

## Score

1. **Correctness — 2/5** At least 8 of ~37 visible verbs carry wave-ID scaffolding, `start` is a naked stub, and `today` is live yet absent from `--help`, so the manifest is materially false.

2. **Robustness — 2/5** Ghost verbs (`today`) and duplicate aliases (`engines-heal` / `engines heal`) create bifurcated paths; stubs fail silently or opaquely under operator use.

3. **Operator-usability — 2/5** A non-technical operator depends on `--help`; ticket-number descriptions and missing entries force runbook dependency for basic discovery.

4. **Test discipline — 2/5** 1576 tests guard logic but none appear to assert CLI-tree completeness or stub absence, allowing dead surface code to persist.

5. **Risk — 3/5** Scaffolding debt will confuse incident response and erode trust as the operator discovers unlisted verbs and stubs; fix before next wave.

6. **Top blocker** — One CLI-hygiene commit: strip wave IDs from all `--help` strings, delete or implement the `start` stub, and register `today` / `status human` in the top-level Click group so `--help` becomes a truthful manifest.

7. **Verdict** — SHIP-WITH-FIXES. The harness works, but its CLI surface is still a construction site; the operator cannot trust the verb tree they see.

### K08-PERFORMANCE

_latency: 78253ms_

## Score

1. **Correctness — 3/5** Preflight --skip-engines hits 5995 ms with an observer timeout, missing the ~5 s target, while the audit gate is locked at a stated 60–90 s per row.
2. **Robustness — 3/5** The dead-engine quarantine now writes correctly, but latent 5 s observer timeouts and prior silent schema drops show degradation paths under latency pressure aren’t fully hardened.
3. **Operator-usability — 3/5** `harness today` reads clearly, yet forcing a non-technical operator to absorb a 6 s preflight and hour-long serial audit gates strains the feedback loop.
4. **Test discipline — 2/5** 1 576 tests guard correctness, yet no visible performance regression suite protects the 5 s preflight budget or the 60–90 s audit ceiling.
5. **Risk — 4/5** Serial 60–90 s audit per row hard-caps Wave throughput; as the 310-row STATUS.csv backlog grows, the long-pole latency will stall the session.

6. **Top blocker** — Parallelize the MiMo audit row loop with a `ThreadPoolExecutor(max_workers=4)` to collapse per-Wave audit from ~12 min serial to ~90 s wall-clock.
7. **Verdict — SHIP-WITH-FIXES** Operator readiness is genuine, but the throughput ceiling is a hard pacing constraint that must be broken before the harness can scale to larger Waves.

### K09-COSTS-BUDGET

_latency: 40683ms_

## Score

1. **Correctness** — 2 — `budget` verb exists but snapshot shows no per-session cost output or ledger validation; operator cannot answer "what did this session cost" in one command.
2. **Robustness** — 2 — No evidence ledger handles write failures or token-skew; the W8 EngineHealth silent-schema bug shows similar data paths can fail undetected.
3. **Operator-usability** — 1 — `harness today` surfaces zero cost data; non-technical operator has no runbook step for spend checks and no proven one-command cost query.
4. **Test discipline** — 1 — 1,576 tests cite no budget/ledger coverage; mutation sweeps ignore cost modules.
5. **Risk** — 5 — Autonomous loops across three paid engines without real-time spend visibility is a runaway-budget ship-blocker.

6. **Top blocker** — A single human-readable `harness budget today` command (or `--costs` flag on `today`) printing per-engine and total session spend, backed by at least one pytest on ledger arithmetic.
7. **Verdict** — HOLD — the harness can spend money autonomously but cannot yet show the operator what was spent; ship when cost visibility matches dispatch velocity.

### K10-MULTI-ENGINE

_latency: 78263ms_

## Score

1. **Correctness — 2**: Engine-health schema silently rejected quarantine writes until W8; slot-fill flag exists but no evidence Kimi slots are actively kept full.
2. **Robustness — 2**: A bare `except Exception: continue` masked every failed engine-health write; fixed but the pattern may linger in other engine paths.
3. **Operator-usability — 3**: `engines-heal` and `engines-cooldowns` exist, yet the operator cannot see whether Kimi is under-utilized or why a cooling engine was still routed.
4. **Test discipline — 2**: 1,576 tests missed a load-bearing Pydantic Literal mismatch in `EngineHealth`, and no test proves cooldowns block dispatch.
5. **Risk — 4**: Subscription waste from unverified slot-fill logic plus untested cooldown gates; the recent silent-quarantine bug signals state-machine fragility.

6. **Top blocker**: Add `test_dispatch_respects_cooldown`—an integration test proving the router skips cooling engines and logs the fallback choice.
7. **Verdict**: SHIP-WITH-FIXES. The engine-lifecycle layer recently concealed silent failures and still offers no proof that slot-policy or cooldown enforcement are exercised under test.

### K11-AUDIT-NONDETERMINISM

_latency: 150166ms_

## Score
1. **Correctness** — 3. The harness executes correctly, but the audit gate contradicts itself on identical commits, so its verdicts are not reliably correct.
2. **Robustness** — 2. A gate that yields PASS and STOP for the same SHA under replication is brittle; robustness requires stable output under identical input.
3. **Operator-usability** — 3. The operator can drive the CLI, but audit roulette creates toil—forcing reruns or training them to ignore STOPs.
4. **Test discipline** — 3. Strong unit coverage (1576 tests), yet no golden-set test enforces verdict stability across repeated audits of a fixed commit.
5. **Risk** — 4. Next 30 days: real gaps may be dismissed as MiMo noise, while false STOPs burn review cycles on harmless rows.

6. **Top blocker** — Codify the shipped DeepSeek-primary + --avg-of-N infrastructure into a binding panel protocol: require ≥3 runs, discard outliers, enforce σ<0.10 and mean confidence ≥0.75 before a PASS/STOP is recorded.
7. **Verdict** — SHIP-WITH-FIXES. The harness is operator-ready, but a quality gate noisier than its signal is a liability; calibrate it to a stable, consensus-based standard before relying on it for ship decisions.

### K12-REPLAY

_latency: 60380ms_

## Score
1. **Correctness** — 3: The command exists for v1/v2 reconstructions, but zero operator-facing artifacts (runbook, `today`, preflight) describe when to invoke it, so the decision-archaeology promise is unfulfilled.
2. **Robustness** — 3: The tool likely tolerates truncated logs, yet the operator's mental model is fragile—without guided entry points they will not use it under pressure.
3. **Operator-usability** — 2: Completely absent from `harness today` suggested actions and the runbook excerpts shown; indistinguishable from a debug utility for engineers, not a non-technical operator.
4. **Test discipline** — 2: No test row or canary sweep validates the operator replay journey; a regression in CLI flags or output schema would only be caught by chance.
5. **Risk** — 3: The next time an engine quarantines or a dispatch loops, the operator lacks self-service archaeology, forcing escalation to engineering for decisions that replay data already holds.

6. **Top blocker** — Add a `--human` flag to `replay` that emits a numbered decision narrative (why engine X, why stop, what diff) and link it from `harness today` whenever audit STOPs or dead engines appear.

7. **Verdict** — SHIP-WITH-FIXES: The harness is operator-ready for day-to-day driving, but `replay` is a dead verb until decision-archaeology is surfaced in the daily pulse and runbook for non-technical users.

### K13-SESSION-HANDOFF

_latency: 134593ms_

## Score
1. **Correctness** — 3: `session` exists but snapshot shows no output or autonomous-loop integration, so the proactive-transfer spec is unverified.
2. **Robustness** — 3: Exit codes and fallback CLIs are clear, yet no evidence the session monitor captures state if the loop crashes ungracefully.
3. **Operator-usability** — 4: `today` and `preflight` give excellent plain-language blockers and exact commands, but lack a proactive "why you have control" narrative.
4. **Test discipline** — 2: Thousands of tests pass, but the snapshot shows no test coverage for session-handoff or proactive transfer logic.
5. **Risk** — 3: Without demonstrated auto-handoff, a non-technical operator may not notice loop pause or understand next steps.

6. **Top blocker** — Integrate `harness session` into the loop exit path to auto-print a structured handoff packet (last action, blockers, recommended command) on every pause.

7. **Verdict** — SHIP-WITH-FIXES: Strong operator UX exists, but the session-handoff monitor is an unverified stub and proactive loop-to-operator transfer is not demonstrated.

### K14-LOOP-PRODUCTION

_latency: 78022ms_

## Score

1. **Correctness** — 2. `loop` CLI entry exists, yet `init/tick/start/stop/status` subcommands are invisible in help, runbook, and preflight, leaving the promised surface unverified.
2. **Robustness** — 2. Preflight checks the scheduler task is armed, but there is no demonstrated loop-state durability or graceful tick-drain on `stop`/`kill`.
3. **Operator-usability** — 2. The operator can read `today` and run `preflight`, but cannot directly `start`, `stop`, or query loop status without leaving the harness CLI.
4. **Test discipline** — 2. No loop-lifecycle or kill-restart regression tests are visible in the 1,576-test suite or mutation manifest.
5. **Risk** — 4. Absence of a verified loop control plane is a near-term ship-blocker for unattended autonomous operation.

6. **Top blocker** — Harden and expose `harness loop start/stop/status --human` plus a preflight check confirming graceful tick-drain and Task Scheduler re-arm after simulated kill.
7. **Verdict** — SHIP-WITH-FIXES. The loop functions but its productized lifecycle surface is not yet operator-grade or kill+restart proven.

### K15-COORD-V2-MATURITY

_latency: 73753ms_

## Score

1. **Correctness** — 3. Core verbs ship, but persistent STOPs on hook/prompt and the silent schema bug show failure-path correctness is unreliable.
2. **Robustness** — 3. `except Exception: continue` masked total quarantine failure; observer timeout kills unattended starts.
3. **Operator-usability** — 4. Runbook and `harness today` help, but 30+ CLI verbs and unfixable observer warnings still bury a non-technical user.
4. **Test discipline** — 3. High count, yet dict-stub tests completely missed a Pydantic schema rejection that broke production quarantine.
5. **Risk** — 4. Silent failure patterns plus non-deterministic audit gate equal high regression escape probability in unattended mode.

**Top blocker** — Add one integration test that writes real Pydantic `EngineHealth` through the quarantine path and lint-ban bare `except Exception:` in production code; the W8 bug proves dict stubs give false confidence.

**Verdict** — SHIP-WITH-FIXES. The unattended shell is real, but silent exception swallowing and a persistently STOPped hook mean v2 is still demo-ware with ambitions, not production-ready.

### K16-SPEC-CULTURE

_latency: 70977ms_

## Score

1. **Correctness — 2**  
   The W8-PLAN spec at `9aea866` preceded its implementation rows, yet the `EngineHealth` schema (`Literal["up","degraded","down"]`) was stale against the quarantine logic, causing silent failures; persistent MiMo STOPs on W8-STOP-HOOK and W8-AUDIT-PROMPT signal residual drift.

2. **Robustness — 2**  
   `spec-verify` and `lint-spec` provide provenance tracking, but the commit hook (W8-STOP-HOOK) is a persistent audit failure and needed retroactive exclusion tuning, showing the spec gate frays under real repo churn.

3. **Operator-usability — 4**  
   Non-technical operators can scaffold, lint, and SHA-verify specs via `harness spec-init / lint-spec / spec-verify` without touching Python.

4. **Test discipline — 2**  
   Every Wn row gets a MiMo audit, but identical commits produce PASS/STOP flips (W8-ENGINES-HEAL, STATUS-HUMAN), so the gate detects noise more reliably than drift.

5. **Risk — 3**  
   If the audit gate is perceived as random, developers will silence or skip it, and specs will diverge from code just as the `EngineHealth` schema did.

6. **Top blocker**  
   A deterministic `spec-verify --fresh` pre-commit check that maps each `spec/*.md` acceptance-criteria bullet to an existing CLI verb, schema field, or test path, replacing MiMo as the sole drift detector.

7. **Verdict** — SHIP-WITH-FIXES. Spec-first process exists but lacks a trustworthy mechanical freshness check; once deterministic, the culture will stick.

### K17-AUTHORITY-DISCIPLINE

_latency: 88349ms_

## Score

1. **Correctness** — 3: The observer—the spec-mandated check on dev-manager authority—times out and its audits flip PASS/STOP on identical commits, so the oversight spec is not reliably met.
2. **Robustness** — 2: With full commit authority and a discipline layer that degrades to warnings (observer timeout) and noise (audit non-determinism), the harness cannot survive a plausible runaway dev-manager episode.
3. **Operator-usability** — 4: Runbook and `today` are operator-friendly, but the audit output is inscrutable (real STOP vs. noise), leaving the non-technical operator without a trusted brake pedal.
4. **Test discipline** — 3: 1,576 passing tests cover features, yet no test exercises the authority boundary (e.g., “observer rejects illicit commit”); mutation kill rates remain barely above gate.
5. **Risk** — 5: Over 30 days, unfettered commit/push authority plus a flaky automatic auditor is a ship-blocker: there is no deterministic circuit-breaker preventing long-horizon drift.

6. **Top blocker** — Harden `harness preflight` to treat observer timeout as a hard FAIL (not a warn) and mandate the W10 `--avg-of-N` DeepSeek audit pass before any autonomous loop tick resumes.

7. **Verdict** — HOLD: Full dev authority without a deterministic, blocking discipline check is an unacceptable long-horizon risk; the observer must be a reliable circuit-breaker before shipping.

### K18-SCOPE-CREEP

_latency: 64097ms_

## Score

1. **Correctness** — 3. W10 items are shipping inside a W8 closeout; wave boundaries have dissolved, so correctness is fragmenting across an unbounded surface.
2. **Robustness** — 3. Twenty-eight CLI verbs and a 310-row STATUS tracker multiply failure modes faster than any single wave can harden them.
3. **Operator-usability** — 2. A non-technical operator cannot navigate a 28-command tree; the runbook treats sprawl as inevitable rather than curbing it.
4. **Test discipline** — 2. 1,576 tests is a vanity metric when mutation tracking covers only five modules and persistent STOPs remain on foundational audit/hook rows.
5. **Risk** — 4. The harness is accelerating toward a feature-monolith; without a freeze gate it will never reach "done."

**Top blocker**: Impose a hard CLI verb freeze for W11 and publish a deprecation plan for overlapping commands (e.g., `doctor`/`preflight`, `coord`/`loop`) to force subtraction.

**Verdict**: SHIP-WITH-FIXES. It functions, but it is sprawling toward never-done; operator readiness requires ruthless convergence, not more verbs.

### K19-INTERACTION-FRICTION

_latency: 46496ms_

## Score

1. **Correctness — 4/5**  
   Deliverables match specs, but persistent MiMo STOPs on STOP-HOOK and AUDIT-PROMPT force spurious operator-Claude triage turns after code is already sound.

2. **Robustness — 3/5**  
   Relies on human override (W6-PANEL precedent) to survive audit noise; no automation absorbs non-determinism, so the process fractures under scale.

3. **Operator-usability — 4/5**  
   Runbook, `harness today`, and `--fix` shrink operator surface area, yet the audit ritual still demands technical judgment to dismiss flip-flops.

4. **Test discipline — 2/5**  
   Zero coverage on interaction cost (turns per feature, sweep variance); friction is invisible until closeout retrospectives.

5. **Risk — 4/5**  
   Wave 9’s 14-row backlog with a manual 3-sweep audit loop will choke throughput or burn operator patience.

6. **Top blocker**  
   Land an auto-averaging audit gate (`--avg-of-N` with automatic sweep-and-settle) so one dispatch returns a converged verdict, eliminating per-sweep operator-Claude turns.

7. **Verdict**  
   SHIP-WITH-FIXES — Core operator UX is ready, but the manual multi-sweep audit ritual must be automated before the Wave 9 backlog lands.

### K20-NEXT-WAVE

_latency: 44273ms_

## Score
1. **Correctness** — 3: Persistent STOPs on STOP-HOOK and AUDIT-PROMPT show the detection layer itself is still unreliable.
2. **Robustness** — 3: Silent schema quarantine bug persisted for waves; observer timeouts show failure modes still escape.
3. **Operator-usability** — 4: Runbook, `today`, and `engines heal` unblocked the non-technical operator.
4. **Test discipline** — 3: 1576 tests exist, but audit gate flips PASS/STOP on identical commits, eroding signal trust.
5. **Risk** — 4: Undependable detection is a near-term ship-blocker; regressions can slip in silently.

## Plus
6. **Top blocker** — Wave 9 must prioritize **detection** first. Stack-rank: detection > operator UX > engine reliability > v2 maturity > scope reduction. The audit gate needs deterministic DeepSeek-primary averaging (`W9-AUDIT-NONDETERMINISM-AVG` is queued but unshipped), and the stop-hook must reach persistent PASS. Without hardened detection, every later wave builds on sand.
7. **Verdict** — SHIP-WITH-FIXES: operator day-to-day is viable, but detection must be hardened before any scope expansion.

### M01-INSTALL

_latency: 16133ms_

## Score

1. **Correctness**: 3 - Preflight gate works but cold-start path incomplete; operator would hit git_clean block with no auto-fix.
2. **Robustness**: 4 - Survives engine failures (engines-heal) but initial setup assumes git knowledge.
3. **Operator-usability**: 2 - Non-technical operator stuck at first preflight failure; CLI help is technical jargon-heavy.
4. **Test discipline**: 5 - 1576 tests, mutation canary, audit sweeps catch regressions.
5. **Risk**: 3 - Cold-start friction risks operator abandonment before harness demonstrates value.

**Top blocker**: Add `--fix` handling for `git_clean` that either auto-commits with a standard message or provides interactive git guidance for non-technical operators (currently just advises "commit or stash").

**Verdict**: SHIP-WITH-FIXES — The harness is robust and well-tested, but a non-technical operator will get stuck at the first preflight git_clean failure without clearer remediation guidance.

### M02-CLI-COMPLETENESS

_latency: 38801ms_

## Score

**Correctness: 4/5** — The verb tree covers every lifecycle phase. The quarantine schema bug (silently swallowed `quarantined` status) was load-bearing and is fixed. `doctor` and `preflight` overlap with no documented distinction — one is redundant or orphaned.

**Robustness: 3/5** — The W8 schema fix (`EngineHealth` Literal missing `quarantined`/`recovering`) means *every* prior `preflight --fix` quarantine silently failed. That's a foundational robustness gap that existed for weeks. Fixed now, but it reveals insufficient integration-test coverage on the write-path.

**Operator-usability: 3/5** — `today`, `env-wizard`, `preflight --fix`, and the runbook are strong. But 40+ verbs with three overlapping execution paths (`loop`, `orchestrator`, `coord`) and two overlapping health checks (`doctor`, `preflight`) overwhelm the non-technical operator. No lifecycle grouping in `--help`.

**Test discipline: 4/5** — 1576 passing, mutation kill ≥3 on all top-5 modules. Audit-gate policy is enforced. Persistent STOPs on STOP-HOOK and AUDIT-PROMPT suggest the audit infrastructure itself needs dogfooding.

**Risk: 2/5** — No ship-blocker. The non-determinism is accepted with a queued mitigation. Missing verbs (`uninstall`, `rollback`, `pause`) are convenience gaps, not safety gaps.

**Top blocker** — **Collapse `doctor` into `preflight` or document the distinction in `--help`.** Add lifecycle groupings to the help output (`## Setup`, `## Daily`, `## Recover`, `## Debug`). The non-technical operator's first 10 minutes with `harness --help` should map to the runbook's sections. Today it's an alphabetical wall of 40+ verbs with no entry point.

**Verdict: SHIP-WITH-FIXES.** The CLI is functionally complete across the lifecycle, but verb-tree sprawl (three execution verbs, two preflight verbs, no grouping) and the now-fixed-but-revealing quarantine schema bug indicate the operator-facing surface needs a focused deduplication pass before handoff.

### M03-OPERATOR-DAILY

_latency: 15408ms_

## Score

1. **Correctness: 3** — The verbs exist (`preflight`, `today`, `engines-heal`, `daily`) but the critical flow is broken: `preflight --skip-engines` still shows `[X] git_clean` as a hard blocker, meaning the operator's *first morning action* fails every time unless they manually commit. The runbook says "run preflight" but doesn't tell them what to do when it fails with uncommitted files.

2. **Robustness: 2** — No retry/degraded-mode for preflight (observer timeout shows `[!]` then counts toward verdict). The `today` command shows 48h of dispatches with no grouping — 121+ lines is not scannable. If the operator runs `preflight --fix` and it hits the git_clean blocker, it just fails; no partial-fix path exists.

3. **Operator-usability: 2** — The operator's morning flow should be: `preflight → today → act`. But `preflight` returns a hard FAIL (exit code 4) on git_clean which the operator can't fix (they can't author Python, and the runbook doesn't cover "stash your in-progress work"). `today` dumps raw timestamps with no prioritization. There's no `harness morning` or single "here's what I need to do right now" command — the operator must stitch 3 commands together and interpret results.

4. **Test discipline: 3** — 1576 tests exist, but none test the *operator's actual morning sequence end-to-end*. Preflight-fix tests verify the fix functions fire, not that the operator's UX path from "preflight fails" to "preflight passes" is coherent. The `daily` verb (W10) is listed but its acceptance criteria aren't auditable here.

5. **Risk: 4** — The operator runs this system daily. If preflight always fails on git_clean, they'll either ignore it (defeating the gate) or stop checking. The `today` overwhelm (121+ unsorted entries) means they'll stop reading it. Within 30 days, the operator cadence collapses into "just run the loop and hope."

6. **Top blocker** — Ship a `preflight --auto-stash` mode (or make `--fix` handle git_clean by stashing) so the operator's first command *succeeds*. Without this, every morning starts with a red X the operator cannot resolve alone.

7. **Verdict: HOLD** — The verbs exist but the operator's daily flow is broken at step one: preflight hard-fails on an issue the non-technical operator cannot fix, and no degraded path or clear guidance exists.

### M04-OBSERVABILITY

_latency: 17927ms_

## Score
**Correctness**: 4 – mostly does what it claims, but persistent audit STOPs and observer timeout show gaps.
**Robustness**: 3 – schema bug fixed, but observer timeout and non-deterministic audit sweeps indicate fragility under failure.
**Operator-usability**: 4 – runbook, `harness today`, and `preflight --fix` are clear, but observer timeout and missing `status --human` surface hurt.
**Test discipline**: 4 – 1576 tests, mutation kill rates above gate, but audit non-determinism suggests tests may miss regressions.
**Risk**: 3 – observer timeout and audit flakiness could erode operator trust, not a ship-blocker yet.

## Top blocker
Fix the observer probe timeout (`[!] observer             observer probe timed out (5s)`) so `harness preflight` passes cleanly and the operator sees a fully green gate.

## Verdict
SHIP-WITH-FIXES – the system is functional for a non-technical operator, but observable gaps (observer, audit flakiness) need closure before hands-off trust is earned.

### M05-ERROR-RECOVERY

_latency: 54254ms_

## Score

1. **Correctness** — 4. The load-bearing schema bug (`EngineHealth.status` silently rejecting `quarantined`/`recovering`) was real, found, and fixed in `7081d93`. The quarantine→recover→clear flow now works end-to-end. Deduction: the bug existed for at least one wave before detection.

2. **Robustness** — 3. The `except Exception: continue` pattern that masked the schema bug is a code-smell the fix didn't fully extinguish — similar silent-swallow patterns elsewhere could hide future failures. The `preflight --fix` L4 toast path now works, which is good. But the operator has no instrumentation to detect "fix ran but didn't actually fix."

3. **Operator-usability** — 3. `engines-heal`, `today`, and `preflight --fix` are genuinely operator-driveable. But `git_clean` shows `[X]` after `--fix` with the same message — the operator runs the documented fix and still fails, with only a "Commit or stash" hint and no `preflight --fix` auto-resolution. **That is a dead-blocker for a non-technical operator.**

4. **Test discipline** — 3. 32 net tests added; the schema bug was caught by audit, not by tests. Tests assert "no exception" but not "engine_health row actually mutated" — the same class of silent-failure gap that caused the original bug.

5. **Risk** — 3. The `git_clean` dead-blocker is live right now (exit code 4 in preflight output). If the operator encounters it during an autonomous-mode start, they're stuck unless they know git.

6. **Top blocker** — **Make `git_clean` auto-fixable by `preflight --fix`**: stash dirty tracked files (or at minimum run `git stash push -m "preflight auto-stash"`). Right now the fix function exists but the preflight output still says "Run to fix: Commit or stash" — the operator runs `preflight --fix`, sees `[FIXED] git_clean`, reruns preflight, sees the same `[X]`, and is dead.

7. **Verdict** — **SHIP-WITH-FIXES.** The `git_clean` fix is a one-commit task and the only real operator-blocking dead-end in the snapshot; everything else is auditable noise or cosmetic.

### M06-AUDIT-GATE

_latency: 30628ms_

## Score

**Correctness (3/5):** The gate correctly lifted W8-PREFLIGHT-FIX from STOP→PASS after the schema-bug fix — genuine true-positive detection. But 3/7 rows flipped verdict with **zero code change** between sweeps 2→3, which means the gate is right ~57% of the time on first read. A gate that's a coin-flip on 43% of rows isn't reliably correct.

**Robustness (2/5):** Non-determinism is the dominant failure mode. No `--avg-of-N` stabilization exists yet (queued W9-AUDIT-NONDETERMINISM-AVG, not shipped). The gate also has no self-calibration: it cannot report its own confidence interval or flag when a verdict is marginal (0.55–0.75 band). Three persistent/STOP rows (ENGINES-HEAL, STATUS-HUMAN, OPERATOR-RUNBOOK) produced 6 conflicting verdicts across 2 unchanged commits — that's the gate breaking, not the code.

**Operator-usability (2/5):** `harness today` surfaces "34 PASS, 27 STOP" with no resolution mechanism. A non-technical operator sees 44% STOP rate, can't distinguish signal from noise, and has no `audit explain` verb. The operator runbook says "every Wn row gets a MiMo audit before done" but doesn't tell the operator what to do when the audit contradicts itself.

**Test discipline (2/5):** Zero tests gate the audit gate's own stability. There's no golden-set regression test ("given this fixed commit, the gate must return ≥0.80 PASS"). Without that, the gate can drift unchecked. The 28 existing audit-engine tests validate plumbing, not verdict consistency.

**Risk (4/5):** Two risks compound: (1) operators learn to ignore STOPs → real regressions (like the W8 schema bug) get waved through; (2) the persistent STOP on W8-STOP-HOOK/AUDIT-PROMPT blocks those rows permanently even when improvements landed. Both are happening simultaneously right now.

**Top blocker:** Ship a golden-set stability test — 3–5 fixed commits with known-good verdicts, run the gate against them, fail CI if the gate flips. This is the minimum artifact to prove the gate's own integrity.

**Verdict:** SHIP-WITH-FIXES. The gate caught one load-bearing bug (schema/quarantine) proving it *can* work, but its 43% non-determinism rate means it's currently unreliable as a release gate — a regression-silent gate and a false-alarm gate produce the same operational outcome: operator distrust.

### M07-MUTATION-COVERAGE

_latency: 35754ms_

## Score

1. **Correctness**: 4 — Top-5 modules clear the ≥3 gate, but the full sweep wasn't re-run in W8, and the manifest notes modules with 0 kill-rate (observer/cycle) that need pattern expansion.
2. **Robustness**: 3 — The mutation canary and manifest exist, but MiMo audit non-determinism (which drives mutation checks) is a fragile layer; the `--avg-of-N` fix is queued but not shipped.
3. **Operator-usability**: 4 — The operator never directly touches mutation coverage, but the system's reliability underpins autonomous mode trust. The runbook and `harness today` abstract this well.
4. **Test discipline**: 4 — Mutation-orchestrator tests exist and the W8 schema-bug fix landed with tests. However, we lack proof that mutations kill bugs in the newly added W8 features (preflight-fix, engines-heal).
5. **Risk**: 3 — The main risk is coverage stagnation as the codebase grows. Without re-running the full sweep and expanding patterns for all warm-tier modules, the gate becomes a historical artifact, not a current guarantee.

## Top blocker

Run a full mutation sweep (not just canary) on the current HEAD and update `coord/mutation_targets.yaml` with fresh kill-rates for all modules. This would reveal which modules are currently untested and allow the ≥3 gate to be enforced globally, lifting my score by ≥1 on Correctness and Risk.

## Verdict

SHIP-WITH-FIXES. The ≥3 gate is currently met for the top 5, but the system's credibility as a regression net depends on continuous, comprehensive mutation sweeps—a practice not yet normalized.

### M08-ENGINE-RELIABILITY

_latency: 35283ms_

## Score

**Engine Reliability Reviewer — single-engine-collapse lens**

1. **Correctness** — 3/5: Schema bug fix (`EngineHealth` Literal missing `quarantined`/`recovering`) was load-bearing and resolved. But the quarantine flow was silently failing *every* write until W8 audit sweep caught it — meaning the production engine layer ran broken for potentially weeks. Correctness is now *claimed*, not yet *proven* across all states.

2. **Robustness** — 3/5: Post-fix, `engines-heal` walks the recovery chain correctly (dead→quarantined→recovering→blocked). Dispatcher fallback (W5-O: retry-on-different-engine) handles the primary collapse case. However, zero tests validate the end-to-end cascade: *engine goes down → alarm fires → heal quarantines → dispatcher skips → operator sees toast*. The `_check_dead_engines` excluding already-quarantined is correct, but `engines-heal` has no timeout/retry if `read_engine_health` itself fails during recovery.

3. **Operator-usability** — 3/5: `harness engines-heal` is a clean verb. The L4 toast fires. But non-det audit scores (PASS/STOP/STOP) mean *neither the operator nor I can trust that the module behaves as specified* — MiMo itself can't reach stable verdict on it.

4. **Test discipline** — 3/5: 1576 tests pass, dispatcher.py mutation kill-rate 17.30 is excellent. But the quarantine schema bug evaded all tests — `except Exception: continue` swallowed Pydantic rejection silently. No integration test exercises `preflight --fix` → `preflight --skip-engines` roundtrip and verifies the dead-engine warning *actually clears*.

5. **Risk** — 3/5: The non-determinism on W8-ENGINES-HEAL (the only row *directly* in my scope) means I cannot confirm the module is audit-clean. If a *second* engine collapses while the first is `recovering`, the current heal walk has no documented handling.

6. **Top blocker**: Add a **roundtrip integration test** — `read_engine_health` returns `{"status": "down"}` → `preflight --fix` quarantines → next `read_engine_health` returns `quarantined` → `engines-heal` marks `recovering` → subsequent preflight shows `[OK]`. This one test would have caught the schema bug *and* would anchor the non-det audit score.

7. **Verdict**: **SHIP-WITH-FIXES.** The schema fix is real and critical, but the engine layer's only proof-of-correctness is a single manual verification and three contradictory audit runs — one integration test closes the gap.

### M09-SECURITY-POSTURE

_latency: 31646ms_

## Score

**Correctness (3/5):** DPAPI + env-wizard path is documented and functional; redaction integrity test exists (W9); but `panic-dump` secret-scrubbing is untested — no evidence of a redaction-canary that verifies output before it leaves the process.

**Robustness (2/5):** L5 DPAPI fallback path is a blind spot — what materializes when DPAPI is broken? If it falls back to plaintext env vars or an unprotected `secrets.json`, that's your leak. The `except Exception: continue` pattern discovered in the quarantine schema bug tells me the same anti-pattern likely exists near secrets.

**Operator-usability (4/5):** `harness env-wizard` + `harness env` + DPAPI section in runbook is solid for non-technical operators. Rotation flow documented. L5 fallback surfaced as "call engineering" — correct.

**Test discipline (2/5):** Redaction-integrity-test exists but no mutation kill-rate data for `redact/` or `secrets/` modules — they're not in the top-5 or even warm-tier canary. The injection scanner (W8-AUDIT-PROMPT) scores 0.25 STOP and is **not load-bearing** — it's a post-hoc review tool, not a pre-commit gate. If an engine returns a dispatch containing raw DPAPI-decrypted material, no scanner catches it before commit.

**Risk (3/5):** Modified tracked files (`git_clean` fail) could include secrets in working tree. The `git status` detector (W5-P) catches edits but not content. A `.env` or `secrets.json` staged for commit has no pre-commit content-scan.

## Top blocker

Add a **pre-commit hook that scans staged content for DPAPI-decrypted patterns** (API key regex, `secrets.json` content hashes). The redaction-integrity-test proves the *regexes* work; wire them into `git diff --cached --name-only` filtering. One concrete file: `hooks/pre-commit` calling the existing redaction patterns against staged blobs. This closes the path where secrets leak through version control — the only unmonitored egress.

## Verdict

**SHIP-WITH-FIXES.** The DPAPI layer itself is sound; the gap is the egress path — no gate between DPAPI decryption and git/logs/process-snapshot. The pre-commit redaction hook plus a `panic-dump` redaction-canary test would close it.

### M10-STATE-ATOMICITY

_latency: 31648ms_

## Score

| Dim | Score | Justification |
|---|---|---|
| **Correctness** | 2 | W8 schema bug proved EngineHealth writes silently failed for an entire wave; the `except Exception: continue` anti-pattern still lurks in any path that hasn't been individually audited. No proof all JSON/CSV/SQLite writes go through validated models. |
| **Robustness** | 1 | No evidence of atomic write primitives (tmp+rename, SQLite WAL/journal). `kill -9` mid-write of `status.csv` (310 rows) or any `state/*.json` yields partial/truncated files with zero automatic recovery. `StateFileCorruptError` is never mentioned as caught, raised, or tested — it either doesn't exist or is never triggered, meaning corruption is silent. |
| **Operator-usability** | 4 | `preflight --fix` and `engines-heal` give the operator self-service repair; `status_csv writable` check exists. Usable surface is good. |
| **Test discipline** | 2 | 1576 tests but none exercised `kill -9` recovery, corrupt-file simulation, or partial-write rollback. The W8 quarantine bug evaded every test because they tested the happy path, not the failure path. The `except Exception: continue` pattern is untestable by design. |
| **Risk** | 4 | Silent state corruption on process kill is the single highest-impact failure mode in a long-running autonomous loop. Operator trusts the state to make routing/health decisions; if it's stale or truncated, cascading bad dispatches follow. |

## Top blocker

Ship a **`state/_atomic_write.py`** utility that every state path must use: write-to-temp → `fsync` → `os.replace` (POSIX atomic rename) → verify re-read checksum. Retrofit `status.csv`, all `state/*.json`, and `engine_health` writes to go through it. Add a `--corrupt-state` preflight check that detects zero-byte or unparseable files and surfaces a `StateFileCorruptError` with recovery guidance. This single artifact lifts Robustness from 1→3 and Risk from 4→2.

## Verdict

**SHIP-WITH-FIXES.** The W8 schema bug proves silent-write failures are not hypothetical; without atomic write guarantees and corruption detection, the next `kill -9` during an autonomous overnight loop will produce unrecoverable stale state that no preflight or heal command knows to look for.

### M11-CONCURRENCY

_latency: 61257ms_

## Score

1. **Correctness (4/5):** Logic works sequentially, but `EngineHealth` updates in `preflight` lack explicit atomic read-modify-write semantics, risking data races in the `ThreadPoolExecutor`.
2. **Robustness (2/5):** `scheduled_tasks.lock` likely suffers from stale-lock gaps; `multiprocessing` sweeps risk zombies; `asyncio` coord likely stalls if `engines-heal` uses blocking HTTP calls without `await asyncio.to_thread()`.
3. **Operator-usability (4/5):** Excellent CLI, but a stuck lock file from a crashed thread or process will brick the non-technical operator until manual file deletion.
4. **Test discipline (3/5):** 1576 tests pass sequentially, but zero evidence of concurrency stress tests to establish happens-before guarantees on shared files like `status.csv`.
5. **Risk (4/5):** High probability of silent `status.csv` corruption during parallel mutation appends and deadlocked `ThreadPoolExecutor` workers if an engine health check hangs indefinitely.

## Top blocker

Implement a dedicated `test_concurrent_state_access` suite that runs `preflight --fix` and `mutation sweeps` in parallel to validate that file-locking guarantees happens-before semantics and that thread-safe dictionary updates prevent lost `quarantined` states.

## Verdict

SHIP-WITH-FIXES. Without explicit concurrency stress tests, race conditions on shared state and stale locks will inevitably brick the autonomous loop under production load.

### M12-V2-COORD

_latency: 32311ms_

## Score

**Correctness: 4** — The EngineHealth schema bug was a genuine cross-contract failure: fix functions wrote `quarantined`/`recovering`, Pydantic silently rejected, consumers never saw it. Fixed now; quarantine flow verified end-to-end. Persistent STOPs on two audit-related rows remain but don't block operator functionality.

**Robustness: 3** — The `except Exception: continue` that hid the schema mismatch is exactly this lens's nightmare: a worker contracts to write status, integrator silently drops it. Fixed for this instance, but no grep/lint proves the pattern is gone elsewhere. Audit non-determinism means the robustness *verifier* itself is flaky.

**Operator-usability: 4** — `preflight --fix` now actually heals, `engines-heal` surfaces recovery states, `harness today` is plain-language. The runbook closes the gap the readiness panel identified. Non-technical operator can recover a dead engine without writing Python.

**Test discipline: 3** — The schema bug passed 1544 tests. Tests asserted fix functions *returned* success but never asserted on-disk `engine_health` actually contained `"status": "quarantined"`. The audit sweep caught what tests missed — that's the audit doing its job, but it means integration tests at the coordination contract boundary are missing.

**Risk: 3** — The `except Exception: continue` + stale-schema pattern could exist in any coordinator→integrator→status path. W9-AUDIT-NONDETERMINISM-AVG is queued but not landed, so the audit gate remains a noisy signal for the next wave.

6. **Top blocker**: Add one integration test per fix function that asserts *on-disk file state* after `preflight --fix` — not function return value, but actual JSON round-trip through the Pydantic schema. This would have caught the W8 schema bug in CI rather than requiring an audit sweep.

7. **Verdict**: **SHIP-WITH-FIXES** — the load-bearing coordination bug is fixed, but the test gap that allowed it to ship needs closing before autonomous mode can trust the preflight→fix→verify contract.

### M13-PROXY-SAFETY

_latency: 26822ms_

## Score (Proxy Safety Reviewer lens: 4-key proxy + circuit breaker + auto-quarantine)

| Dimension | Score | Justification |
|---|---|---|
| Correctness | 3 | Circuit breaker exists and mutation-kills at 2/2; but the quarantine path silently failed for unknown duration until W8 caught it — proxy's safety claims are load-bearing on code that was demonstrably broken |
| Robustness | 2 | The `except Exception: continue` that swallowed the EngineHealth schema rejection is exactly the anti-pattern a safety reviewer flags. If quarantine writes fail silently, circuit-breaker state is untrustworthy. No evidence of tombstone or dead-letter for failed quarantine attempts |
| Operator-usability | 3 | `engines-heal` surfaces blocked/recovering states; `preflight --fix` works post-W8. But operator cannot distinguish "proxy protected the key" from "proxy failed open and forwarded to upstream directly" — visibility gap |
| Test discipline | 2 | 6 new tests for quarantine flow post-fix, but zero tests asserting the proxy **refuses to forward traffic when circuit is open**. Mutation kill on `proxy/circuit` confirms idioms exist, but no integration test proves end-to-end fail-closed behavior |
| Risk | **4** | Silent schema bug proves the safety path was untested in production. DPAPI + 4-key rotation is sound architecture but the failure mode is: proxy circuit trips → quarantine fails silently → next request uses a compromised or rate-limited key → cascade to operator-visible error with no recovery path. The content-filter incident (MiMo tripping on verbatim API keys) also suggests key material may leak into log/prompts |

## Top blocker

**Add a fail-closed integration test that kills the upstream HTTP client, triggers circuit-breaker, and asserts the proxy returns 503 (not passthrough).** The `except Exception: continue` pattern must be replaced with `except Exception: log_and_escalate` on the quarantine path specifically. One test, ~30 lines, transforms the risk posture from "assumed safe" to "verified safe."

## Verdict

**SHIP-WITH-FIXES** — The proxy architecture is sound and the W8 quarantine fix landed correctly, but the proven-existence of silent-failure anti-patterns on the safety path means shipping without a fail-closed assertion is shipping on faith, not evidence.

### M14-OBSERVER-DESIGN

_latency: 45158ms_

## Score

1. **Correctness (2/5)**: Observer probe times out in preflight — the detection layer isn't catching anything right now. The audit gate it feeds is non-deterministic: three rows flip PASS↔STOP with zero code change between sweeps, which means the observer's verdict is not grounded in stable criteria.

2. **Robustness (2/5)**: Observer timeout is a single point of failure for autonomous mode (preflight exit code 4 = hard blocker). MiMo content filter blocked every W9 audit until DeepSeek fallback landed — one fragility patched, but the structural non-determinism remains. `--avg-of-N` is a statistical band-aid, not a fix for inconsistent interpretation.

3. **Operator-usability (3/5)**: Preflight's observer timeout message gives actionable guidance (`harness observer scheduler-status`). But "Non-det" audit results in `harness today` are not operator-grade — a non-technical operator cannot act on "this flag flipped PASS↔STOP with no code change." The observer's 12 subcommands are developer-facing, not operator-facing.

4. **Test discipline (2/5)**: 41 observer tests from W20-OBSERVER exist, but none test the observer's own liveness or timeout behavior — exactly the failure preflight is catching. Non-determinism means even passing tests don't guarantee stable behavior across runs.

5. **Risk (3/5)**: Observer down → autonomous mode hard-blocked. Persistent STOPs on W8-STOP-HOOK and W8-AUDIT-PROMPT confirm the detection layer has known blind spots. Not a ship-blocker in `review_each` mode, but autonomous loops are unreliable until fixed.

6. **Top blocker**: Diagnose and fix the observer probe timeout. Until the observer passes its own preflight health check, nothing else in the detection layer matters — the canary is dead. The 5-second timeout may simply be too tight, or the observer scheduler may not be armed; either way, this is the single artifact that lifts my score by ≥1.

7. **Verdict**: HOLD. Both load-bearing pillars of the detection layer — observer liveness and audit-gate determinism — are compromised. Fix the timeout, confirm observer cycles are actually running, then re-score.

### M15-DASHBOARD-UX

_latency: 16708ms_

## Score

1. **Correctness** — 4/5 — Commands work as spec'd (`today`, `preflight`); dashboard (via `dashboard-serve`) surfaces data but its value-add over CLI is unclear from the snapshot.
2. **Robustness** — 3/5 — `preflight` gracefully handles timeouts; `today` presents known data. No evidence of handling dashboard WebSocket disconnects or large-history performance.
3. **Operator-usability** — 2/5 — The raw `harness today` output is text-heavy and mixes 121+ events with audit roll-ups. Dashboard likely improves this, but its surface isn't evaluated here. The `--help` tree is comprehensive but overwhelming.
4. **Test discipline** — 4/5 — 1576 tests + mutation canary suggest good regression catches. The audit-gate test for MiMo non-determinism (`W9-AUDIT-NONDETERMINISM-AVG`) is a direct UX-adjacent fix.
5. **Risk** — 3/5 — Operator cognitive overload from undifferentiated information (e.g., raw dispatch lists in `today`) is a key UX risk. Could lead to missed critical signals.

## Top blocker
**Triage `harness today` output.** The current stream (dispatches + audit rolls + blockers) is overwhelming. Group, summarize, and highlight only actionable changes (e.g., "3 dispatches succeeded, 1 audit STOP needs review") to lift usability score by ≥1 point.

## Verdict
**SHIP-WITH-FIXES** — The dashboard infrastructure (CLI, serve, data endpoints) is correct and robust, but the operator-facing information density in `harness today` is counterproductive; it needs summarization to be usable.

### M16-TEST-QUALITY

_latency: 29485ms_

## Score

1. **Correctness** — 3/5. The quarantine schema bug (`except Exception: continue` + wrong Literal values) proves behavioral assertions weren't validating actual Pydantic writes. Tests passed while the feature silently failed every quarantine — a test discipline gap.

2. **Robustness** — 2/5. `except Exception: continue` was load-bearing masking code. Mock dict stubs in engines-heal tests allowed dict-path to pass while Pydantic-path was broken in production. Tests should have caught the schema mismatch.

3. **Operator-usability** — 4/5. `harness today`, preflight, engines-heal are non-technical-usable. Runbook exists. Minor: observer timeout warning leaks internal concepts.

4. **Test discipline** — 3/5. 1576 tests but the three modules I sampled reveal pattern: tests validate dict stubs not real Pydantic models. The engines-heal `isinstance(v, dict)` dual-path exists *because* tests use dicts. This inverts the relationship — production code adapts to test stubs.

5. **Risk** — 3/5. Mock-heavy tests that don't exercise Pydantic schemas will miss the next schema mutation. The mutation canary (3 patterns, rolling) helps but doesn't cover schema evolution.

**Three modules sampled** (highest mutation-kill-rate first):
- `engines/dispatcher.py` (17.30 kill-rate) — likely behavioral; kill rate suggests real edit detection. **A-**.
- `coord/worker.py` (recovered to 4.00) — test stubs use dicts not real schemas; the quarantine bug's sibling risk. **C+**.
- `proxy/circuit` (2/2 killed, consistent) — circuit breaker is inherently behavioral (state transitions). **B+**.

6. **Top blocker** — Replace dict-based test stubs with real Pydantic `EngineHealth(...)` construction in engines-heal and preflight-fix tests. This one change would have caught the schema bug that silently failed every quarantine, and would generalize to future schema mutations.

7. **Verdict** — **SHIP-WITH-FIXES.** Tests catch regressions in behavioral modules but mask bugs where mock dicts diverge from Pydantic schemas — the quarantine flow proves this isn't theoretical.

### M17-DOCS-ACCURACY

_latency: 32265ms_

## Score

| Dimension | Score | Justification |
|---|---|---|
| **Correctness** | 3 | Closeout doc describes flows the code exhibits (prelight fix, engines-heal recovery); but W8-STOP-HOOK and W8-AUDIT-PROMPT hold persistent STOPs — auditor found gaps spec/* doesn't address. |
| **Robustness** | 3 | Schema-bug fix (EngineHealth Literal) is load-bearing and documented; but the spec/* files themselves may not enumerate `quarantined`/`recovering` states, leaving the next developer to re-break the same contract. |
| **Operator-usability** | 3 | OPERATOR_RUNBOOK exists, `today` prints blocks, `preflight --fix` is documented — but the `observer probe timed out` warning in the live output has no inline fix guidance; operator must hunt the runbook. |
| **Test discipline** | 3 | +32 net tests for 8 shipped rows (4 tests/row avg) is thin; some rows like W8-OPERATOR-RUNBOOK (docs-only) reasonably lack tests, but W8-STOP-HOOK claims 5 hook tests yet still holds persistent STOP — tests aren't catching the actual gap. |
| **Risk** | 4 | Two persistent STOPs + three non-det rows mean the doc/spec/code triangle has real divergence. The closeout itself admits "documentation lying" territory for STOP-HOOK's content-hash filter (present in code, not in spec). |

## Top blocker

**Audit the spec/* files against the HEAD code for the 5 W8-STOP-HOOK + W8-AUDIT-PROMPT rows.** The closeout text acknowledges the auditor found a code-side fix (content-hash filter) that the spec doesn't describe. Closing that gap — updating spec/ to reflect the actual debounce/hash/exclusion logic — would lift Correctness and Risk each by ≥1, and likely flip both persistent STOPs to PASS on the next audit sweep.

## Verdict

**SHIP-WITH-FIXES.** The code works (schema bug fixed, preflight quarantine confirmed), but two persistent audit STOPs flag genuine spec-accuracy drift that will re-trigger every wave until the spec/* files are reconciled with the commit-state.

### M18-STATUS-CSV-DISCIPLINE

_latency: 42010ms_

## Score

**1. Correctness — 3/5.** Task rows map accurately to shipped commits (W8 items cross-check against `7081d93` refs). But ~130 rows are timestamped dispatches (`2026-05-24T081155Z` style) masquerading as tasks — the CSV conflates a task tracker with a dispatch log.

**2. Robustness — 2/5.** No schema enforcement on note length (W10-AUDIT-FOLLOWUP-COMMIT-POLICY packs regex boundary specs into a tracker cell). No status lifecycle — every visible row is "shipped"; where are queued/blocked items from W9's "10 candidates queued"? No validation that a row is a real Wn task vs. an auto-dispatch.

**3. Operator-usability — 2/5.** 310 rows with notes containing Pydantic Literal extensions and `find_latest_commit_for_task` boundary rules. A non-technical operator can't scan this in 30 seconds. Ironically, `harness today` and `harness status human` have become the *real* tracking surface — the CSV is now an engineering dump pretending to be an operator tool.

**4. Test discipline — 3/5.** Preflight checks `status_csv` is writable + recently touched. The W9 on-commit hook catches CRLF. But zero tests validate note-length bounds, row-type discrimination (task vs. dispatch), or that Wave N rows actually appear before the wave closes. The tracker's own integrity is untested.

**5. Risk — 3/5.** Not a ship-blocker today. But with ~130 dispatch rows per wave and waves accelerating, the CSV hits 500+ by W12. Notes will never be pruned. The tracker is losing its canonical status — `harness today` already superseded it for operator queries. Risk is entropy, not failure.

**6. Top blocker.** Split STATUS.csv into `tasks.csv` (Wn rows only, note cap ~200 chars, enforced by on-commit hook) and `dispatch_log.csv` (auto-generated, no manual notes). This removes ~130 noise rows immediately, makes the tracker scannable, and restores one-pane truth. The W10 `harness status human` verb already pulls from the CSV — it could pull from the cleaner table.

**7. Verdict: SHIP-WITH-FIXES.** The harness works, the operator surface is usable, but the canonical tracker has drifted into combined task-tracker-plus-dispatch-log noise that no one can actually audit — which defeats its purpose as a tracking primitive.

### M19-WAVE-DISCIPLINE

_latency: 28512ms_

## Score

1. **Correctness — 4/5.** The plan→execute→audit→closeout loop ran for W8: plan was authored post-panel, 8/8 items shipped, three audit sweeps ran, closeout committed. But the audit gate surfaced a load-bearing schema bug (EngineHealth Literal missing `quarantined`/`recovering`) that shipped in W7 and wasn't caught until W8 audit follow-through — the loop caught it late, not proactively.

2. **Robustness — 2/5.** The audit step itself is structurally unreliable: 3 rows flip PASS↔STOP with zero code change between sweeps 2 and 3. Two more persistently STOP across all three runs. A gate that gives different verdicts on identical input isn't a gate — it's a coin flip dressed as rigor. The discipline loop's weakest link is its own verification step.

3. **Operator-usability — 4/5.** Genuinely improved: `harness today` is readable, `preflight --fix` fixes things, runbook exists in non-Python language. The `--skip-engines` flag on preflight showing dead engines as `[OK]` even when the path is skipped is a minor confusion vector, but the operator trajectory is clearly upward.

4. **Test discipline — 3/5.** +32 tests in W8, 1576 total. But the schema bug — a Pydantic Literal silently rejecting writes behind `except Exception: continue` — shipped through W7 untouched. That's exactly the class of bug mutation testing or a type-checking lint should surface. Mutation kill rates weren't re-run in W8 either, so the top-5 table is stale since W7.

5. **Risk — 3/5.** The non-determinism isn't new (W6-PANEL precedent), but it's now affecting 3 of 8 W8 rows. Each wave that ships with a broken gate normalizes the breakage. W9's `avg-of-N` mitigation is the right bet, but until it lands, every future audit sweep is suspect.

6. **Top blocker.** Ship `W9-AUDIT-NONDETERMINISM-AVG` (the `--avg-of-N` flag) and re-run the W8 row set through it as a calibration baseline. If the averaged gate still flips, the problem is deeper than run variance. If it stabilizes, the discipline loop becomes trustworthy. Either way, you get signal. Without this, every future audit sweep is theater.

7. **Verdict — SHIP-WITH-FIXES.** W8's *deliverables* are solid and the operator trajectory is real, but the discipline loop's own audit gate is unreliable — fix the averaging before W9 closeout or the loop devolves into ritual without signal.

### M20-RISK-PROFILE

_latency: 31082ms_

## Score

1. **Correctness**: 4/5 — Core flows work post-schema-fix, but persistent audit STOPs on STOP-HOOK and AUDIT-PROMPT indicate unresolved spec deviations.
2. **Robustness**: 3/5 — Silent quarantine failure (now fixed) exposed a fragility pattern: exceptions swallowed with `continue`. The `git_clean` preflight fail blocks autonomous mode; no auto-fix offered.
3. **Operator-usability**: 3/5 — Runbook and `harness today` are good, but non-deterministic audit flips (PASS→STOP with no code change) will confuse a non-technical operator expecting consistency.
4. **Test discipline**: 3/5 — 1576 tests and mutation gates are solid, but the audit gate itself is the primary regression detector—and it's non-deterministic. Tests don't catch audit-flip drift.
5. **Risk** (next 30 days): 4/5 — **Engine collapse is the top risk**: MiMo content filter blocks audit prompts; DeepSeek is now primary but has no proven fallback if it degrades. Key revocation by any provider could silently break dispatch. Cost overrun is secondary (~$0.03/wave, but Wave 10 scope is wide). Scope creep is medium—autonomous loop can keep adding rows without operator review.

**Top blocker**: Implement `W9-AUDIT-NONDETERMINISM-AVG` (`--avg-of-N`) before Wave 10 closes. The audit gate is the harness's quality backbone, and right now a single sweep has ~40% false-positive/negative noise. Averaging 3+ sweeps would collapse the noise floor and let operators trust the verdict. Without it, every future wave risks shipping on a STOP or holding on a false PASS.

**Verdict**: SHIP-WITH-FIXES. The harness is functional and the schema bug is fixed, but the audit non-determinism and lack of cross-engine fallback resilience mean the operator cannot fully trust the system's self-diagnosis yet.
