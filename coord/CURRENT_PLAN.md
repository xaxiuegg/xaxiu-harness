# Current strategic plan — xaxiu-harness

**Source**: 15-engine Round 2 strategic panel ([FINAL_VERDICT](reviews/strategic-planning-panel15-final-verdict/FINAL_VERDICT.md)) + Friday v1.0.0 release-gate ([FINAL_VERDICT](reviews/v1-release-gate/FINAL_VERDICT.md), 2/3 APPROVE).
**Last updated**: 2026-05-28 (agentic-operator roadmap shipped AM + engine-budget triad shipped PM after audit-first reconciliation; live action chain shifts to Week 2 Operations Hardening starting with `W14-AUDIT-CHAIN-HMAC`).

> **For agents**: this file is the active "what are we trying to ship right now" document. `coord/STATUS.csv` is the per-row task tracker; this file is the strategic narrative that explains why those rows exist. When the rows here disagree with `harness today`, trust `harness today` for current state and update this file.

---

## North star

**Horizon C internal tool, NOT commercial product** (operator directive 2026-05-25).
Solo internal use. Optimize for visible/overridable/auditable behavior.
Drop everything multi-user / plugin-marketplace / VPS-hosted / best-of-N-cost-multiplier.

---

## Where we are right now (as of 2026-05-25)

**Tag**: **`v1.0.0`** (tagged at commit `d30bace` after 2/3 APPROVE on the Friday release-gate panel — DeepSeek + MiMo APPROVE, Kimi auth-out)
**Tests**: 2377 passed, 6 skipped (slow-marked install-verify), 0 failed
**Budget**: well under $5/session cap

**Week 1 complete**: 11 W13 rows + v1.0.0 tagged at `d30bace` on 2026-05-25. Per-row detail in [coord/releases/v1.0.0.md](releases/v1.0.0.md). Audit infra now routes W12+ tasks to STATUS.csv via [W13-AUDIT-INFRA-W12-PLUS].

**2026-05-28 AM — agentic-operator roadmap shipped + CAPPED** (15 commits, v0.5.5 → v0.6.3). A separate roadmap from the engine-budget triad.  Tracked in memory at [project_agentic_operator_roadmap_2026_05_28](../../C:/Users/xaxiu/.claude/projects/D--xaxiu-harness-standalone/memory/project_agentic_operator_roadmap_2026_05_28.md).  Shipped: `harness proxy --upstream` (5 upstreams incl. TOS-compliant Claude-Code-subprocess), `harness engines describe` + `compatibility-matrix`, `harness introspect`, `harness ask --rerun --escalate {audit|panel}`, `harness ask-history` + `ask-show`, `harness self-update`, snippet auto-version-stamp + staleness detection, `harness ask --audit --auditors N` quorum, `harness ask --research <path>`, setup-wizard step 6 (snippet install).  Empirically validated by 7 fresh-session sub-agent tests (4 positive scenarios at 9/10, 3 Goodhart-aware tests at 8-9/10 with one bug surfaced + fixed: ask-history hyphen anti-trap).  Score ceiling reached for solo internal use per the Horizon C plan; **further iteration on this surface is diminishing-returns territory.**

⚠ **Track-swap audit (the why-this-section-exists note)**: the morning's 15 commits shipped from the agentic-operator roadmap, **not from this plan's stated "What's next" engine-budget triad**.  The agentic-operator track had visible friction (transcript-grounded hiccups) + fast feedback loops + shippable surface; the engine-budget track was operator-blocked on DASHSCOPE_API_KEY acquisition.  Under full dev authority the easier track pulled all the gravity.  See new anti-pattern #8 below.

**2026-05-28 PM — engine-budget triad ALSO shipped** (4 commits, after the audit caught the track-swap). Audit-first reconciliation found 2 of 3 rows substantially shipped weeks back under different row IDs; today's commits closed the remaining gaps.  See [feedback_grep_before_declare_greenfield_2026_05_28](../../C:/Users/xaxiu/.claude/projects/D--xaxiu-harness-standalone/memory/feedback_grep_before_declare_greenfield_2026_05_28.md) for the lesson on why strategic-panel synthesis under-detects already-shipped capability.

| Triad row | Today's commit | What completed today |
|---|---|---|
| `W14-KIMI-REPLACEMENT-WITH-QWEN-SCAFFOLD` | `522df36` | `QwenConcrete` adapter + factory registration + budget pricing + 12 tests.  Live validation gated on operator acquiring `DASHSCOPE_API_KEY`. |
| `W14-BUDGET-METER-PER-ENGINE-OBSERVER-HOOK` | `b646b3c` | Meter + caps + dispatch-skip already shipped weeks back.  Today: cheap local periodic check + `harness observer budget-watch` verb + MED/HIGH flag emit at 80%/100% thresholds + dedup via signature marker. |
| `W14-DISPATCH-HEALTH-AWARE-FALLBACK-IN-ASK-FLOW` | `bcb2ae6` | `routing.py::filter_eligible_engines` already shipped + dispatcher already used it.  Today: `recommend_healthy()` wrapper + `harness ask` routed-default + `_pick_auditor_engines` walker both call it now. |

