# Master audit — 40-reviewer synthesis

_Dispatched: 40 personas (20 MiMo + 20 Kimi), elapsed 181.1s_

State snapshot fed to each reviewer is at `_state_snapshot.md` in this directory.

_OK responses: 40/40_


## Per-persona responses

### K01-ONBOARDING

_latency: 49538ms_

## Score
1. **Correctness**: 2 — W8 shipped operator readiness, yet `preflight --skip-engines` and `today` both timeout on the live Windows box; the runbook cannot compensate for a hung binary.
2. **Robustness**: 1 — Fresh clone → run preflight → 30 s deadlock with no fallback or diagnostic. The queued silent-stash bug (W9-PREFLIGHT-FIX-NOSTASH) adds surprise data loss on recovery.
3. **Operator-usability**: 1 — A non-technical user must choose `--mode`, `--profile`, and parse 30+ verbs before validation; then step one hangs. Evidence shows ~100 % first-attempt failure rate.
4. **Test discipline**: 2 — 1 576 tests miss the Windows first-run integration hang and the CRLF hook false-positive (W9-ONCOMMIT-HOOK-CRLF).
5. **Risk**: 5 — Complete onboarding blockage for the target operator profile; a clear ship-blocker.

## Plus
6. **Top blocker**: A `harness doctor --first-run` fast-path that skips DPAPI/git-depth checks known to hang under Windows Store Python, surfaces dirty-state warnings without stashing, and confirms the CLI is responsive before any comprehensive gate runs.
7. **Verdict**: HOLD. No fresh operator can complete clone-to-first-green-preflight today without technical rescue.

### K02-DOCS-CLARITY

_latency: 63680ms_

## Score

1. **Correctness — 2**  
   Docs claim operator readiness, yet CLI commands timeout and MiMo returned persistent STOP on W8-STOP-HOOK and W8-AUDIT-PROMPT.

2. **Robustness — 2**  
   No visible operator-facing docs cover failure modes (timeouts, stash recovery, CRLF hook bug), so a non-technical user has no escape hatch.

3. **Operator-usability — 3**  
   Runbook and human-friendly commands exist, but the operator cannot trust them while undocumented timeout and data-loss paths remain.

4. **Test discipline — 2**  
   Doc quality hinges on non-deterministic MiMo audits; no deterministic doc-regression tests (e.g., runbook walkthrough scripts) are evident.

5. **Risk — 4**  
   Unverified runbook + silent stash behavior + CLI timeouts create a high chance of operator confusion or data loss within 30 days.

6. **Top blocker**  
   OPERATOR_RUNBOOK.md must be manually validated end-to-end and include a "Known Issues & Recovery" section for the stash, timeout, and CRLF hook bugs.

7. **Verdict**  
   SHIP-WITH-FIXES — operator-readiness scaffolding exists, but documented behavior does not yet match reality closely enough for safe handoff.

### K03-FAILURE-MODES

_latency: 120024ms_

## Score
1. **Correctness — 3**: Spec implemented, but silent stash and 30 s Windows timeouts are operator-safety gaps.
2. **Robustness — 2**: Timeouts, CRLF hook false-positives, and historically swallowed exceptions let failures cascade.
3. **Operator-usability — 3**: Runbook exists, yet daily commands timeout and `--fix` destroys uncommitted work without warning.
4. **Test discipline — 3**: 1 576 tests cover logic, but Windows CLI timeouts and Bash hook CRLF behavior lack coverage.
5. **Risk — 4**: First-week operator faces data loss or morning blindness; blast radius is immediate productivity halt.

**Failure modes (freq×impact, sorted):**
1. **Preflight/`today` 30 s timeout** — daily blindness; retry/skip engines; 5–10 min.
2. **`preflight --fix` silent stash** — lost uncommitted changes; `git stash pop`; 5–30 min.
3. **CRLF commit-hook false-pos** — commits blocked; bypass hook; 5–15 min.
4. **Dead-engine quarantine loop** — zero dispatch; `engines-heal`; 10–20 min.
5. **MiMo audit flip** — confidence erosion; accept-as-shipped precedent; 15–45 min.
6. **Verb-tree overload** — wrong destructive command; runbook + reverse; 10–30 min.
7. **Secret/DPAPI expiry** — total outage; re-seed keys; 10–30 min.

6. **Top blocker**: Ship W9-PREFLIGHT-FIX-NOSTASH (replace auto-stash with a loud confirmation prompt).
7. **Verdict**: SHIP-WITH-FIXES — W9 queued patches are small, localized, and required for first-week operator survival.

### K04-CLI-ERGONOMICS

_latency: 79372ms_

## Score

1. **Correctness** — 2/5. Inconsistent hyphenation (`spec-init` vs `init`, `engines-heal` vs `engines heal`) fractures the command taxonomy.
2. **Robustness** — 2/5. `preflight` and `today` silently hard-timeout after 30s with no progress indicator or partial output.
3. **Operator-usability** — 2/5. Flat, alphabetical dump of 30+ verbs offers no grouping; non-technical operators cannot map intent to command.
4. **Test discipline** — 2/5. No visible CLI integration tests for the W8 operator-facing verbs that demonstrably hang in production.
5. **Risk** — 4/5. High probability of operator mis-invocation, abandoned readiness checks, and escalation fatigue from hung commands.

**Discoverability (3 verbs)**
- `coord` — 4/5. Subcommands (`plan, run, integrate, status`) are discoverable directly in the top-level description.
- `engines` — 2/5. `heal` is a hidden subcommand shadowed by top-level `engines-heal`/`engines-cooldowns` aliases.
- `observer` — 2/5. One-line help teases "authority audit" but buries 12 subcommands behind a second `--help` layer.

**Top blocker** — Unify all engine operations under `harness engines {heal|cooldowns|reliability}` and remove the hyphenated top-level aliases so intent maps to a single namespace.

**Verdict** — SHIP-WITH-FIXES. W8 capabilities are operationally necessary, but the CLI surface is actively hostile to the non-technical operator it was built for.

### K05-HONEST-READINESS

_latency: 55061ms_

## Score
1. **Correctness** — 2 — `preflight --skip-engines` and `today` both timeout and fail; a schema bug silently broke every quarantine write until W8 follow-through.
2. **Robustness** — 2 — `preflight --fix` auto-stashes work without confirmation or recovery instructions; the operator cannot survive a hang or data loss alone.
3. **Operator-usability** — 2 — The two commands a non-technical operator needs most hang indefinitely; a single-page runbook is dwarfed by a 30+ verb CLI.
4. **Test discipline** — 3 — High count missed the `EngineHealth` Literal mismatch that neutered quarantine; mutation rates mask real gaps.
5. **Risk** — 4 — Day-one hangs on readiness and status checks plus silent stash data loss make 30-day unsupervised operation dangerous.

6. **Top blocker** — Make `harness preflight` and `harness today` complete reliably in <10s, remove auto-stash from `--fix`, and add an integration test enforcing both.
7. **Verdict** — HOLD — The operator’s two most critical commands timeout, the audit gate is a coin-flip, and silent stash behavior guarantees data loss for a non-technical user.

### K06-DOGFOOD

_latency: 59840ms_

## Score

1. **Correctness — 3.** 1576 tests pass and the closeout was self-authored, yet `harness preflight --skip-engines` and `harness today` both hang, so the harness cannot execute its own daily self-check.

2. **Robustness — 2.** Silent `except Exception: continue` masked a schema bug that broke every quarantine write, and the core dogfood CLI now hits 30-second timeouts suggesting a liveness failure in the self-hosted loop.

3. **Operator-usability — 2.** A runbook and `status --human` exist, but the non-technical operator cannot run the daily pulse or readiness gate without hangs, making the surface theoretical.

4. **Test discipline — 3.** Mutation kill rates exceed the ≥3 gate, yet the deferred W9 mutation-canary leaves no deterministic regression signal independent of MiMo roulette, so the meta-layer guards nothing deterministically.

