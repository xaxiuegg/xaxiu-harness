# External review request — xaxiu-harness session 2026-05-22

You are reviewing the **structure** of a multi-engine LLM dispatch harness
that's been under intense iteration today.  You are NOT reviewing code
correctness; you are reviewing **process, role boundaries, and packet
shape**.  The operator believes throughput is below the achievable
ceiling.  Identify why and how.

---

## What xaxiu-harness is

A Windows-native Python tool that lets one human ("operator") run
multiple LLM engines (Kimi K2.6, DeepSeek V4 Flash, Anthropic, Gemini,
Xiaomi MiMo V2.5 / V2.5-Pro) as a coordinated dev team.  The
"dev manager" role is held by Claude inside a Claude Code session —
Claude drafts packets, dispatches to engines, reviews returned
FILE/REPLACE diffs, applies them, runs pytest, commits.

Core verbs:
- `harness coord plan --spec <md>` — engine decomposes a markdown spec into a WavePlan (one worker per discrete edit task)
- `harness coord run` — spawns one OS-process per worker; each worker dispatches its packet to an engine
- `harness coord integrate` — merges worker branches, runs full pytest, commits
- `harness dispatch_packet(force_engine=...)` — direct dispatch, used by the planner + observer
- `harness observer cycle-now` — periodic independent audit of recent dispatch activity

Engines available today (`SUPPORTED_BACKENDS`):
- `kimi`         → Kimi Code (api.kimi.com/coding/v1)
- `deepseek`     → DeepSeek (api.deepseek.com/v1, model `deepseek-v4-flash`)
- `mimo`         → Xiaomi MiMo Open Platform (Token Plan SGP for tp-prefix keys, model `mimo-v2.5-pro` text / `mimo-v2.5` multimodal)
- `anthropic`    → Claude API (no key in this env)
- `gemini`       → Google Gemini (no key in this env)
- `mock`         → test-only stub

Plus xaxiu-swarm wrapper identifiers (`swarm/kimi`, `swarm/kimi-api`, `swarm/deepseek`, `swarm/mimo`) for engines invoked via the external xaxiu-swarm CLI tool (kimi-cli is agentic; the others go through swarm subprocess for audit logging).

---

## Role rules Claude operates under

From persistent memory:

1. **`feedback_claude_strategic_role`** — Claude may directly author only 7 classes:
   chat / plan / spec / packet drafts / validation runs / merge ops / summaries / memory writes.
   Hard ceiling: 30 LOC code, 80 doc-lines per artifact.  Everything else **dispatches** to engines.

2. **`feedback_xaxiu_harness_full_dev_authority`** — Operator override 2026-05-20: act without per-action confirmation; lifts the 30-LOC ceiling.

3. **`feedback_plan_first_dispatch_default`** — Saved 2026-05-22 mid-session after operator caught inline-drift: full-dev-authority lifts the approval gate, NOT the dispatch-first rule.  Inline only for routing/safety-bootstrap, ≤30 LOC merge surgery, or every-engine-failing fallback.

4. **`feedback_no_permission_seeking`** — Pick + execute on operational choices.  Strategic alignment is the only ask-worthy class.

5. **`feedback_engine_routing_2026_05_11`** — Kimi first for non-V-file tasks (subscription cost), DeepSeek for V-file-spanning + math, Claude inline only when explicitly required.

6. **`feedback_status_csv_canonical`** — `coord/STATUS.csv` is the canonical task tracker; update on every transition.

7. **`feedback_check_memory_first`** — On any procedure friction (API config, dispatch, scheduling), grep memory + warehouse + spec/coord BEFORE trial-and-error and BEFORE escalating.

---

## Session arc — what actually happened today (2026-05-22)

### Round 1 — battle-test coord run
- Spec: `spec/samples/env-doctor-check.md` (add `_check_env_var_inventory` to doctor.py)
- Dispatched 2 workers via swarm/kimi.  Both workers eventually shipped, but the run surfaced **8 defects** in the coord pipeline: missing --engine flag on `coord run`, worker subprocess died on parent exit, budget meter rejected `swarm/*` names, v2 proxy auto-start failed silently, worktrees branched from master regardless of `depends_on`, `_dispatch_via_swarm` fell back to `cwd=None` when worktree missing (silent main-repo mutation risk), integrator squash failed on overlapping commits, integrator pytest timeout 120s < real 157s.
- Claude authored all 8 fixes **inline** over Wave 1 + Wave 1.5 + Wave 2.

### Wave 1.5 — engine fixes (operator surfaced new info mid-stream)
- Operator shared Artificial Analysis benchmark: Kimi K2.6 = 63.5s e2e, DeepSeek V4 Pro Max = 165s.  120s httpx read timeout was killing thinking-heavy queries.  Bumped to 600s.
- Added MiMo adapter (default Amsterdam endpoint originally).  Operator then pointed out: their actual Token Plan key is provisioned against Singapore (`token-plan-sgp.xiaomimimo.com`), not Amsterdam.  Patched default to SGP.
- Operator preferred config: DeepSeek V4 Flash with thinking ON.  Found we were auto-injecting `"thinking": false` into the JSON payload whenever model ended with `-flash` — which DeepSeek's API rejects with HTTP 400.  Removed.  Explicit `max_tokens=32768` added to Kimi + DeepSeek payloads (server defaults capped at ~16K).
- Added swarm/mimo identifier routing direct to in-process dispatch_packet (xaxiu-swarm has no mimo backend); MiMo auto-routing (Pro for text, V2.5 std for multimodal markers).

