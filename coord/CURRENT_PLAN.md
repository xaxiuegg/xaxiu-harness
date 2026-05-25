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

### Operator engine-budget commitment (2026-05-25 evening)

After Kimi termination + strategic eval, operator committed to a $195/mo split:
- **Claude Code (direct, not via harness): $100/mo** — Max base tier, daily interactive coding
- **MiMo Token Plan Standard: $15/mo** — through harness, multi-engine panel + dispatch
- **DeepSeek PAYG: $30/mo** — through harness, primary dispatch
- **3rd engine: $50/mo** — through harness, diversification slot
  - **Recommended pick: GLM-5.1 PAYG** ($0.60/$2.00 per M tokens, ~38M tokens/mo at $50, open-weight MIT, OpenAI+Anthropic API compat, 77.8% SWE-bench Verified)
  - Alternative: Gemini Pro PAYG (~9M tokens/mo, Western-provider diversity hedge)

This commitment **reverses the previous "pause + observe" recommendation** ([EVALUATION.md](reviews/post-kimi-strategic-eval/EVALUATION.md)) — the harness IS now load-bearing because it's the thing that coordinates the multi-engine pool. Resume W14 work.

### Immediate — Engine-budget-enablement (~8-10h)

| Row | Effort | Why |
|---|---|---|
| **W14-KIMI-REPLACEMENT-WITH-GLM** (from master plan, repointed at PAYG endpoint NOT Coding Plan) | M (~5h) | The $50/mo 3rd-engine slot. Unblocks the operator's budget split. |
| **W14-BUDGET-METER-PER-ENGINE** (new) | M (~3-4h) | Per-engine monthly caps ($30 deepseek / $15 mimo / $50 glm) + 80%-spend observer flag + dispatch-time enforcement (refuse when over cap unless explicit override). Extends existing `harness budget set-cap`. |
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

**Acquire `GLM_API_KEY` from [open.bigmodel.cn](https://open.bigmodel.cn) (PAYG, NOT Coding Plan), then ship W14-KIMI-REPLACEMENT-WITH-GLM.** This is the unblocking move for the $195/mo engine-budget split — the harness can't enforce the 3rd-engine slot until GLM is wired.

In parallel, decide the MiMo plan tier (Standard at $14.08/mo fits the $15 budget) and confirm whether to acquire a `sk-` PAYG MiMo key as fallback insurance (no cost until used).

After GLM ships: W14-BUDGET-METER-PER-ENGINE so the harness can actually enforce the $30/$15/$50 caps + alert at 80% spend.

Kimi (`W14-KIMI-AUTH-RESTORE`) is no longer in the action chain — replaced by GLM. The Kimi adapter stays in the codebase (TOS-compliant after W14-MIMO-TOS-COMPLIANCE) for any operator who later acquires a legitimate Moonshot-approved client license.

---

## How to update this file

This file is hand-maintained. Edit it directly when:

- A panel runs and produces a new forward plan (replace the "What's next" section)
- A row in the plan ships (move it from "What's next" to "Shipped this week" or delete if older than a week)
- A new strategic constraint is added (e.g., new operator directive)

`coord/STATUS.csv` is the per-row tracker; this file is the strategic narrative. Keep them consistent — if a row is in STATUS.csv as `shipped` but this file still shows it as todo, this file is stale.

For programmatic access, use `harness plan show` (renders this file to stdout) or `harness plan show --format json` (parsed sections).