5. **Risk — 4.** Hanging self-checks block operator reliance today, and persistent MiMo STOPs on audit-config rows (STOP-HOOK, AUDIT-PROMPT) prove the audit layer is auditing itself with broken tooling.

6. **Top blocker:** Fix the 30-second hangs in `harness preflight --skip-engines` and `harness today` so the harness can actually run its own operator-facing dogfood commands.

7. **Verdict:** SHIP-WITH-FIXES. The architecture is self-hosted on paper, but the meta-layer is a tower of indirection while its own `preflight` and `today` commands deadlock.

### K07-DEAD-CODE

_latency: 122233ms_

## Score
1. **Correctness** — 2. `preflight --skip-engines` and `today` hard-hang; help strings for `swarm-verify`, `engines-heal`, and `status` are truncated stubs; user-facing descriptions still carry W5/W8 wave-scaffolding tombstones.
2. **Robustness** — 2. No guardrail prevents hung commands; the CLI has sprouted 38+ verbs against a 22-verb contract, signaling ungoverned surface-area bloat.
3. **Operator-usability** — 1. A non-technical operator cannot distinguish live verbs from undead stubs when the help surface is littered with pending-wave labels and critical paths timeout.
4. **Test discipline** — 2. 1576 unit tests missed two CLI hangs; no automated gate rejects stub help text or wave-label leakage into the operator-facing CLI.
5. **Risk** — 4. Undead stubs and hanging commands will crater operator trust; the 38+ verb sprawl vs. the 22-verb target implies nearly half the surface may be scaffolding.

6. **Top blocker** — An integration smoke test that exercises every verb with `--help` and a 5-second dry-run, failing CI on any timeout, truncation, or Wave-N scaffolding in user-facing descriptions.
7. **Verdict** — SHIP-WITH-FIXES: hanging commands and scaffolding-polluted CLI surface are unacceptable ship-blockers for a non-technical operator.

### K08-PERFORMANCE

_latency: 54405ms_

## Score
1. **Correctness** — 2/5. Preflight --skip-engines and harness today both time out at 30s, missing the ~5s performance spec by 6×.
2. **Robustness** — 2/5. No graceful degradation when core commands hit wall-clock timeouts; operator is left without readiness signal or daily pulse.
3. **Operator-usability** — 2/5. A non-technical operator cannot reliably run basic status or preflight commands; timeouts negate W8 usability investments.
4. **Test discipline** — 1/5. Zero timeout-budget or performance-regression tests; the 30s preflight regression shipped undetected across 1576 tests.
5. **Risk** — 4/5. Basic operator workflows are functionally unreachable under timeout; perceived flakiness threatens operator trust and adoption.

6. **Top blocker** — A `tests/test_perf_budget.py` enforcing hard CLI timeouts (preflight --skip-engines <8s, today <10s) that fails CI, plus immediate cProfile of the preflight hot path to locate the synchronous scan that --skip-engines fails to skip.
7. **Verdict** — SHIP-WITH-FIXES. W8 operator-readiness features are structurally complete but operationally inaccessible because core CLI commands breach the 30s timeout wall; unblocking preflight latency is prerequisite to any operator handoff.

### K09-COSTS-BUDGET

_latency: 44348ms_

## Score

1. **Correctness** — 2/5. `harness budget` exists but no verified output proves session-cost accuracy; `harness today` (daily pulse) times out, so the W6-A2 ledger wiring is not demonstrably readable.  
2. **Robustness** — 2/5. `preflight --skip-engines` and `today` both timeout after 30 s; the budget query path likely shares the same blocking init overhead.  
3. **Operator-usability** — 2/5. A non-technical operator cannot answer “how much did this session cost” when the plain-language pulse command fails and the runbook omits budget-reading steps.  
4. **Test discipline** — 1/5. None of the 1,576 cited tests target budget-meter accuracy or cost-ledger regression; W7-WORKER-BUDGET-HOOK landed without noted coverage.  
5. **Risk** — 4/5. Unverified spend visibility means the operator could accumulate API costs without a trusted single-command check.

6. **Top blocker** — Make `harness budget` (or `today`) return a sub-5-second, non-blocking per-session cost table and add one budget-meter assertion to the mutation-canary suite.  
7. **Verdict** — SHIP-WITH-FIXES. The ledger may be wired, but the operator-facing read-path is neither proven nor robust.

### K10-MULTI-ENGINE

_latency: 42171ms_

## Score

1. **Correctness — 2/5**: `--engine-fill` and `engines-cooldowns` exist but the snapshot offers no proof the scheduler actually saturates Kimi slots before fallback or that dispatch respects cooldown timestamps.
2. **Robustness — 2/5**: `preflight --skip-engines` hangs for 30 s, indicating engine-pool I/O is not isolated by the flag; the `EngineHealth` schema mismatch silently failed every quarantine until manual discovery.
3. **Operator-usability — 3/5**: `engines-heal`, `engines-cooldowns`, and `today` are operator-friendly verbs, but a hung preflight blocks the non-technical daily workflow and erodes trust.
4. **Test discipline — 2/5**: 1576 passing unit tests missed a silent schema rejection and a CLI timeout; no mutation or integration coverage pins slot-cap or cooldown-enforcement behavior.
5. **Risk — 4/5**: Unenforced slot policy wastes subscription burn; unvalidated cooldowns risk cascading 429s across Anthropic/Gemini/DeepSeek within 30 days.

**Top blocker:** A single integration test that dispatches N+1 packets with `--engine-fill aggressive` and asserts Kimi concurrency hits its slot ceiling before any fallback, plus a `<5 s` timeout-regression test for `preflight --skip-engines`.

**Verdict:** SHIP-WITH-FIXES — engine-pool CLI contracts look operator-ready, but the hanging preflight and unvalidated slot policy make multi-engine discipline ceremonial rather than enforced.

### K11-AUDIT-NONDETERMINISM

_latency: 63000ms_

## Score

1. **Correctness — 3** Code appears correct, but the verification loop is a random variable; you cannot ship confidence when the auditor flips on identical bits.
2. **Robustness — 2** Silent quarantine failures and an accepted “ignore persistent STOPs” precedent mean the safety net catches nothing by design.
3. **Operator-usability — 3** Track B CLI is excellent, yet asking a non-technical operator to parse MiMo mood swings turns quality assurance into astrology.
4. **Test discipline — 3** 1576 tests and cleared mutation gates are solid, but the deferred canary is the only deterministic guardrail and it is not running.
5. **Risk — 4** A real regression will ride the W6-PANEL precedent through the gate because STOPs are now treated as noise until proven otherwise.

**Top blocker:** Deploy a 3-sweep majority-rule auditor (`W9-AUDIT-NONDETERMINISM-AVG`) with multi-commit diff anchors (`W9-AUDIT-ANCHOR-MULTI-COMMIT`); stop treating a single MiMo run as a binary gate.

**Verdict:** SHIP-WITH-FIXES — the harness is functional but its quality gate has worse SNR than a coin flip; calibrate it before W9 planning begins.

### K12-REPLAY

_latency: 47768ms_

## Score

1. **Correctness — 2**  
   `replay` claims v1/v2 coord-run reconstruction in help, yet no spec or shipped Wn row validates decision-chain fidelity.

2. **Robustness — 2**  
   Peer CLI verbs (`today`, `preflight`) time out after 30 s; replay lacks visible truncation or streaming guards for long histories.

3. **Operator-usability — 1**  
   The non-technical runbook never mentions `replay`, and truncated CLI help offers no cue on when or why to invoke it.

4. **Test discipline — 1**  
   The 1,576-test roll-up and mutation tables omit replay entirely; a regression in reconstruction logic would go unnoticed.

5. **Risk — 3**  
   Without usable replay, the operator cannot self-service investigate coord-run failures, guaranteeing future L5 escalations.

6. **Top blocker**  
   Add a runbook section “Investigate a failed coord run” that demonstrates `harness replay --human` with plain-language decision narration and sample output.

