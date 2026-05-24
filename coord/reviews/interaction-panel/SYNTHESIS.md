# Interaction-arc panel — 10-reviewer synthesis

_Dispatched: 10 personas, elapsed 71.0s_

## Per-persona responses

### K1-operator-ux

1. **W8-STOP-HOOK-BATCH** — modify `.harness/stop-hook.sh` to (a) ignore `mtime` drift under `mutation/` working directories and (b) emit one batched `STATUS.csv` warning at wave end instead of per-file fires. Reasoning: W7 burned ~6 operator turns on ack-and-touch loops that contained zero decision value; the hook is crying wolf and the operator is acting as a human cron job.

2. **Preserve:** The Phase B panel-closeout composite. The operator honestly translated a 4/6 split into a conditional accept plus a backlog-locked W7 worker without gaming the gate. Codify this as a `panel-synthesis.md` template so the pattern survives session handoffs.

**Replace:** Audit-script semantic STOPs. In W6, the auditor expected behavioral integration but received unit + sentinel coverage, forcing the operator to manually interpret and reroute. Add a structured `audit-scope` field (e.g., `[unit|integration|sentinel]`) to each gate so mismatches auto-open a pre-filled remediation branch instead of halting with an opaque STOP.

3. **Theme: Eradicate operator toil loops.** The next waves should (a) finish the stop-hook silence work, (b) block wave close when worktree branches contain unmerged files like `transport.py` (W6-B1 partial), and (c) harden the engine-transport ABC so MiMo batch-HTTP drops are caught at dispatch, not silently excluded. The operator should review outcomes, not nurse diffs through gates.

### K2-test-quality-meta

1. W8-MUTATION-CANARY / `proxy/dispatch.py`. Run a 3-mutant boundary spot-check (flip a timeout comparator, remove an empty-iterator guard, swap an and/or) against the existing test suite. A 0.0 kill rate confirms the same W6-A3 blind spot hides in the untouched modules; a >0 result lets you rotate the canary to `observer/hook.py`, `loops/scheduler.py`, and `dashboard/state.py` without ever paying for a full sweep. Behavioral coverage ≥3 is necessary but not sufficient—boundary mutants are the real survivors.

2. WORKING: The honest audit-STOP paired with an external panel gate (W6 closeout → conditional backlog lock). It kills velocity bias and forces evidence-based unlocks; preserve exactly this mechanics. NOT WORKING: Defaulting to dense, full-module mutation sweeps when entering new territory. W6-A3 proved that is expensive and still left four modules unexamined. Replace with the rolling 1-file/3-mutant canary as the mandatory pre-sampler before any full sweep is budgeted.

3. THEME: "Boundary-harden the untrusted perimeter." Aim the next 2–3 waves at moving from behavioral demonstration to boundary-condition kill verification in engine-adjacent modules (proxy, observer, loops, dashboard). Locate gaps via canary sampling, then surgically inject boundary-focused tests (timeouts, empty states, off-by-ones) and make the canary gate a standard pre-commit requirement.

### K3-architecture

1. **W8-STATE-COMPRESSION** — collapse the JSONL and JSON artifact files into the existing SQLite schema, targeting the integrator’s write path (e.g., `harness/state/artifact_store.py` or equivalent). Reasoning: single_worker serializes execution, removing the last justification for fragmented file-based persistence; a unified ACID store gives the integrator atomic commits and the observer a single query surface, eliminating format drift and halving the stop-hook noise caused by scattered mtime updates.

2. **Working:** The honest audit-STOP plus conditional backlog-lock pattern demonstrated in the W6→W7 panel transition. It prevents spec-shaping, enforces mutation kill-rate thresholds before features ship, and should remain the permanent quality gate.  
**Not working:** Mtime-based sentinel hooks firing repeatedly during mutation sweeps because STATUS.csv drifts against touched files. Replace this with a content-addressed or batch-closed STATUS update so mutations do not trigger sentinel storms.

3. The next waves should aim at three themes: **(a) unify state under one SQLite surface** so the dispatch+integrator+observer trinity shares a single source of truth; **(b) formalize a capability-aware dispatch registry** so the enforced single_worker is routed only to backends that support the required transport mode (SSE vs. batch) and reasoning budget; and **(c) promote the observer from passive sentinel to active operator surface** that can veto or recommend single_worker assignments based on real-time backend health and state-layer pressure.

### K4-cost

1. W8-AUDIT-ROUTER row / `audit/router.py`: build a tiered failover so MiMo remains default for audit, panel, and planner, but DeepSeek—already integrated at $0.35 via the W7-B1 StreamingTransport ABC—auto-assumes the role on MiMo 429 or quota-exceeded. This hedges the MiMo monoculture without rewriting the operator directive: if MiMo tightens, the harness degrades to the cheap engine rather than halting.