Plan reconciliation itself shipped as `b503fcb` (`W14-PLAN-RECONCILE-2026-05-28`).  Engine-budget triad is now **done**; the live action chain shifts to Week 2 Operations Hardening below.

---

## What's next

### Operator engine-budget commitment (2026-05-25 evening, **REVISED**)

After Kimi termination + strategic eval + cost-vs-usage matrix work, operator committed to a $195/mo split:
- **Claude Code (direct, not via harness): $100/mo** — Max base tier, daily interactive coding + Tier-1 strategic reasoning via Opus 4.7
- **MiMo Token Plan Standard: $15/mo** — through harness, cross-engine voice for panels (Xiaomi lineage)
- **DeepSeek V4 Flash PAYG: $30/mo** — through harness, observer + bulk + cheap-tier code (~140M tokens/mo at $0.21/M)
- **Qwen 3.6 Plus PAYG: $50/mo** — through harness, premium code generation + cross-engine voice (Alibaba lineage). **~51M tokens/mo at $0.97/M** — Kimi-K2.6-comparable quality at ~46% lower cost. Apache-2.0 open-weight, zero termination risk.

**Why Qwen 3.6 Plus over GLM-5.1**: same SWE-bench tier, but $0.97/M vs $1.30/M = **+34% more capacity at the same $50** (~51M tokens vs ~38M). Full cost-vs-usage matrix in [reviews/engine-cost-usage-matrix/MATRIX.md](reviews/engine-cost-usage-matrix/MATRIX.md).

This commitment **reverses the previous "pause + observe" recommendation** ([EVALUATION.md](reviews/post-kimi-strategic-eval/EVALUATION.md)) — the harness IS now load-bearing because it's the thing that coordinates the multi-engine pool. Resume W14 work.

### Usage-tier → engine routing (the harness's actual job)

| Tier | Workload | Volume/mo | Engine |
|---|---|---|---|
| 1 | Strategic ship-gate panels | ~200-500k tokens | Claude Opus 4.7 via Claude Code direct |
| 2 | Multi-engine validation panels (3 voices) | ~300k-1M tokens × N | DeepSeek V4 Pro + Qwen 3.6 Plus + MiMo v2.5-pro |
| 3 | Code generation packets | ~200k-1M tokens | Qwen 3.6 Plus (top SWE-bench at this price tier) |
| 4 | Observer audits | ~200-500k tokens | DeepSeek V4 Flash |
| 5 | Bulk batch / simple Q&A | 500k-2M tokens | DeepSeek V4 Flash (or Qwen3 Turbo via DashScope) |

### Week 2 Operations Hardening (~6-8h, audit-first reconciled)