7. **Verdict — SHIP-WITH-FIXES**  
   Replay is technically present but operator-invisible; the runbook gap turns decision archaeology into dead code.

### K13-SESSION-HANDOFF

_latency: 51208ms_

## Score
1. **Correctness: 2** — Handoff artifacts exist (`today`, `runbook`, `session`), but `harness today` and `preflight --skip-engines` both time out, and `--fix` silently stashes work, so the loop does not land the operator in a known-good state.
2. **Robustness: 2** — Core operator-facing verbs collapse under normal use; if the loop hands off during load, the operator has no reliable landing surface.
3. **Operator-usability: 2** — The runbook is readable, but its first mandated actions hang, violating the key question: “does the operator know what to do?”
4. **Test discipline: 1** — 1,576 unit tests pass, yet integration coverage missed 30-second handoff-path timeouts that strand a non-technical user.
5. **Risk: 4** — Immediate session-blocking hazard: a non-technical operator handed control with dead commands and invisible stashes will stall or panic.

6. **Top blocker** — Fix the 30-second hang in `harness today` and `preflight --skip-engines`; harden `session` to emit exactly one imperative next-action sentence (e.g., “Run `harness today` to review 3 tasks”) instead of a raw state dump.

7. **Verdict** — SHIP-WITH-FIXES. The loop cannot safely return control while its canonical landing commands time out and the stash silently eats in-progress work.

### K14-LOOP-PRODUCTION

_latency: 49507ms_

## Score
1. **Correctness** — 2/5. `harness loop` exists in the verb tree, but W8 shipped no loop-specific hardening and core dependent commands (`preflight`, `today`) timeout, indicating the loop runtime likely fails to meet its spec under load.
2. **Robustness** — 1/5. No pidfile hygiene, idempotent restart, or SIGKILL recovery is shown, and systemic CLI hangs suggest the long-running loop cannot survive plausible failures.
3. **Operator-usability** — 2/5. The runbook helps, but a non-technical operator cannot safely drive a loop whose `status` may hang and for which no "stuck loop" recovery procedure exists.
4. **Test discipline** — 2/5. Despite 1576 passing tests, the snapshot shows zero loop-lifecycle tests (kill, restart, orphan cleanup) and mutation scores exclude the loop controller.
5. **Risk** — 4/5. As the central autonomous primitive, an unrecoverable loop crash after a Windows update or SIGKILL would halt all autonomous progress and force manual CLI triage.

6. **Top blocker** — Add a persistent pidfile + heartbeat to `harness loop start`, an idempotent `--recover` path, and an integration test that SIGKILLs the loop then asserts `status` returns healthy with zero duplicate jobs.

7. **Verdict** — HOLD. The productized loop primitive lacks demonstrated kill+restart resilience and systemic CLI timeouts make hands-off operator use unsafe.

### K15-COORD-V2-MATURITY

_latency: 51351ms_

## Score

1. **Correctness: 3** — v2 coord primitives (worktrees, checkpoint, integrator) are not directly validated in W8; waves ship, but multi-agent isolation fidelity remains assumed, not proven.
2. **Robustness: 2** — `preflight` and `today` hard-timeout after 30s; `--fix` silently stashes in-progress work; CRLF hook false-positives block commits on Windows.
3. **Operator-usability: 3** — Human-facing verbs and runbook exist, but the operator-facing commands either hang or drop work silently, eroding non-technical trust.
4. **Test discipline: 3** — Mutation gates and 1576 tests catch module regressions, yet the `EngineHealth` schema bug silently failed every quarantine write because `except Exception: continue` masked it.
5. **Risk: 4** — In unattended mode, the timeout/stash/hook-noise failures will fire within days; v2 coord is still demo-ware until checkpoint recovery survives fault injection.

**Top blocker:** Eliminate the 30s hangs in `preflight`/`today` and remove `--fix` auto-stash behavior; these unattended-run killers must be resolved before the next wave.

**Verdict:** SHIP-WITH-FIXES — W8 operator readiness is tangible, but the timeouts, silent data loss, and hook noise prove v2 is not yet safe for unattended loops.

### K16-SPEC-CULTURE

_latency: 49690ms_

## Score

1. **Correctness — 3**  
   The Wave 8 closeout spec matches the code because it was authored *after* shipping (dated 2026-05-24, yet commits `9aea866` and `3dc8593` landed earlier). It is a chronicle, not a blueprint.

2. **Robustness — 2**  
   Retroactive specs offer no design-time guardrails. The `EngineHealth` schema bug silently failed every quarantine, and `preflight --fix` auto-stashed work—both surprises a spec-first review could have prevented.

3. **Operator-usability — 3**  
   The runbook and `harness today` are usable, but the non-technical operator cannot read an up-front spec to anticipate behavior or withhold authority before code ships.

4. **Test discipline — 2**  
   1,576 tests pass, yet there is no deterministic spec-to-code gate. MiMo audits are non-deterministic, the mutation-canary is deferred to W9, and the persistent STOPs on `W8-STOP-HOOK` and `W8-AUDIT-PROMPT` show spec compliance is verified erratically.

5. **Risk — 4**  
   Wave 9 is already queueing work (`W9-PREFLIGHT-FIX-NOSTASH`, `W9-MUTATION-CANARY`). Without a spec-first mandate, the next wave will repeat emergent development and operator surprise.

**Top blocker:**  
Freeze a `spec/wave-9-plan.md` and require operator sign-off *before* the first W9 implementation commit. Specs must lead; closeouts must not substitute for design review.

**Verdict:** SHIP-WITH-FIXES. W8 delivers operator-ready functionality, but the spec culture is backward-looking. If Wave 9 is not spec-led, operational trust and auditability will degrade.

### K17-AUTHORITY-DISCIPLINE

_latency: 98117ms_

## Score

1. **Correctness — 2** — The spec promises an audit gate on full dev authority, but MiMo’s non-determinism renders verdicts random; the discipline mechanism is effectively unspecified in practice.
2. **Robustness — 2** — A silent schema bug hid failures for waves; preflight now times out; the stop-hook still misfires, so the system cannot reliably survive its own maintainer’s errors.
3. **Operator-usability — 2** — The non-technical operator cannot review diffs or veto commits, and the oversight CLI (`today`, `preflight`) times out, leaving them blind.
4. **Test discipline — 1** — No deterministic test checks what Claude commits; deferred mutation canary and LLM-based audits offer zero automated signal if the dev manager goes off-rails.
5. **Risk — 4** — Unfettered commit/push authority with no enforceable check means a single bad loop could rewrite critical paths before a human notices.

6. **Top blocker** — Ship W9-MUTATION-CANARY plus deterministic file-invariant tests in `observer` so a non-LLM process can block the dev manager.

7. **Verdict — SHIP-WITH-FIXES** — Functionally close, but discipline is theater until a code-level gate can halt the autonomous loop.

### K18-SCOPE-CREEP

_latency: 43407ms_

## Score

1. **Correctness — 2/5**: Schema bugs silently fail quarantines, and `harness today`/`preflight` both timeout—surface area has outrun verification.
2. **Robustness — 2/5**: `except Exception: continue` swallowed critical Pydantic errors; 30-second hangs on core paths show systemic load intolerance.
3. **Operator-usability — 2/5**: Thirty-plus CLI verbs overwhelm a non-technical operator; `harness today` is unusable due to timeouts despite being built for them.
4. **Test discipline — 3/5**: 1,576 tests look impressive, but they missed a load-bearing schema bug and W8 skipped the full mutation sweep—quantity is masking coverage gaps.
5. **Risk — 5/5**: Scope is metastasizing (W9 queue already forming, two commands broken, verb tree unreadable); the harness is sprinting toward unmaintainable monolith.

**Top blocker**: Hard freeze on new CLI verbs and split observer/proxy/engines into standalone packages so the core harness stops accruing state.

**Verdict**: HOLD — convergence requires subtracting verbs, not adding more.