2. WORKING: The composite panel-closeout with conditional backlog locks (W6 → W7 mutation gating) preserved honest STOPs, prevented spec-shaping, and lifted kill rates from 0.0–1.0 to ≥3.0. Keep that route. NOT WORKING: STATUS.csv mtime hook noise burned ~6 acknowledge-touch token cycles in W7, and the Kimi `reasoning_content`/`max_tokens` footgun wasted budget on empty returns. Replace mtime checks with an append-only operation journal and enforce a Kimi max-tokens floor above reasoning budget.

3. Theme: "Cost-resilient cognitive distribution." Decouple audit, panel, and planner from any single engine via a cost-router; eliminate hook-noise token leaks; establish engine tiers (DeepSeek bulk, Kimi deep-reasoning, MiMo planner-override) so a quota tightening becomes a budget routing event, not a wave-blocking failure.

### K5-devils-advocate

1. **Suspend the MiMo audit directive and launch W8-SMOKE-GRAMMAR.** The single best move is to replace the per-Wn audit gate with a machine-checkable acceptance grammar—deterministic schemas for planner outputs, transport dispatch traces, and STATUS.csv freshness—plus a mandatory 60-second integration smoke run against a local mock endpoint. W6-C2 exposes the audit gate as a false-positive factory: it STOPped at 0.62 because the auditor wanted “behavioral integration” but only got unit tests and a source-grep sentinel; the 10-reviewer panel later accepted it 8-2. If the smoke run passes and the grammar validates, the wave should ship regardless of mutation kill rate.

2. **Preserve the conditional-close + backlog-lock pattern from Phase B.** It kept W6 moving without overriding safety and gave W7-MUTATION-WORKER the room to fix A3. **Kill the audit script as a hard gate.** Proxy metrics (kill rate, diff coverage) are too noisy for an immature harness; they punish partial retrofits that later integrate cleanly. Replace the MiMo audit with the smoke-run contract above, and retire the STATUS.csv mtime stop-hook for a hash-based event invalidation—those ~6 fires in W7 were pure friction.

3. **Theme: Mechanical contracts over crowd review.** The next waves should turn the harness into a self-validating system: semantic schemas for engine I/O, CI-style smoke tests per transport adapter, and reviewer panels demoted to advisory-only. Stop auditing every commit; start verifying every integration surface mechanically.

### M1-strategy

1.  **Next-Best Move:** The single next move should be **W8-A: Transport Unification**. The foundation is now strong (W7 achieved 0 STOPs, kill rates ≥3), but the engine transport layer has fragmentation: `StreamingTransport` ABC exists, MiMo was explicitly left OUT of the refactor (still batch HTTP), and the Kimi/DeepSeek paths diverged. This creates scope drift risk. Unifying the transport under one ABC implementation is a foundational move that enables cleaner future feature waves (e.g., a real observer surface) without compounding tech debt.