| Row | Effort | Status & Why |
|---|---|---|
| W14-AUDIT-CHAIN-HMAC | M (3-4h) | **Truly zero** (grep'd `hmac\|HMAC\|audit_chain` — no matches in `src/harness/`).  Security panel's #1 pick (0.90/0.95 confidence).  The actual greenfield work. |
| W13-BACKUP-ENCRYPTION (renamed from W14-BACKUP-MANAGER) | S (~3-4h) | **Was overcounted.**  `src/harness/backup.py` (347 LOC, create/list/prune/restore) shipped 2026-05-25 as the W13 backup work (see STATUS.csv for the shipped row).  No encryption code present (grep'd `encrypt\|cipher`).  Remaining work: AES-256 of the .tar.gz body, key derivation from DPAPI / system keyring, manifest stays cleartext.  Same `harness backup` surface, transparently encrypted. |
| W14-KEY-ROTATION-PLAYBOOK + `harness env rotate <engine>` verb | S-M (2-3h) | **Truly zero for the verb.**  `harness env --help` confirms only `--show-set` flag; no rotate.  doctor/preflight touch the concept but no playbook doc.  Greenfield work: write the verb + a `docs/KEY_ROTATION_PLAYBOOK.md`. |
| Auto-default guardrail CI framework | M (4-5h) | **Truly zero** (grep'd `auto.default.guardrail\|guardrail.*ci` — no matches).  Greenfield work. |

### Week 3 — Polish + Nice-to-haves (~4-6h, optional)

| Row | Effort | Source |
|---|---|---|
| Schema versioning (when first data-structure change happens) | S | M3 + DeepSeek amendment 3 |
| `harness commands --did-you-mean` | S (~2h) | DeepSeek amendment 4 |
| Hallucination test harness | S (~2h) | DeepSeek amendment 6 |
| Tier 2 shifts (auto-retry, cost-cap pre-check, L5-inline in DispatchResult) — pick 1-2 | S each | DeepSeek amendment 5 |

### Deferred backlog (NOT this month)

- **W14-LOCAL-LLAMA-FALLBACK** — keep as outage insurance row; ship only if/when cloud-engine outage actually happens (DeepSeek amendment 1)
- Everything in the prior DROP list — W15 plugin architecture, W14-BEST-OF-N, W14-MISTRAL, W16 multi-user, W17 VPS-hosted-observer, W13-PLUGIN-SANDBOX-PLAN, W13-BACKUP-ENCRYPTION-FULL

---

## Confirmed anti-patterns (don't do these)

1. Don't ship auto-defaults before `W13-AUDIT-JSONL` lands. → ✅ already done; we have the ledger.
2. Don't add new CLI verbs without explicit ROI. → Defer to `harness capabilities` introspection where possible.
3. Don't auto-close observer flags (auto-escalate instead).
4. Don't merge `dispatch` + `review` (different intents, different return types).
5. Don't build plugin architecture for a solo internal tool.
6. Don't trust untested install paths. → ✅ W13-INSTALL-VERIFY now gates every PR.
7. Don't ship features that hide what the harness is doing — the visible/overridable/auditable trio is mandatory.
8. **Don't substitute easier tracks for the plan's stated Immediate row without surfacing the substitution.** (Added 2026-05-28 after a 15-commit day shipped agentic-operator roadmap polish while the engine-budget triad — the plan's stated "single most important action (live)" — sat at 0%.)  Under full dev authority, tracks with visible friction + fast feedback + shippable surface pull all the gravity; the harder operator-unblock-required track is what the strategic plan calls load-bearing.  When CURRENT_PLAN.md's Immediate row is operator-blocked (waiting on a key, a sign-up, or a decision), either (a) ship the *prerequisite-free portions* of that row (e.g. scaffold the adapter, build the budget meter that the blocked adapter will plug into) OR (b) explicitly surface the substitution in STATUS.csv with a row titled `STRATEGIC-DETOUR: <reason>` so the next planner sees the diversion.  See [feedback_velocity_vs_mandate_2026_05_28].

---

## Single most important action (live)

**Start `W14-AUDIT-CHAIN-HMAC`** — the security panel's #1 pick (0.90/0.95 confidence) and the only truly-zero Week 2 Operations Hardening row with no operator dependency. Greenfield M (3-4h): SHA-256 chained-hash of audit JSONL entries with HMAC keyed off DPAPI-stored secret. Closes the audit-integrity gap that lets a process with write access tamper with the ledger post-hoc.

**In parallel (operator-blocked)**: acquire `DASHSCOPE_API_KEY` from [dashscope.aliyun.com](https://dashscope.aliyun.com) (PAYG, NOT Alibaba Coding Plan subscription) to unblock `W14-KIMI-REPLACEMENT-WITH-QWEN` live validation.  The `QwenConcrete` scaffold + tests are already in `522df36`; only the live smoke test gates on the key.

In parallel (decision-blocked): decide the MiMo plan tier (Standard at $14.08/mo fits the $15 budget) and confirm whether to acquire a `sk-` PAYG MiMo key as fallback insurance (no cost until used).

Kimi (`W14-KIMI-AUTH-RESTORE`) is no longer in the action chain — replaced by Qwen 3.6 Plus. The Kimi adapter stays in the codebase (TOS-compliant after W14-MIMO-TOS-COMPLIANCE) for any operator who later acquires a legitimate Moonshot-approved client license.

GLM-5.1 is NOT removed from the candidate pool — it could be added later as a 5th engine if the Anthropic-API-compat property becomes useful. Qwen 3.6 Plus takes the $50 slot first because of the better $/quality ratio (51M tokens/mo vs GLM's 38M).

---

## How to update this file

This file is hand-maintained. Edit it directly when:

- A panel runs and produces a new forward plan (replace the "What's next" section)
- A row in the plan ships (move it from "What's next" to "Shipped this week" or delete if older than a week)
- A new strategic constraint is added (e.g., new operator directive)

`coord/STATUS.csv` is the per-row tracker; this file is the strategic narrative. Keep them consistent — if a row is in STATUS.csv as `shipped` but this file still shows it as todo, this file is stale.

For programmatic access, use `harness plan show` (renders this file to stdout) or `harness plan show --format json` (parsed sections).