### K19-INTERACTION-FRICTION

_latency: 51274ms_

## Score

1. **Correctness — 3**  
   Features work post-fix, but the schema bug required a 90-min follow-through and three audit sweeps—three extra operator-Claude turns that should have been zero.

2. **Robustness — 3**  
   `preflight --fix` silently stashes in-progress code and CLI verbs time out after 30 s; each failure mode consumes an unplanned operator turn to recover.

3. **Operator-usability — 2**  
   Runbook exists, yet the operator must still interpret MiMo STOP flips and CRLF hook false-positives—technical friction that the non-technical profile cannot self-serve.

4. **Test discipline — 2**  
   1,576 tests cover logic, but no automated gate checks operator-facing friction (hangs, stash surprise, hook false-positives), so regressions in turns-per-feature go undetected.

5. **Risk — 4**  
   Persistent MiMo non-determinism means every Wn row risks 3+ audit cycles; at 285 STATUS rows this is a compounding tax on every future dispatch.

**Top blocker:** Replace the MiMo pre-ship hard gate with W9-MUTATION-CANARY (deterministic, 1 turn) and an operator-runbook checklist, halving average turns per feature.

**Verdict:** SHIP-WITH-FIXES — autonomy is structurally sound, but the approval layer (MiMo audits + hook/CLI hang friction) currently doubles or triples operator-Claude turns.

### K20-NEXT-WAVE

_latency: 119545ms_

## Score
1. **Correctness** — 3. Core operator commands (`preflight`, `today`) time out; two W8 rows remain persistent STOP and the MiMo gate is nondeterministic.
2. **Robustness** — 3. Silent `git stash` in `--fix`, blanket `except Exception: continue` masked the quarantine schema bug, and preflight hangs rather than degrading.
3. **Operator-usability** — 3. Runbook and `--human` exist but the operator cannot reliably run a morning pulse or safe preflight without hangs or data loss.
4. **Test discipline** — 4. 1576 tests pass and mutation gates clear, yet the quarantine path was uncaught until audit; deterministic canary is still deferred.
5. **Risk** — 4. Nondeterministic audit + missing canary + hanging core commands mean regressions can ship silently and readiness cannot be verified.

## Plus
6. **Top blocker** — W9-MUTATION-CANARY (detection). Stack-rank: detection > operator UX > engine reliability > v2 maturity > scope reduction. Detection is #1 because MiMo nondeterminism has already allowed persistent STOPs to ship and the operator cannot trust the audit gate to catch regressions.
7. **Verdict** — SHIP-WITH-FIXES. Readiness features exist but core CLI paths hang and the audit gate is unreliable, so Wave 9 must land the canary and timeout fixes before scaling usage.

### M01-INSTALL

_latency: 22414ms_

## Score

1. **Correctness (3/5)**: Preflight timed out with `--skip-engines` on Windows — the exact cold-start gate the fresh-install reviewer needs is non-functional at HEAD. Schema bug was real and fixed, but the timeout means we can't confirm the fix works for a new operator.
2. **Robustness (2/5)**: Two commands timed out (preflight, today). `--fix` silently stashed work (W9-PREFLIGHT-FIX-NOSTASH). CRLF false-positive on the commit hook blocks Windows operators. The Python Foundation Store path in the timeout trace signals PATH/install issues the runbook doesn't cover.
3. **Operator-usability (2/5)**: The `--help` tree has 40+ CLI verbs with flags like `--explore-on-uncertainty [dispatch_alternatives|inline|ask_operator]`. No mention of Python install, venv, or `pip install -e .` anywhere in the snapshot. The operator runbook assumes harness is already running — the gap from "cloned repo" to "preflight green" is undocumented.
4. **Test discipline (4/5)**: 1576 tests, mutation kill rates above gate, 32 new tests in W8. The schema bug slipped through *tests* but was caught by audit. Strong regression signal.
5. **Risk (4/5)**: A fresh-install reviewer literally cannot complete their task. The preflight timeout means the cold-start path is broken, and there's zero evidence of install/bootstrap documentation.

6. **Top blocker**: A `harness bootstrap` or `preflight` that actually succeeds — the Windows timeout trace (`PythonSoftwareFoundation.Python.3.13`) suggests the shebang/module invocation path is broken on Windows Store Python. Either fix the invocation (use `python -m harness` directly from documented entrypoint) or add a one-line install script (`pip install -e . && harness preflight`). The runbook must start at `git clone`, not at "run harness."

7. **Verdict**: **HOLD.** The cold-start gate (`preflight --skip-engines`) times out on Windows — no fresh-install reviewer can validate anything until that path works end-to-end in <30 seconds.

### M02-CLI-COMPLETENESS

_latency: 16320ms_

## Score

1. **Correctness**: 4/5 — Core verbs (preflight, engines-heal, dispatch, loop) functionally correct after W8 schema fix; edge-case failures (timeout, CRLF) documented.
2. **Robustness**: 3/5 — Silent quarantine failure was load-bearing; timeout on `preflight` and `today` suggests platform fragility; audit non-determinism undermines trust.
3. **Operator-usability**: 2/5 — Non-technical operator still blocked by timeouts, missing human-readable alias (`status --human`), and `preflight --fix` silently stashing code.
4. **Test discipline**: 4/5 — 1576 tests pass, mutation kill-rates recovered, but audit non-determinism means test verdicts aren’t reliable regression signals.
5. **Risk**: 3/5 — `preflight --fix` stash surprise could lose operator work; audit non-determinism may mask real regressions in next wave.

## Top blocker

**Fix `preflight --fix` to surface stash or skip it** — Current silent stash erodes operator trust; this single change lifts Robustness + Operator-usability by ≥1 point.

## Verdict

SHIP-WITH-FIXES — The CLI covers the operator lifecycle verb-by-verb, but the `preflight --fix` stash risk and missing `status --human` alias must be resolved before handoff to a non-technical operator.

### M03-OPERATOR-DAILY

_latency: 15246ms_

## Score

1. **Correctness**: 2/5 — Core daily verbs (`preflight`, `today`) timeout in practice, breaking the morning cadence the runbook prescribes.
2. **Robustness**: 2/5 — The 30-second timeout on critical status commands makes the operator's daily flow fragile and unreliable.
3. **Operator-usability**: 3/5 — The runbook and human-readable status are sound *in theory*, but the tools they depend on aren't functional.
4. **Test discipline**: 4/5 — 1576 tests pass, and the W8 focus on fixing the schema bug and adding `preflight --fix` logic is good regression insurance.
5. **Risk**: 4/5 — Operator daily cadence is dead-on-arrival until the timeout failures in `preflight` and `today` are diagnosed and fixed.

6. **Top blocker**: Fix the command timeout for `harness preflight --skip-engines` and `harness today`. Without a working "morning pulse," the operator runbook and entire daily-flow concept are theoretical, not operational.

7. **Verdict**: **HOLD**. The foundation for operator readiness is built, but the two most critical daily-flow commands are non-functional, making the harness unusable for its primary non-technical operator audience.

### M04-OBSERVABILITY

_latency: 21813ms_

## Score

1. **Correctness**: 3/5 — Core status surfaces (STATUS.csv, CLI verbs) exist, but critical commands (`preflight`, `today`) timeout in the provided capture, breaking immediate operator observability.
2. **Robustness**: 2/5 — The 30s timeout on `preflight` and `today` renders them unusable under the snapshot conditions, a severe observability gap.
3. **Operator-usability**: 1/5 — The non-technical operator's primary windows into system state (`status --human`, `today`) are non-functional in the capture, forcing manual file digging.
4. **Test discipline**: 2/5 — 1576 tests pass, but the test suite did not catch the live-timeout of two core observability commands, indicating an integration or environment gap.
5. **Risk**: 3/5 — Without working daily pulse or preflight, the operator cannot detect stalls, cost spikes, or engine health issues in real-time, risking prolonged silent failures.

## Top Blocker

