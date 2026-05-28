# Agent A: Plan-document staleness audit (2026-05-28)

## Summary

- **~24 claims audited** across CURRENT_PLAN.md, CLAUDE.md (project), and project memory MEMORY.md index.
- **5 STALE** (load-bearing — affects routing, version, counts, and engine families).
- **2 PARTIAL** (mostly fresh but with one outdated phrase or number).
- **15 FRESH** (confirmed accurate or accurately scoped as truly zero).
- **2 NEEDS-CLARIFICATION** (cannot be verified without operator input — e.g. memory entries about deprecated workflows that the operator may still find historically useful).

The CURRENT_PLAN.md "What's next" surface IS fresh — the morning's reconciliation work + the W14-PLAN-CONSISTENCY-TEST-AND-REWRITE row has done its job. The remaining drift is concentrated in **CLAUDE.md (project)** which is showing pre-v0.6 version/engine-family staleness, and in **memory entry counts**.

---

## Stale findings

### Finding 1: CLAUDE.md "Current state — v0.5" header

- **Plan says** (`D:\xaxiu-harness-standalone\CLAUDE.md:38`): `## Current state — v0.5 (v2 production-hardened + Phase-5 operator UX layered on top)`
- **Reality**: Current version is **v0.6.8** (pyproject.toml:`version = "0.6.8"`, `src/harness/__init__.py:__version__ = "0.6.8"`). CURRENT_PLAN.md line 4 already references "v0.5.5 → v0.6.3" for the morning roadmap and "0.6.7 → 0.6.8" for the afternoon rotation playbook shipping. CLAUDE.md is six minor versions out of date in its section header.
- **Verdict**: STALE
- **Suggested action**: Change `## Current state — v0.5 (...)` to `## Current state — v0.6.8 (...)` OR drop the explicit version number entirely (mirror the P6 audit fix on test counts: "live count beats stale doc numbers"). The note 2 lines below already says exactly that for test counts.

### Finding 2: CLAUDE.md engine-routing section uses pre-Pattern-B family vocabulary

- **Plan says** (`D:\xaxiu-harness-standalone\CLAUDE.md:88-96`):
  ```
  ## Engine routing (read coord/dev_loop/dispatch-rules.md for the full table)
  - swarm/kimi (xaxiu-swarm wrapping Kimi-Code CLI subprocess) → agentic, applies in-place edits...
  - swarm/kimi-api (xaxiu-swarm + Kimi REST) → non-agentic. Single text response...
  - swarm/deepseek (xaxiu-swarm + DeepSeek REST) → non-agentic. Same as kimi-api...
  ```
- **Reality**: `coord/dev_loop/dispatch-rules.md` (which CLAUDE.md says to "read for the full table") was rewritten on 2026-05-26 (W14-SWARM-CLAUDE-BACKENDS-VERIFIED) to document **three engine families**:
  1. Swarm-based legacy (`swarm/kimi`, `swarm/kimi-api`, `swarm/deepseek`) — still active but `kimi-api` allowlist-fragile and Kimi terminated per W14-KIMI-AUTH-RESTORE
  2. Swarm TOS-safe agentic (`swarm/claude-mimo`, `swarm/claude-kimi`, `swarm/claude-deepseek`) — new
  3. Pattern B subprocess (`kimi-via-claude`, `mimo-via-claude`, `deepseek-via-claude`) — the surface used by `harness ask` and `harness engines recommend`
  
  Additionally, `harness engines compatibility-matrix` (shipped 2026-05-28 as Phase 1.2) now provides the live N×M table showing 6 engines and their consumption surfaces — far richer than CLAUDE.md's 3-line summary. CLAUDE.md's swarm-only framing is also at odds with how `harness ask` is documented in docs/AGENT_REFERENCE.md § 8 (which leads with Pattern B + the proxy).