### Independent benchmark loop (Phase 2 of operator request)
- `scripts/bench_mimo_vs_kimi_deepseek.py` runs a 5-prompt × 4-engine parallel grid.
- v1 results: 3/4 engines broken (MiMo 401 from Amsterdam, DeepSeek 400 from thinking field, Kimi 60s rate-limit under parallel load).  All root causes fixed.
- v2 results: DeepSeek 5/5 (8.1s), MiMo Pro 5/5 (12.4s), MiMo Std 5/5 (12.7s), Kimi K2.6 3/5 (27s — 2 failures = rate-limit under parallel; sequential succeeds).

### Wave 2 (Round-1 carry-overs + auto-routing)
- D-NEW-2: planner blocked by `dpapi_direct` injection filter on harness-internal specs that mention `list_secrets()` in code-fence prose.  Fix: `trusted_source=True` kwarg on `dispatch_packet` for operator-authored ingress.
- D-NEW-5: `mimo` missing from closed Literal types (`ActiveDispatch.backend`, `RoutingAction.backend`, `WavePlan.planner_engine`).
- D-NEW-4: opaque `run_id` regex.  Planner now auto-replaces malformed run_ids with `_new_run_id()` + WARNING.
- D7 (last Round-1 defect): integrator squash strategy now commits between workers so overlapping dep-branched commits don't break the merge.
- Claude authored **all of these inline.**  Operator caught this drift.

### The inline-drift correction (operator-driven)
Operator: *"you decided to pivot in fixing certain areas yourself instead of having sub agents do it... I feel like if you plan before proceed inlining, you would have had better results."*

Saved `feedback_plan_first_dispatch_default` to memory.  Then ran a corrective Wave 2 dispatch demonstrating the discipline:
- 4 packets (`spec/samples/wave1-*.md`) drafted earlier but never dispatched.
- v1 dispatch (no read-set in packet): 4 engines produced unusable diffs — hallucinated SEARCH anchors against a codebase they hadn't seen.
- v2 dispatch (read-set embedded, cli.py windowed to anchor function ± 160 lines): 3/4 packs shipped clean:
  - Pack A (Kimi K2.6): `coord status --json` — 1 test assertion patch
  - Pack B (MiMo V2.5-Pro): `budget summary --since-days` — datetime import + test data tweak
  - Pack D (Kimi K2.6): `observer cycle-now --dry-run` — Windows-safe filename
  - Pack C: failed all 3 engine attempts (DeepSeek → MiMo → DeepSeek) with `internal` / `engine_init_failed`.  Deferred.

### Observer arming check (operator question right before this review)
- Observer was armed via Windows Task Scheduler (3 entries firing hourly + daily).
- But every prior auto-cycle had `dispatch_success: false, error: "unsupported_force_engine"` because cycle.py dispatched with `engine="swarm/deepseek"` and `dispatch_packet` only accepts bare backends.  Also `adapters/observer/harness-adapter.yaml` did not exist.
- Both fixed.  Fresh cycle now reports `engine: mimo, response: [], findings: 0` (clean audit).

### Cumulative session metrics
- 26 commits pushed (5112168 latest)
- Pytest 1224/1224 green (+89 net new tests since 1135 baseline at session start)
- 3 engines live-validated: DeepSeek Flash thinking-ON, MiMo Pro SGP, Kimi K2.6
- 3 features shipped via engine dispatch (Packs A/B/D), rest shipped via inline Claude authorship

---

## The operator's question to YOU

> *"I don't think this is the true possible speed with the way we structure."*

Specifically the operator asks you (Kimi / MiMo / DeepSeek, whichever this packet was dispatched to):

1. **Structural critique.** Where is Claude's role-definition leaking?  What's the mismatch between the stated "dev manager dispatches; engines author" pattern and what actually happens in transcript?

2. **Packet-shape critique.** v1 dispatches without read-set produced hallucinated diffs.  v2 with read-set worked.  What other packet-shape failures should we expect, and how should the packet template evolve?

3. **Throughput ceiling.** If Claude had perfectly executed dispatch-first from minute 1, what would 8 hours of work look like in number of shipped features?  Where are the remaining bottlenecks beyond Claude's inline-drift?

4. **Conflicting-memory risk.** With 50+ memory entries influencing Claude's behavior + project-specific overrides (full-dev-authority for xaxiu-harness, strategic-role for warehouse) + 3 cross-project stop-hooks, what's the likelihood of a memory-conflict misfire?  Is the project folder structure (single `~/.claude/projects/D--Projects/memory/` for ALL projects) a source of friction?

5. **Migration recommendation.** Should xaxiu-harness migrate to a new project folder with isolated memory + stop-hooks?  What would the migration look like?  Or is sharing memory across projects a feature, not a bug?

---

## Output rules

- Output **markdown only**.  No tool calls.
- Structure your response with these section headings:
  - `## 1. Structural critique`
  - `## 2. Packet-shape recommendations`
  - `## 3. Throughput ceiling estimate`
  - `## 4. Memory + project-folder risk`
  - `## 5. Migration verdict`
- Each section: 3–8 specific findings, each with severity (LOW/MED/HIGH) and 1-line actionable recommendation.
- No padding, no boilerplate.  Be terse and specific.
- End with `## Bottom line` — one paragraph, your top-3 changes to ship next.
- Total length budget: ~600–900 lines.  Going longer wastes tokens; going shorter loses specificity.