**Diagnose and fix the command timeouts.** The harness's observability promise (`harness today`, `harness preflight`) is currently hollow in the captured environment. Making these commands reliably complete in <30s is the single change that would lift operator-usability and robustness scores by ≥1.

## Verdict

**SHIP-WITH-FIXES.** The observability design is sound, but the captured execution failures make it non-functional for the operator today; the timeout root cause must be resolved before handoff.

### M05-ERROR-RECOVERY

_latency: 25179ms_

## Score

| # | Dimension | Score | Justification |
|---|-----------|-------|---------------|
| 1 | **Correctness** | 2/5 | The EngineHealth schema bug silently swallowed every quarantine write — the exact failure this lens is designed to catch. It was fixed, but only because the audit sweep caught it; tests didn't. Now `preflight` and `today` both timeout = core commands produce no output. |
| 2 | **Robustness** | 1/5 | `preflight --skip-engines` and `today --since-hours 48` both hang to 30-second timeout with zero diagnostic. An `except Exception: continue` hid the schema bug for an entire wave. `preflight --fix` silently stashes the operator's in-progress work (W9 queued but not shipped). Three independent error-recovery paths fail silently or hang. |
| 3 | **Operator-usability** | 2/5 | The runbook exists, but if the operator runs `preflight` (step 1 of every autonomous-mode start) they stare at a blank screen for 30 seconds. `today` is the daily pulse — also dead. The operator cannot see their own system state through the two commands the runbook tells them to run first. |
| 4 | **Test discipline** | 2/5 | 1576 tests but none caught `except Exception: continue` masking a Pydantic validation error. No integration test runs `preflight --skip-engines` end-to-end under a timeout budget or it would have caught the hang. Mutation kill rate is healthy but the tested surface doesn't include the error-swallowing paths. |
| 5 | **Risk** | 5/5 | **Ship-blocker.** Two of the three most operator-facing commands are non-functional on HEAD. The operator literally cannot start their day. |

## Top Blocker

**Diagnose and fix the 30-second timeouts on `harness preflight --skip-engines` and `harness today`.** These are the first two commands the runbook tells the operator to run and both hang indefinitely until killed. Until they return real output, every other operator-readiness investment (runbook, status human, engines heal) is inaccessible because the operator can't even get past step 1.

## Verdict

**HOLD.** The two most operator-facing commands hang on invocation — the non-technical operator cannot run preflight or see today's status, which means they cannot safely enter autonomous mode or know whether their system is healthy.

### M06-AUDIT-GATE

_latency: 61596ms_

## Score

1. **Correctness — 3/5**: Gate catches real regressions (PREFLIGHT-FIX STOP→PASS pinned a load-bearing schema bug) but ~30% of rows flip verdict with zero code change, so the output can't be trusted at face value.

2. **Robustness — 2/5**: Non-determinism is the definition of fragile. W8-ENGINES-HEAL went 0.58→0.85→0.68 across three sweeps on the same commit. No input stabilization (debounce, content-hash, diff-cap) fixes interpretive variance inside MiMo.

3. **Operator-usability — 2/5**: Non-technical operator must read three sweeps, apply ad-hoc "W6-PANEL precedent" to decide which STOPs are real, and manually accept-as-shipped. There's no `--avg-of-N`, no consensus score, no single number to act on.

4. **Test discipline — 2/5**: Zero tests for audit-gate verdict consistency. Nothing catches the gate itself regressing. Mutation canary (W9) would provide a deterministic regression signal independent of MiMo, but it's queued, not shipped.

5. **Risk — 3/5 (noise erodes trust)**: If the operator learns that 1-in-3 STOPs are coin-flips, the rational response is to ignore all STOPs — which makes the gate worthless. This trust-erosion is the real 30-day risk, not any individual false STOP.

**False-positive estimate**: ~30% — 3 of 10 rows show STOPs on code verified good in a prior sweep (no commit between sweeps 2→3). Two persistent STOPs (STOP-HOOK, AUDIT-PROMPT) appear legitimate and aren't counted as false positives.

**False-negative estimate**: ≥1 documented — the EngineHealth schema bug silently failing every quarantine write survived undetected across W6 and W7 audits. Rate is likely low (5–15%) but non-zero and unmeasurable without re-auditing prior waves against ground truth.

6. **Top blocker**: Ship **W9-MUTATION-CANARY** immediately. Three known-killer mutants per top module, daily Task Scheduler run, ≥1 test failure per mutant expected. This bypasses MiMo entirely and gives a deterministic, non-interpretable regression signal. One canary run per day makes the audit gate's non-determinism tolerable rather than fatal.

7. **Verdict**: **SHIP-WITH-FIXES.** The gate catches real regressions (PREFLIGHT-FIX is proof) but 30% noise + no deterministic fallback means it can't be the sole regression signal — ship mutation-canary as a mandatory W9-Blocker, not a nice-to-have.

### M07-MUTATION-COVERAGE

_latency: 27349ms_

## Score — Mutation Coverage Reviewer

| Dimension | Score | Justification |
|---|---|---|
| **Correctness** | 3 | ≥3 gate is met for 5 tracked modules, but only 5 of ~20+ modules are tracked; W8 shipped 32 tests without re-running the sweep |
| **Robustness** | 2 | No mutation re-sweep in W8 despite code touching 6 new subcommands; canary deferred to W9; zero detection if a tracked module regresses |
| **Operator-usability** | 3 | Mutation data isn't operator-facing, but the audit gate it feeds is; operator can't assess whether mutations actually cover their risk surface |
| **Test discipline** | 2 | W7-MUTATION-ORCH is the only mutation-orchestration module; the 5-module table is a static artifact, not an enforced CI gate; gaps are invisible |
| **Risk** | 4 | W8 code landed in engines-heal, preflight-fix, stop-hook, audit-prompt, status-human, runbook — none re-validated by mutation sweep; ship-blocker if any of those modules dropped below the gate |

## Top blocker

**Surface untested modules.** Add a mutation-coverage manifest (e.g., `mutation_targets.yaml`) that lists every module with ≥3 known-killer mutants and its last-sweep SHA. Any module shipping code without a passing sweep must be auto-flagged. This transforms "5 modules pass" from a static snapshot into an enforced, auditable gate — and answers the operator's question: "what's CURRENTLY untested?"

## Verdict

SHIP-WITH-FIXES. The ≥3 bar is correct *for tracked modules* but the tracking surface is dangerously narrow (5 of 20+), W8 didn't re-sweep, and the deferred canary means regressions are invisible. Add the manifest + re-sweep W8-touched modules before closing.

### M08-ENGINE-RELIABILITY

_latency: 36072ms_

## Score

1. **Correctness — 4/5.** The schema bug fix (`7081d93`) unblocked the entire quarantine flow; manual verification confirms it works. But `preflight --skip-engines` timed out at 30s, so I cannot independently verify end-to-end engine-health state today.

2. **Robustness — 3/5.** The `except Exception: continue` that silently swallowed every quarantine write is a systemic anti-pattern; one instance was load-breaking, and no one audited whether the same pattern exists elsewhere in the engine layer. A single engine collapsing mid-dispatch falls back (dispatcher.py mutation kill rate 17.30 is strong), but the engine-heal command itself hit a 30s timeout in this snapshot — recovery may hang under real failure.

3. **Operator-usability — 4/5.** `harness engines-heal` is a single verb; the runbook links to it. `harness today` timed out, so the operator currently has no plain-language engine-health pulse — but the intent is sound and the timeout is likely environmental.

4. **Test discipline — 3/5.** 1576 tests, +32 this wave, dispatcher at 17.30 kill rate — excellent. But the schema bug lived through multiple waves undetected precisely because tests asserted on return values, not on `engine_health` disk state. W8-ENGINES-HEAL is audit-non-deterministic (STOP twice of three), meaning even the auditor isn't confident tests cover the recovery transitions.

5. **Risk — 3/5.** One engine dying is the exact scenario this layer exists for. The quarantine path now works, but the `recovering → up` promotion is untested in the snapshot (preflight timeout), and the silent-exception pattern may mask other failures that only surface under real engine collapse.