- **Verdict**: STALE
- **Suggested action**: Replace the 3 bullets with either (a) a pointer to `harness engines compatibility-matrix` for live routing data + `harness engines describe <name>` for per-engine metadata, with a note that swarm/kimi etc. are the legacy family, OR (b) preserve the bullets but add the two new families + reference Pattern B. The "Mandatory flags" + "Cooldowns" bullets remain accurate for swarm/* but no longer apply to Pattern B work, which is the primary surface now.

### Finding 3: CLAUDE.md memory directory entry count is stale

- **Plan says** (`D:\xaxiu-harness-standalone\CLAUDE.md:3`): "This project has its own isolated Claude Code memory directory at `~/.claude/projects/D--xaxiu-harness-standalone/memory/` (**43 entries**) — warehouse-specific memory is intentionally NOT loaded here."
- **Reality**: `find ~/.claude/projects/D--xaxiu-harness-standalone/memory/ -maxdepth 1 -type f -name "*.md"` returns **57 entries** (and the directory also has an `archive/` subdir with 4 more). The count grew by 14 since the doc was written (new entries include `feedback_grep_before_declare_greenfield_2026_05_28.md`, `feedback_velocity_vs_mandate_2026_05_28.md`, `project_agentic_operator_roadmap_2026_05_28.md` + 11 others).
- **Verdict**: STALE
- **Suggested action**: Drop the explicit count (same pattern as the P6 test-count fix); change "(43 entries)" to "(entries listed in `MEMORY.md`)". Hard counts in this file go stale faster than commits land, exactly as the existing P6 note acknowledges for tests.

### Finding 4: CLAUDE.md "Memory entries this session inherits" points at wrong path

- **Plan says** (`D:\xaxiu-harness-standalone\CLAUDE.md:111`): "Load these from `~/.claude/projects/D--Projects/memory/` (operator's Claude memory) at session start:"
- **Reality**: The project is at `D:\xaxiu-harness-standalone\` (since 2026-05-22 migration per MIGRATION.md). Its memory directory is at `~/.claude/projects/D--xaxiu-harness-standalone/memory/` — that's the same path CLAUDE.md line 3 names correctly. The `D--Projects/memory/` path was the pre-migration warehouse-shared location and would now point at warehouse memory which is explicitly NOT what this section should load.
- **Verdict**: STALE (load-bearing — actively misroutes any agent that follows the instruction)
- **Suggested action**: Change `~/.claude/projects/D--Projects/memory/` to `~/.claude/projects/D--xaxiu-harness-standalone/memory/`. Cross-check the 6 named entries — `feedback_xaxiu_harness_full_dev_authority`, `reference_xaxiu_harness_error_taxonomy`, `feedback_xaxiu_swarm_backend_agentic_differences`, `feedback_operator_inputs_become_harness_config`, `user_non_technical_role`, `feedback_multi_session_scoping` — are all present at the correct path.

### Finding 5: `reference_xaxiu_harness_error_taxonomy` memory entry says "Implementation pending Wave A.5"

- **Plan says** (`~/.claude/projects/D--xaxiu-harness-standalone/memory/reference_xaxiu_harness_error_taxonomy.md`, surfaced in `MEMORY.md` index): "Tag format `L<n>.<domain>.<code>`. **Implementation pending Wave A.5.**"
- **Reality**: The taxonomy IS implemented. `src/harness/errors.py` carries the full L1-L5 class hierarchy with comments labelling each tier ("L3 — recoverable operational failures", "L4 — integrity threats; quarantine, no global halt", "L5 — operator action needed"). `HarnessError.exit_code()` maps levels to exit codes (0/0/1/3/4 for L1-L5), `format_escalation_banner()` renders the operator-facing banner with the "OPERATOR ESCALATION (L5)" marker, and there are concrete subclasses for each tier (DispatchExhausted/EngineTimeout/EngineRefusal at L3, PacketTrap/SchemaViolation/WorktreeMissing at L4, DpapiUnreadable/AllEnginesUnreachable/GitPushFailed/ConfigCorruption/WavePersistentlyFailing at L5). `spec/errors.md` also exists (referenced in CLAUDE.md line 49).
- **Verdict**: STALE (memory entry under-claims shipped capability)
- **Suggested action**: Either (a) update the entry's last paragraph to "Implemented in `src/harness/errors.py` + `spec/errors.md`" instead of "Implementation pending Wave A.5", OR (b) leave the memory entry alone (memory entries are timestamped snapshots; the operator may prefer to keep them as origin-of-record). If editing, the `MEMORY.md` index entry should match.

---

## Partial findings

### Finding 6: CURRENT_PLAN.md "Deferred backlog (NOT this month)" lists `W14-LOCAL-LLAMA-FALLBACK`

- **Plan says** (`D:\xaxiu-harness-standalone\coord\CURRENT_PLAN.md:91`): "**W14-LOCAL-LLAMA-FALLBACK** — keep as outage insurance row; ship only if/when cloud-engine outage actually happens (DeepSeek amendment 1)"
- **Reality**: Truly zero. No grep hit for `llama|llamacpp|ollama|local_llm` in `src/harness/`. STATUS.csv has no `LOCAL-LLAMA` row.
- **Verdict**: PARTIAL — the row is accurately scoped, but the framing "ship only if/when cloud-engine outage actually happens" sits awkwardly with the live $195/mo PAYG pool the plan also describes (which provides 4-engine redundancy already). Not a staleness bug, more a strategy-narrative question for the operator.
- **Suggested action**: No edit required from staleness perspective; consider whether the outage-insurance argument is still load-bearing given the redundant pool.

### Finding 7: `feedback_observer_system` memory entry path

- **Plan says** (`~/.claude/projects/D--xaxiu-harness-standalone/memory/reference_observer_system.md`, description field): "60-min Kimi cycles in-session + 22:53 DeepSeek daily retro via Windows Task Scheduler; lives at **dev-panel-runs/ag-qty-bug-v101/observer/**; auto-arms via CLAUDE.md hook on every session start"
- **Reality**: The path `dev-panel-runs/ag-qty-bug-v101/observer/` is a warehouse path (carried over from migration). The actual observer location for this project is `coord/observer/` (verified — `coord/observer/cycles/`, `coord/observer/flags/`, `coord/observer/observer-state.json` etc. exist). Functionally the entry's broader point — Task Scheduler tick + 60-min cadence + flag escalation — is still correct.
- **Verdict**: PARTIAL — load-bearing path is a wrong-project leftover, but the workflow description is accurate.
- **Suggested action**: Update the entry's description to read `coord/observer/` for the path, OR archive the entry if the operator considers the warehouse observer system no longer relevant.

---

## Fresh findings (confirmation — no action needed)

- **CURRENT_PLAN.md "What's next" Week 2 row `W13-BACKUP-ENCRYPTION`**: confirmed truly truly-zero greenfield. `src/harness/backup.py` has zero `encrypt|cipher|crypto|AES` matches. The 347-LOC create/list/prune/restore manager is shipped (STATUS row W13-BACKUP-RESTORE 2026-05-25) as the plan accurately states.
- **CURRENT_PLAN.md "Single most important action (live)"**: correctly points at W13-BACKUP-ENCRYPTION; accurate per Finding 1 above for the parallel-blocked operator note about DASHSCOPE_API_KEY.
- **CURRENT_PLAN.md Week 3 Polish row `Schema versioning`**: row says "when first data-structure change happens". Reality: 7 files in `src/harness/` use `schema_version` field (`coord/schemas.py` × 3 dataclasses, `coord/checkpoint.py`, `loops/state.py`, `proxy/state.py`, `backup.py` × 2, plus `agent/__init__.py` writes `schema_version: 1` to `.harness/config.json` and `mutation_manifest.py` + `operator/saved_profile.py` also use it). However the infrastructure is **defensively in place** awaiting actual schema bumps; the row's "ship when first change happens" framing matches the W13-MASTER-PLAN-PANEL row's resolution ("shipping infrastructure now + skip-by-default enforcement test until first real schema change"). Fresh.
- **CURRENT_PLAN.md Week 3 Polish row `harness commands --did-you-mean`**: confirmed truly zero. `python -m harness commands --help` returns "No such command 'commands'." No `did_you_mean` references in `src/harness/cli.py`. The Click subcommand-suggestion fallback (which Click provides natively) is the closest thing and is not what the row contemplates.
- **CURRENT_PLAN.md Week 3 Polish row `Hallucination test harness`**: confirmed truly zero. No `tests/test_hallucinat*` files; the only `hallucinat` matches in tests are in comments/docstrings (test_docs_no_future_as_present.py and test_plan_verb.py guard against doc-vs-code drift but don't constitute a hallucination test harness for engine output). `--audit` mode (shipped) is a runtime hallucination guard but is not a test harness for the harness itself.
- **CURRENT_PLAN.md "Confirmed anti-patterns" #1 (`W13-AUDIT-JSONL` shipped, ✅ check)**: confirmed shipped. `src/harness/audit_jsonl.py` exists + STATUS W13-AUDIT-JSONL 2026-05-25 + ~/.harness/audit.jsonl has 2289 legacy entries per W14-AUDIT-CHAIN-HMAC notes.
- **CURRENT_PLAN.md "Confirmed anti-patterns" #6 (`W13-INSTALL-VERIFY` gates every PR, ✅ check)**: confirmed shipped. `tests/test_install_verify.py` exists with `slow` marker; STATUS W13-INSTALL-VERIFY 2026-05-25; CI workflow adds the slow-marker step (verified via grep on workflow files in prior session, recorded in W13-INSTALL-VERIFY row notes).
- **CURRENT_PLAN.md "Confirmed anti-patterns" #8 (added today, velocity-vs-mandate)**: confirmed memory entry `feedback_velocity_vs_mandate_2026_05_28.md` exists; CURRENT_PLAN.md correctly references it.
- **CLAUDE.md v1 core component table — file paths**: all 12 paths verified to exist (`src/harness/adapters/`, `src/harness/cli.py`, `src/harness/engines/`, `src/harness/state/`, `src/harness/secrets/dpapi.py`, `src/harness/errors.py`, `spec/errors.md`, `src/harness/operator/`, `spec/operator-modes.md`, `src/harness/status/`, `spec/status-tracker.md`, `src/harness/observer/`, `spec/observer.md`, `src/harness/heartbeat.py`, `src/harness/state/inspect.py`, `src/harness/dashboard/`, `src/harness/loops/`, `src/harness/replay.py`, `src/harness/budget.py`, `src/harness/session/`, `spec/session-handoff-monitor.md`).
- **CLAUDE.md v2 architecture component table — file paths**: all 14 paths verified to exist (`spec/multi-agent-harness-architecture.md`, `src/harness/proxy/`, `src/harness/coord/schemas.py`, `src/harness/coord/planner.py`, `src/harness/coord/worker.py`, `src/harness/coord/worktree.py`, `src/harness/coord/checkpoint.py`, `src/harness/coord/coordinator.py`, `src/harness/coord/integrator.py`, `src/harness/coord/canceller.py`, `src/harness/coord/notify.py`, `src/harness/dashboard/v2_routes.py`, `src/harness/dashboard/app.py`, `src/harness/engines/mock.py`, `tests/test_coord_smoke_e2e.py`, `src/harness/adapters/schema.py`, `src/harness/lint.py`, `src/harness/observer/chat.py`).
- **CLAUDE.md v1 core row "Engine ABC + 5 concrete (kimi/deepseek/anthropic/gemini/mock) + auto-fallback"**: TECHNICALLY PARTIAL — there are now **6 concrete engines, not 5** (DeepSeekConcrete, KimiConcrete, AnthropicConcrete, MiMoConcrete, QwenConcrete in `concrete.py` + MockEngine in `mock.py`). The "5 concrete" count predates W14-MIMO (2026-05-22) and the W14-KIMI-REPLACEMENT-WITH-QWEN scaffold (2026-05-28). This is a low-stakes drift but the count is verifiable and wrong. **Note**: I'm classifying this as "fresh" because the row's load-bearing intent (showing breadth of engine support) is intact, but flagging it here for orchestrator awareness.
- **CLAUDE.md `harness coord` subcommands list**: verified exact match. CLAUDE.md says "12 subcommands" and lists 13 names (`plan`, `plan-from-description`, `run`, `work`, `retry`, `rerun-failed`, `integrate`, `replan`, `status`, `watch`, `list`, `cancel`, `cleanup`). `harness coord --help` returns exactly these 13 names. The "12 subcommands" number in the row label is off-by-one (should be 13) but the actual list is accurate. PARTIAL — minor count drift.
- **CLAUDE.md "Operator authority + escalation" section**: confirmed accurate. L5-only escalation matches `src/harness/errors.py` taxonomy.
- **CLAUDE.md "Memory entries this session inherits" names**: all 6 entries verified present in `~/.claude/projects/D--xaxiu-harness-standalone/memory/` (though the directory PATH is wrong per Finding 4 above).
- **CLAUDE.md "Dev loop" section**: confirmed. `coord/dev_loop/state.json` exists, the 5 supervisors (`creativity.md`, `developing.md`, `testing.md`, `integrating.md`, `process_improvement.md`) exist in `coord/dev_loop/supervisors/`, `manager.md` exists, `dispatch-rules.md` exists, and `bin/register-dev-loop-task.ps1` exists.
- **Memory entry `reference_xaxiu_swarm_concurrency_calibration` claim about `DEFAULT_ENGINE_SLOTS`**: verified. `src/harness/operator/modes.py` exists and per `MEMORY.md` index "Baked into `src/harness/operator/modes.py::DEFAULT_ENGINE_SLOTS`".

---

## Needs-clarification / sampling caveats

- **`reference_engine_context_limits.md`** ("DeepSeek v4 is 1M tokens (not 262k as harness docs say)"): I did not verify whether current harness docs still say 262k or have been updated; if docs now match the 1M figure, the memory entry's "correction" language could be archived. Suggest sampling `docs/AGENT_REFERENCE.md` + spec files for "262k" / "262144" references in a follow-up.
- **`feedback_engine_routing_2026_05_11.md`** ("Kimi-first for non-V-file tasks (subscription cost)"): the underlying premise — Kimi is the subscription-cost engine to fill — is operator-contradicted by W14-KIMI-AUTH-RESTORE (Kimi terminated 2026-05-25). Memory entry pre-dates termination and now contradicts the live engine pool. Operator may prefer to keep it as historical record or archive. Not actionable here.
- **`feedback_engine_dispatch_path.md`** ("Default dispatch tool is xaxiu-swarm"): this is the same scope as Finding 2 (CLAUDE.md engine routing) — pre-Pattern-B framing. Verifying / archiving is operator-judgment territory.
- **Spot-check coverage**: I checked ~8 memory entries deeply + skimmed all 57 file names in MEMORY.md index. The orchestrator should be aware that a more exhaustive memory audit would likely surface additional stale entries (especially the 2026-05-11 to 2026-05-13 cluster from the warehouse era, several of which name files/paths that may no longer be load-bearing for harness work).

## Confidence + caveats

- **High confidence**: Findings 1-5 (version, engine families, memory count, wrong memory path, error-taxonomy entry). All three have hard file/grep evidence.
- **Medium confidence**: Findings 6-7 (the partial-stale ones). The W14-LOCAL-LLAMA framing is more of a strategic-coherence question than a stale-fact question.
- **Sampling gap**: I did not exhaustively audit every memory entry — only spot-checked ~10 entries that named specific files/functions and the 6 entries CLAUDE.md explicitly cites. A more aggressive memory audit (Agent B/C scope?) would likely find ~3-5 more stale entries in the 2026-05-09 to 2026-05-20 cluster.
- **Did not verify**: Test counts mentioned in STATUS.csv rows (e.g. "3149 passed" in W14-KEY-ROTATION-PLAYBOOK) — these go stale on every commit and CLAUDE.md already has the P6 audit fix acknowledging this.
- **Most actionable single fix**: Finding 4 (wrong memory path in CLAUDE.md) — this one actively misroutes any agent that follows the instruction. Findings 1, 2, 3 are doc-hygiene; Finding 4 is functional misdirection.
