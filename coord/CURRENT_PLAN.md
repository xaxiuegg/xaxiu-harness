# Current strategic plan — xaxiu-harness

**Source**: 15-engine Round 2 strategic panel ([FINAL_VERDICT](reviews/strategic-planning-panel15-final-verdict/FINAL_VERDICT.md)) + Friday v1.0.0 release-gate ([FINAL_VERDICT](reviews/v1-release-gate/FINAL_VERDICT.md), 2/3 APPROVE).
**Last updated**: 2026-05-25 (v1.0.0 tagged)

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

### Immediate — Engine-budget-enablement (~8-10h)

| Row | Effort | Why |
|---|---|---|
| **W14-KIMI-REPLACEMENT-WITH-QWEN** (renamed from -WITH-GLM) | M (~5h) | The $50/mo 3rd-engine slot. Qwen 3.6 Plus PAYG via DashScope endpoint (NOT Alibaba Coding Plan subscription). Structurally identical to a GLM adapter — both use the existing `StreamingTransport` base + OpenAI-compat chat-completions schema. |
| **W14-BUDGET-METER-PER-ENGINE** | M (~3-4h) | Per-engine monthly caps ($30 deepseek / $15 mimo / $50 qwen) + 80%-spend observer flag + dispatch-time enforcement. Extends existing `harness budget set-cap`. |
| W14-DISPATCH-HEALTH-AWARE-FALLBACK | M (4-5h) | Saves real money now that the operator is paying real money — skip dead engines, don't waste tokens on terminated Kimi / no-key Anthropic-Gemini-direct |

### Then — Week 2 Operations Hardening (~6-8h)

| Row | Effort | Why |
|---|---|---|
| W14-AUDIT-CHAIN-HMAC | M (3-4h) | Forensic integrity, security panel's #1 pick (0.90/0.95 confidence) |
| W14-BACKUP-MANAGER (folds W13-BACKUP-SECRETS-REDACT + W13-BACKUP-INTEGRITY + W13-BACKUP-DRY-RUN + W14-BACKUP-PREFLIGHT-SCAN) | L (5-6h) | Multi-lens convergent pick — backup tar may contain API keys |
| W14-PARALLEL-DISPATCH-RETRY-FIX | S (2h) | Production-evidenced bug (MiMo race in panels) |
| W14-KEY-ROTATION-PLAYBOOK | S (2h) | Direct Kimi-termination response — `harness env rotate <engine>` |
| Auto-default guardrail CI framework | M (4-5h) | Every new auto-default must ship with a "what would happen if this were wrong" test |

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

---

## Single most important action (live)

**Acquire `DASHSCOPE_API_KEY` from [dashscope.aliyun.com](https://dashscope.aliyun.com) (PAYG, NOT Alibaba Coding Plan subscription), then ship W14-KIMI-REPLACEMENT-WITH-QWEN.** This is the unblocking move for the $195/mo engine-budget split — the harness can't enforce the 3rd-engine slot until Qwen is wired.

In parallel, decide the MiMo plan tier (Standard at $14.08/mo fits the $15 budget) and confirm whether to acquire a `sk-` PAYG MiMo key as fallback insurance (no cost until used).

After Qwen ships: W14-BUDGET-METER-PER-ENGINE so the harness can actually enforce the $30/$15/$50 caps + alert at 80% spend.

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