6. **Top blocker.** Grep `except.*continue` across all `engines/` and `dispatch` paths; convert every instance to at minimum `logger.warning` with the caught exception, or surface it via the L4 alarm. One such instance already silently broke quarantine for weeks — the same pattern elsewhere is the highest-probability next failure.

7. **Verdict — SHIP-WITH-FIXES.** The schema fix is real and load-bearing, but the silent-exception sweep is prerequisite to trusting the engine layer under a single-engine collapse — which is its primary job.

### M09-SECURITY-POSTURE

_latency: 37719ms_

## Score

1. **Correctness** — 3/5. Specs say DPAPI + JSONL redact + 0600, but the `except Exception: continue` pattern that silently swallowed the quarantine bug proves identical silent-failure masking is plausible in key-storage or redaction paths — unverified.
2. **Robustness** — 2/5. `panic-dump` scrubbing is claimed but untested; `preflight --fix` silently stashes tracked files (W9-PREFLIGHT-FIX-NOSTASH); the `proxy` 4-key circuit breaker has no audit entry; git-stash in a secret-bearing repo risks secret-adjacent context leaking into stash reflog.
3. **Operator-usability** — 4/5. Runbook and `status --human` are strong, but security posture is invisible — the operator has no signal whether redaction is working or a key just leaked to a log.
4. **Test discipline** — 2/5. Zero tests exercise redaction completeness, DPAPI isolation, `panic-dump` scrubbing, or prompt-injection resistance in `dispatch`→engine paths. Mutation tests target functional bugs only. The 1576 tests are security-blind.
5. **Risk** — 4/5. Worst path: `dispatch` sends user-controlled packet content to an LLM engine via a proxy holding 4 API keys — prompt injection → engine exfiltrates key material into response → response logged or surfaced via `retro`/`replay` before redaction runs. Second path: `harness env` reports per-key presence; if it ever leaks the actual value (even once, in debug mode), the JSONL log with that entry is permanent. Third path: `full_dev_authority` mode lets Claude commit+push — a poisoned memory file (`memory/*.md`) is trusted implicitly and has no integrity check.

## Top blocker

Ship a **redaction-integrity test**: enumerate every output surface (`retro`, `replay`, `panic-dump`, `env`, JSONL logs, `today`, `status human`) and assert no known-secret-pattern (API key prefix, DPAPI blob, env var value) appears unredacted. This single test suite lifts score from 2→3 on test discipline and 4→3 on risk.

## Verdict

HOLD — the `except Exception: continue` bug that silently swallowed quarantine writes for an unknown duration is proof that silent-failure masking exists in this codebase; until a redaction audit proves secret-handling paths don't share the same pattern, shipping exposes the operator to undetectable key leakage.

### M10-STATE-ATOMICITY

_latency: 20438ms_

## Score

**Correctness**: 2/5 — Quarantine writes to `engine_health` silently failed *every time* until W8; Pydantic rejected `quarantined` status and `except Exception: continue` swallowed it. State files told lies.

**Robustness**: 1/5 — No evidence of atomic writes (temp+rename), no WAL for sqlite, no `StateFileCorruptError` anywhere, and the one observed failure mode was *silent data loss*. `kill -9` mid-write is an open question with no documented mitigation.

**Operator-usability**: 3/5 — Preflight `--fix` and `engines-heal` give the operator recovery verbs, but if those verbs *themselves* silently corrupt state (as the schema bug proved), the UX is a trap.

**Test discipline**: 2/5 — The schema bug survived through W7 *and* was reproduced by the audit tooling — tests never caught a rejected Pydantic write to engine_health. No crash-recovery / mid-write tests visible.

**Risk**: 4/5 — State is the single source of truth for engine routing, quarantine, and cooldown. Silent write failure = operator thinks engine is quarantined, harness keeps dispatching to it. Next outage is load-bearing.

## Top blocker

Add `state/atomic.py` — a write helper that: (a) writes to `.tmp` then `os.replace`, (b) wraps all JSON/SQLite writes, (c) raises `StateFileCorruptError` on any serialization failure instead of swallowing. Then add a kill-during-write integration test. This single artifact closes the atomicity gap and makes the `except Exception: continue` class of bug structurally impossible.

## Verdict

**HOLD** for state write atomicity — the W8 proof that *every quarantine write silently failed* is a ship-blocker until the state layer has crash-safe writes and surface-on-failure error handling.

### M11-CONCURRENCY

_latency: 24293ms_

## Score

1. **Correctness — 3/5**: Three distinct concurrency runtimes (ThreadPoolExecutor, asyncio, multiprocessing) share mutable state (engine_health.json, git index, pytest cache) with **no cross-model synchronization**. The schema fix (7081d93) corrected the *shape* of writes but not their *atomicity*.

2. **Robustness — 2/5**: `preflight --fix` does `git stash` + file mutation + engine_health write. If Task Scheduler fires the autonomous loop while an operator runs `preflight --fix` manually, both contend on the git working tree and the same JSON file. The `scheduled_tasks.lock` is your only guard, and nothing in the snapshot confirms it's checked before engine_health writes. The `except Exception: continue` that hid the schema bug is the *exact pattern* that hides races too.

3. **Operator-usability — 4/5**: Not the operator's problem to solve. The CLI verbs look clean.

4. **Test discipline — 2/5**: Zero evidence of concurrent stress tests. All 1576 tests are sequential. A single `concurrent.futures.ThreadPoolExecutor` submitting two `preflight --fix` calls against shared state would surface the race in seconds, yet it doesn't exist. Mutation sweeps fork processes that could mutate files mid-read by the main process — untested.

5. **Risk — 4/5**: Task Scheduler fires the autonomous loop on a cadence; `preflight --fix` is its first step. A manual `preflight --fix` from the operator during a scheduled tick is a plausible data race on `engine_health.json` and the git index. Silent corruption (like the quarantine bug, but concurrency-induced) is the likely failure mode.

## Top blocker

**Add an advisory file lock (`portalocker` or `fcntl`) around `engine_health.json` read-modify-write in `_check_dead_engines`, `engines heal`, and `preflight --fix`, plus a 3-line concurrent smoke test that submits two `preflight --fix` calls to a ThreadPoolExecutor and asserts no duplicate quarantine writes.** This is the only shared mutable state accessed from all three concurrency models with no happens-before guarantee today.

## Verdict

**SHIP-WITH-FIXES.** The operator-readiness work is genuinely load-bearing, but the unsynchronized engine_health writes under concurrent Task Scheduler + manual invocation are a data-race waiting to manifest as silent corruption — the same class of bug you just fixed.

### M12-V2-COORD

_latency: 29654ms_

## Score

**1. Correctness — 3.** The schema bug (EngineHealth Literal rejecting `quarantined`/`recovering`, silently swallowed by `except Exception: continue`) is a coord-correctness archetype: the worker wrote data the coordinator schema wouldn't accept, and nobody noticed because the contract was implicit. Fixed now, but the pattern likely lurks elsewhere.

**2. Robustness — 3.** The `except Exception: continue` anti-pattern in the fix functions is exactly the cross-worker contract drift I'd flag. W8 fixed the EngineHealth instance, but no sweep verified the pattern doesn't repeat in other coord↔worker boundaries. `preflight --skip-engines` timing out at 30s is a separate robustness signal.

**3. Operator-usability — 3.** Track B addressed the 0/10 readiness-blocker list, and the CLI verb tree is now rich. But two commands the runbook references (`preflight`, `today`) timed out in testing — the operator will hit those first and lose trust.

**4. Test discipline — 3.** 1576 tests pass, mutation kill rates ≥3 on all top-5 modules. But the quarantine-flow schema bug evaded every test — meaning tests validated the happy path, not the actual schema contract. W9-MUTATION-CANARY (deferred) is the right fix.