2.  **Working Pattern:** The **panel review + backlog lock** mechanism (from Phase B) is highly effective. It externalized a critical decision (A3's condition), preventing operator overload and creating a verifiable gate. This should be preserved as a standard practice for ambiguous deliverables. **Not Working:** The **constant stop-hook noise** for STATUS.csv is a tax on flow. The tooling misaligns with the mutation workflow's high file-churn. This should be replaced with a smarter mtime-ignore or a hook that batches/delays STATUS updates.

3.  **Next 2-3 Waves Theme: Consolidate and Specialize.** The theme should be **"Unify the core, then surface the operator."** First, consolidate fragmented layers (transport, as mentioned; also audit/reporting). Then, begin specializing components for operator use—turning the observer from a log-scraper into a dashboard with actionable signals, and formalizing the wave-planning tooling. This builds on W7's clean execution to create leverage, not just more moving parts.

### M2-process

## 1. Next-Best Move

**W8-STOP-HOOK-DEBOUNCE** — rewrite the stop-hook's dirty-file check to exempt mutation-sweep artifacts (or debounce by comparing STATUS.csv content-hash instead of mtime). Six hook fires across W7 each burned a turn just to `touch STATUS.csv`. That's 6 lost turns of autonomous execution on the cleanest wave yet. The hook is meant to catch real drift; right now it's a false-positive machine. Fix it and W8+ waves ship faster with less operator babysitting.

## 2. Working / Not Working

**Working — preserve:**
- **"Proceed per rec" delegation.** Operator trusts panel synthesis → Claude executes linearly without second-guessing. W7 proved this: 8/8, 0 STOPs. The operator's role is *choose the composite move*, Claude's role is *ship it*. That contract is clean.
- **Honest closeout reporting.** W6 documented both STOPs without spec-shaping to override the gate. That builds trust and gives the panel real signal to work with.

**Not working — replace:**
- **Stop-hook as status oracle.** It fires on mtime churn, not semantic drift. Every fire costs a turn + operator attention. Replace with content-hash or a debounce window.
- **Escalation threshold is too coarse (L5 only).** W6-B1 shipped as "partial" without escalation. A transport module going unmerged is arguably L4, but Claude had no mechanism to flag it — it just shipped partial. There needs to be a mid-tier signal: "not blocking, but operator should know."
- **Latent config bugs surface by accident.** Kimi's max_tokens=4000 eating the reasoning budget was found only because the operator eyeballed empty panel returns. There's no automated "did this call return empty content?" guard. That's a process gap, not a one-off.

## 3. Next 2–3 Waves — Theme

**"Tighten the detection layer."** The *execution* layer is now strong (worker pipeline, transport ABC, mutation infrastructure). What's weak is *automated feedback*: the stop-hook is noisy, audit gates required 3 retries to articulate what they actually wanted (behavioral integration vs. unit sentinel), and there's no guard against silent empty returns from any engine. The next waves should make the harness *self-noticing* — debounced hooks, response-non-empty guards, audit criteria that get written down before the sweep runs, not retrofitted after the third STOP. The goal: the operator shouldn't need to eyeball anything to keep the wave clean.

### M3-risk

**1. Next-best move**  
Harden W7-B1-RETROFIT (`engine/transports.py`). The StreamingTransport ABC is now the path for DeepSeek and Kimi streaming, but MiMo is excluded (batch HTTP). Any ABC break (e.g., `consume_sse` timeout mismatch, missing `reasoning_only` propagation) will silently kill two engines. A targeted wave—`W8-TRANSPORT-REDUNDANCY`—should add: (a) negative-path tests for SSE drops mid-stream, (b) a fallback to batch-HTTP on streaming failure, (c) a transport health-check dashboard line in STATUS.csv.

**2. Interaction patterns**  
**Working:** The operator’s “audit STOPs with honest reporting” loop is gold. It forces real quality gates and prevents spec-shaping.  
**Not working:** The stop-hook noise from STATUS.csv mtime churn. It burns turns and masks real signals. Replace with a `--ignore-mtime-for-mutation` flag that suppresses hook fires when only known mutation-kill-rate files change.

**3. Next 2-3 waves theme**  
**Theme: Observability + Engine-Layer Consolidation.**  
Wave 8 should unify engine transports under a single resilience wrapper (retry, fallback, health reporting). Wave 9 should turn the MiMo auditor into a first-class operator surface: a live dashboard of audit-STOP history, mutation-kill trends, and transport health. Wave 10 should add a lightweight CI layer that runs the full mutation suite + transport smoke tests on every commit, ensuring the hardening sticks as new features land.

### M4-velocity

1. **Next Best Move:** Optimize the mutation testing pipeline. The constant stop-hook noise (~6 fires) and the time/attention cost of manual STATUS.csv touches during mutation sweeps are clear friction. W8 should implement a smarter file-change filter in the stop-hook to ignore mtime-only changes in mutation-related files, or batch the verification. This directly removes a recurring operational drag.

2. **Working Pattern:** The external review panel (10 agents) providing conditional acceptance with backlog-lock gates (e.g., A3 → W7-MUTATION-WORKER). It forces accountable quality jumps and aligns with "don't ship faster than you validate." **Not Working:** The stop-hook's broad mtime trigger for STATUS.csv is creating noise tax. It should be replaced with a content-hash or purpose-aware check for changed files.

3. **Next 2-3 Wave Theme:** **Shift from validation to verification ergonomics.** The core pipeline works; now make the quality gates (mutation, audit, tests) faster, cheaper, and less disruptive. This means parallelizing/optimizing verification runs, refining the stop-hook logic, and possibly adding a local cache for engine responses to reduce latency during iterative testing. The goal is to sustain the pace without the constant context-switching overhead.

### M5-tech-debt

1. **Single Next-Best Move**: Execute `W8-CONFIG-DRIFT-AUDIT`. The single most compounding debt is **configuration drift**—specifically, the disconnect between the pinned engine configurations in `config.py` (or equivalent) and the actual state of the engines referenced in `transport.py` and the updated `StreamingTransport` ABC. This drift is silent, multiplies with every new engine variant or parameter change, and will cause cascading failures in future validation waves. Fixing this before adding new features or observers is critical. A one-off audit row to snapshot, diff, and lock down the config against the known-good transport layer is the most debt-efficient move.

2. **Working/Not-Working Patterns**:
   *   **Working**: The **panel-synthesis + backlog-lock** approach (as seen with A3/MUTATION) is highly effective. It transforms a STOP into a structured, conditional continuation with clear gates. This should be the default response to ambiguous audit outcomes.
   *   **Not Working**: The **stop-hook reactivity** around STATUS.csv is pure friction. It's a tax on focus. The pattern of constant acknowledgment and file-touching for mtime should be replaced by a more resilient observer (e.g., a debounce or a separate watcher process) or by relaxing the hook's sensitivity.

3. **Next 2-3 Waves Theme**: **Solidify the Observability and Control Plane**. This means: 1) **Lock the configuration baseline** (as above), 2) **Promote the observer to a first-class, actionable surface** (not just alerts, but state queries and safe overrides), and 3) **Introduce a minimal, wave-local CI pipeline** (pre-commit hooks for lint/unit tests, and a wave-closeout script that runs the key validation suites and generates a immutable report). This theme pays down debt by making the system's state explicit and its operations repeatable.