**5. Risk — 4.** From my lens: the single-worker directive (W7-SPEC-DRIFT) is enforced by convention, not by coord-layer assertion. Nothing in `coord/planner.py`, `coord/worker.py`, or `coord/integrator.py` validates that the progress-stream contract is upheld between handoffs. The non-deterministic audit sweeps make this worse — a contract-violating change could get a PASS on one sweep and never be re-checked.

**6. Top blocker.** Add a `coord/tests/test_contract_drift.py` that exercises the planner→worker→integrator handoff with synthetic progress-stream payloads and asserts schema conformance at each boundary. One test file catches the class of bugs the EngineHealth schema bug belonged to.

**7. Verdict: SHIP-WITH-FIXES.** The coord contract surface is load-bearing and currently validated only by integration tests that don't isolate handoff schemas — one contract-drift regression will silently propagate.

### M13-PROXY-SAFETY

_latency: 32688ms_

## Score

1. **Correctness — 3/5.** The 4-key proxy + circuit breaker + auto-quarantine exists, but the EngineHealth schema bug proves auto-quarantine-on-flap was *silently non-functional* until W8. Core safety claim was broken; now fixed, but trust is earned over time.

2. **Robustness — 2/5.** The `except Exception: continue` that swallowed quarantine writes is a fundamental anti-pattern in a safety-critical proxy path. What happens when all 4 keys are rate-limited or revoked? Fail-open or fail-closed? Circuit-breaker behavior is unspecified anywhere in the snapshot.

3. **Operator-usability — 3/5.** `engines-heal` + runbook help, but no proxy-specific operator guidance is visible. When the circuit breaker trips at 2am, does the non-technical operator see "traffic routed direct — keys exhausted" or a silent degradation?

4. **Test discipline — 2/5.** Zero proxy-specific tests mentioned. No proxy module appears in the mutation kill-rate table. The 32 W8 net-new tests are unspecified. There is no evidence that key rotation, circuit-breaker trip/recovery, or quarantine-on-flap are exercised by tests at all.

5. **Risk — 4/5.** The proxy's defining feature (auto-quarantine) was demonstrably broken for an indeterminate period. 4 on-disk API keys is 4× the credential-exposure surface of direct HTTPS with one key. A proxy that can silently fail its safety mechanisms is *strictly less safe* than direct HTTPS — it adds opacity, not protection.

## Top blocker

**Produce a proxy failure-mode matrix.** For each scenario — single key revoked, all keys exhausted, circuit-breaker open, all engines quarantined, TLS handshake failure — document: (a) observable behavior, (b) fail-open vs fail-closed, (c) operator action required. This is the artifact that answers "is the proxy actually safer than direct HTTPS?" Currently there is no such document anywhere in the snapshot.

## Verdict

**SHIP-WITH-FIXES.** The proxy's quarantine mechanism works post-W8 schema fix, but with zero visible proxy tests and no failure-mode analysis, we're shipping an opaque safety layer whose failure behavior is unknown — the one thing a proxy safety reviewer cannot accept.

### M14-OBSERVER-DESIGN

_latency: 23818ms_

## Score

| # | Dimension | Score | Justification |
|---|-----------|-------|---------------|
| 1 | Correctness | 3 | Observer runs, but two persistent STOPs are on the *detection layer itself* (STOP-HOOK, AUDIT-PROMPT) — the observer cannot cleanly pass its own audit. The `except Exception: continue` that silenced the schema bug for an entire wave proves the detection surface has blind spots. |
| 2 | Robustness | 2 | 3/7 audited rows flip PASS↔STOP with **zero code change between sweeps 2→3**. A detector whose verdict is a coin-flip on identical input is not robust — it's noise. The schema fix shows silent-failure patterns were load-bearing for weeks. |
| 3 | Operator-usability | 3 | The triage output is a confidence float with no guidance: non-technical operator sees `0.68 STOP` and has no decision procedure. No `--avg-of-N`, no "retry" button, no plain-language interpretation. `harness today` timed out in 30 s — operator can't even read the pulse. |
| 4 | Test discipline | 3 | 1576 passing tests exist, but the mutation canary (the deterministic regress check that bypasses MiMo) was *deferred* from W8. Observer's own behavior is untested for stability across repeated invocations. |
| 5 | Risk (30-day) | 4 | If the operator trusts a flippy audit gate, real regressions get waved through OR good work gets falsely STOP'd. Both erode authority credibility fast. |

**6. Top blocker:** Implement `W9-AUDIT-NONDETERMINISM-AVG` *before* re-running the readiness panel — an N=3 consensus where a row passes only if ≥2/3 sweeps return ≥0.70. This single change converts the audit gate from random signal to actionable triage and lifts correctness+robustness each by ≥1.

**7. Verdict:** **SHIP-WITH-FIXES** — The operator-readiness legs (preflight, runbook, heal, status-human) are genuinely load-bearing and should stay shipped, but the detection layer needs the averaging gate before the observer's verdicts carry operational weight.

### M15-DASHBOARD-UX

_latency: 45263ms_

## Score
1. **Correctness** - 3: Core harness logic works, but the FastAPI `/v2/*` layer lacks endpoints for Wave 8's critical `engines heal` and `preflight --fix` capabilities.
2. **Robustness** - 2: Backend CLI timeouts (30s hangs on `preflight` and `today`) indicate blocking I/O that will cascade to WebSocket clients as silent UI freezes or drops.
3. **Operator-usability** - 2: The non-technical operator's primary interface is the dashboard; leaving `engines heal`, `preflight --fix`, and `status human` as CLI-only renders them invisible.
4. **Test discipline** - 2: The 1576 tests cover backend logic, but the absence of API contract tests for `/v2/*` JSON schemas means frontend breakage bypasses CI entirely.
5. **Risk** - 4: If the dashboard cannot trigger or display the new system health actions, the 0/10 operator readiness vote will not improve.

**Top blocker**: Implement `/v2/engines/heal` and `/v2/preflight` REST endpoints in FastAPI and bind them to a "System Health" UI pane with live WebSocket status updates.

**Verdict**: HOLD — The dashboard completely fails to surface the new Wave 8 operator-readiness tools, leaving the non-technical GUI user unable to perform daily system maintenance.

### M16-TEST-QUALITY

_latency: 24470ms_

## Score

1.  **Correctness** — **4/5**. Core features (preflight --fix, engines-heal, status human) work as specified. Persistent audit STOPs on two rows indicate specified behavior isn't fully validated.
2.  **Robustness** — **4/5**. Schema bug fix shows good failure recovery. However, the `preflight --fix` auto-stash is a robustness risk (silent stash drop).
3.  **Operator-usability** — **5/5**. Single-page runbook, `today` command, and `engines-heal` directly address the W8 readiness panel's 0/10 blocker.
4.  **Test discipline** — **3/5**. 1576 tests pass, but MiMo audit non-determinism and two persistent STOPs suggest test boundaries are fuzzy or flaky, masking real gaps.
5.  **Risk** — **3/5**. Primary risk is MiMo audit non-determinism eroding trust in the gate; secondary is the stash surprise for operators.

**Top blocker**: **Implement `W9-AUDIT-NONDETERMINISM-AVG`**. The `--avg-of-N` flag for the audit command would make verdicts deterministic, turning non-det STOPs into actionable signals or confirmed passes.

**Verdict**: **SHIP-WITH-FIXES**. The operator-readiness foundation is solid and the harness is functional, but the flaky audit gate undermines the "every Wn row gets a MiMo audit" policy.

---
**Test Quality Deep-Dive**:
- **Overall**: Tests are **mostly behavioral**, focusing on module outputs and state changes (e.g., engine health transitions, fix outcomes). Mock usage is strategic for external APIs and file system calls, not heavy.
- **Sampled Modules**:
    1.  `engines/dispatcher.py` (Score: 5/5): Tests are highly behavioral, verifying routing logic and error handling. High mutation kill rate confirms effectiveness.
    2.  `coord/worker.py` (Score: 4/5): Strong behavioral tests after W7 recovery. Minor concern: some tests may mock too much of the integrator.
    3.  `orchestrator.py` (Score: 3/5): Tests are adequate but likely mock-heavy on the underlying `coord` module, reducing confidence in full integration.
- **Dead Test Code**: No significant dead code indicated. The 6 skipped tests appear intentional. The primary "dead" signal is the **non-deterministic audit verdicts**, which make certain test outcomes unreliable for decision-making.

### M17-DOCS-ACCURACY

_latency: 24585ms_

## Score

| Dimension | Score | Justification |
|---|---|---|
| **Correctness** | 2/5 | Closeout claims `harness today` shipped; CLI help shows only `morning-brief` — doc and code disagree on the command name. |
| **Robustness** | 2/5 | Both documented-ref commands (`preflight --skip-engines`, `today`) timed out at 30s; no evidence they actually run. |
| **Operator-usability** | 3/5 | Runbook and human-readable status are described clearly in the doc, but if the commands don't execute, the operator has a playbook for tools that don't work. |
| **Test discipline** | 2/5 | 1576 tests asserted but unverifiable — the harness itself won't boot; mutation-kill table covers 5 modules with no breadth claim for the rest. |
| **Risk** | 3/5 | Doc-code mismatch on a primary operator-facing command (`today` vs `morning-brief`) will confuse a non-technical operator following the runbook literally. |

**Top blocker**: Reconcile the `harness today` claim in the closeout and runbook with the actual CLI verb (`morning-brief`); update either the doc or the CLI so they match, and verify the chosen command actually executes without timeout.

**Verdict**: SHIP-WITH-FIXES — the documentation fabricates a command name that doesn't exist in the CLI tree, and every tested harness invocation timed out, so nothing in the doc can be independently verified as functional.

### M18-STATUS-CSV-DISCIPLINE

_latency: 20576ms_

## Score

1.  **Correctness (3)**: Core features function (preflight --fix, engines-heal, status --human), but the audit gate's own non-determinism (PASS↔STOP flips with no code change) undermines its authority as the canonical "done" signal.
2.  **Robustness (2)**: Schema bug in `EngineHealth` was a load-bearing, silent failure. Command timeouts in preflight/today suggest latent fragility. The auto-stash in `preflight --fix` is an operator-facing footgun.
3.  **Operator-usability (4)**: Significant progress (runbook, `status human`, `engines heal`). The non-technical operator now has a daily pulse and recovery verbs, but timeouts and stash surprises degrade trust.
4.  **Test discipline (4)**: 1576 tests pass; mutation canary is queued but not yet active (W9). The audit process itself lacks deterministic regression checks.
5.  **Risk (3)**: The **audit gate's non-determinism** is the top risk. If the system for judging "shipped" is unreliable, all downstream planning and confidence decay.

## Top blocker

**Fix `W8-AUDIT-PROMPT` (persistent STOP).** The audit prompt is the lens through which all work is judged. Its persistent STOP (low scores on precision/recall) indicates the audit's own instructions are flawed, causing the observed non-determinism. A stable, deterministic audit prompt is foundational.

## Verdict

**SHIP-WITH-FIXES.** The operator-readiness foundation is solid, but the audit system's non-determinism undermines confidence; fix the audit prompt to make the gate reliable before expanding.

### M19-WAVE-DISCIPLINE

_latency: 16895ms_

## Score

1. **Correctness** — 5. All 8 W8 rows shipped as specified; preflight --fix, engines heal, and status --human work as documented.
2. **Robustness** — 4. Schema bug fixed; but audit non-determinism (3 rows flipping PASS↔STOP with no code change) remains a reliability gap.
3. **Operator-usability** — 5. Operator runbook, `harness today`, and `engines heal` directly address the 0/10 readiness panel feedback.
4. **Test discipline** — 4. 1576 tests pass; but the persistent-STOP rows (W8-STOP-HOOK, W8-AUDIT-PROMPT) and audit non-determinism indicate test confidence isn't absolute.
5. **Risk** — 3. Main risk is audit non-determinism masking real regressions; mitigated by planned mutation-canary and averaging.

**Top blocker**: Implement `W9-AUDIT-NONDETERMINISM-AVG` to run audits in triplicate and average scores, lifting confidence in the audit gate's determinism.

**Verdict**: SHIP-WITH-FIXES. The wave discipline loop held across W6/W7/W8, but audit non-determinism is the one process risk that needs a concrete fix before scaling.

### M20-RISK-PROFILE

_latency: 52637ms_

## Top 5 Risks — 30-Day Window

### 1. **Engine Cascade Failure** — Score: 3/5
The quarantine flow was *silently broken* until W8-AUDIT-FOLLOWUP (`7081d93`). `EngineHealth.status` rejected `quarantined`/`recovering` writes via Pydantic, but `except Exception: continue` swallowed the error. **Probability: 40%** a similar silent-failure pattern exists in another engine path. Impact: dead engine wastes dispatch cycles, triggers cascading timeouts, burns Kimi/Claude quota on doomed retries. The `engines-heal` audit is non-deterministic (PASS-STOP-STOP) — confidence the fix itself is robust: **65%**.

### 2. **Audit Gate Unreliability** — Score: 4/5
MiMo's non-determinism is the *systemic* risk. Three rows flipped PASS↔STOP with zero code change. Two persistent STOPs (W8-STOP-HOOK, W8-AUDIT-PROMPT) may be legitimate gaps *or* auditor hallucination — the snapshot doesn't distinguish. **Probability: 80%** that at least one Wave 9 row will be incorrectly held up or incorrectly cleared by the audit gate within 30 days. Without `--avg-of-N` (queued, not shipped), every audit verdict is a coin-flip on soft criteria.

### 3. **Cost Overrun** — Score: 3/5
`--engine-fill aggressive` is the default. DeepSeek handles V-file + math + ship-critical work (the most expensive paths). `harness budget` exists but there's no evidence the operator checks it. **Probability: 35%** of hitting a rate-limit or billing surprise in 30 days, especially if Kimi slots fill and DeepSeek absorbs overflow. No circuit-breaker on per-day spend is visible.

### 4. **Operator Usability Cliff** — Score: 4/5
`preflight --skip-engines` and `today` **both timed out at 30 seconds** in the snapshot. A non-technical operator hitting timeouts on the two most important daily commands will lose trust immediately. The git-stash surprise in `preflight --fix` (`W9-PREFLIGHT-FIX-NOSTASH` queued but not shipped) could lose in-progress work silently. **Probability: 60%** the operator encounters a confusing failure within 30 days.

### 5. **Scope Creep / Wave Drift** — Score: 3/5
Five W9 candidates already queued. Persistent STOPs demand resolution. Readiness-panel rerun is pending. CRLF hook fix surfaced mid-closeout. **Probability: 50%** that Wave 9 scope doubles before the first row ships, pushing delivery out by ≥1 week.

---

## Score (0-5)

| Dimension | Score | Justification |
|---|---|---|
| **Correctness** | 3 | Core flows work; quarantine schema bug was ship-blocking and only found by accident |
| **Robustness** | 2 | Silent `except Exception: continue` pattern was load-bearing; CLI timeouts survive |
| **Operator-usability** | 2 | Two critical commands time out; git-stash surprise; `--help` is technical |
| **Test discipline** | 4 | 1576 passing + mutation gate ≥3; non-determinism is auditor-side, not harness-side |
| **Risk** | 4 | Engine cascade + audit unreliability compound; operator can't self-diagnose |

## Top Blocker
Ship `W9-AUDIT-NONDETERMINISM-AVG` (median-of-3 or avg-of-5) as the *first* Wave 9 row. Every subsequent audit verdict depends on this. Without it, the audit gate is advisory noise, not a gate.

## Verdict
**SHIP-WITH-FIXES.** The harness is functional and the W8 operator-readiness work is real progress, but the audit gate unreliability and CLI timeouts are operator-facing credibility risks that should be resolved before the next wave begins.
