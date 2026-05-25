# Engine cost-vs-usage matrix (best bang for buck by workload type)

**Date**: 2026-05-25 evening
**Trigger**: Operator pushback on the GLM single-engine recommendation. *"I want the best bang for my buck, kimi 2.6 comparable but low cost because to be frank, you need to categorize by cost and usage type."*
**Verdict**: Qwen 3.6 Plus PAYG replaces GLM as the 3rd-engine pick. Categorized matrix below.

---

## Cost landscape — May 2026 prices, $/M tokens (input/output avg)

Sorted cheapest first:

| Engine | $/M avg | SWE-Bench Verified | Open weights? | Lineage |
|---|---|---|---|---|
| Qwen3 Turbo | **$0.09** | (smaller / older — not coding-tier) | Yes | Alibaba |
| Doubao Seed | $0.07-0.15 | (basic) | Yes | ByteDance |
| Gemini 2.5 Flash | $0.19 | mid | No | Google |
| **DeepSeek V4 Flash** (pool) | **$0.21** | strong all-rounder cheap-tier | Yes | DeepSeek |
| Anthropic Haiku 4.5 | $0.75 | mid-strong | No | Anthropic |
| **Qwen 3.6 Plus** | **$0.97** | ~78-80% (estimated open-tier ceiling) | **Yes (Apache 2.0)** | Alibaba |
| **Kimi K2.6 PAYG** | $1.00-1.80 | **80.2%** | Yes (Modified MIT) | Moonshot |
| GLM-5.1 PAYG | $1.30 | 77.8% | Yes (MIT) | Zhipu |
| DeepSeek V4 Pro | $1.38 | strong reasoning | Yes | DeepSeek |
| Qwen 3.6 Max-Preview | ~$1.20-$2 (Max-Preview pricing not finalized) | **#1 SWE-Bench Pro** | API-only | Alibaba |
| Gemini 2.5 Pro | $5.60 | long-context strong | No | Google |
| Anthropic Sonnet 4.5 | $9 | premium | No | Anthropic |
| GPT-5.5 | ~$10 | 88.7% Verified, 82.7% Terminal-Bench | No | OpenAI |
| Claude Opus 4.7 | $45 | **87.6%** (top open or closed) | No | Anthropic |

**Key reading of the table**: Qwen 3.6 Plus is the cheapest open-weight option in the Kimi K2.6 capability tier. ~46% cheaper than K2.6 PAYG at comparable SWE-bench. **This is the literal "Kimi-comparable, lower cost" answer.**

---

## Usage type → best $/quality engine

The harness's real workloads bucket into 5 distinct tiers. Each tier has a different "best value" engine — using one engine for everything wastes either money (using Opus for status checks) or quality (using Turbo for strategic synthesis).

| # | Usage type | Monthly volume (estimated from audit data) | Tier needed | Best $/quality pick | Why |
|---|---|---|---|---|---|
| 1 | **Strategic ship-gate panels** (v1.0.0 release-gate, master-plan synthesis, post-mortem audits) | ~200-500k tokens | Premium reasoning | **Claude Opus 4.7 via Claude Code subscription** ($100/mo flat) | API path is $45/M = $9-22/mo per panel run; subscription amortizes across unlimited interactive + panel use |
| 2 | **Multi-engine validation panels** (regular cross-checks, 3 voices for diversity) | ~300k-1M tokens × N engines | Mid-premium, **diverse lineages required** | DeepSeek V4 Pro + Qwen 3.6 Plus + MiMo v2.5-pro | Three distinct training lineages (DeepSeek / Alibaba / Xiaomi) give genuinely different perspectives; all coding-strong; total cost ~$1-3/panel |
| 3 | **Code generation packets** (FIND/REPLACE blocks, novel features, multi-file refactor) | ~200k-1M tokens | SWE-bench-strong, single engine | **Qwen 3.6 Plus** ($0.97/M) | Top SWE-Bench Verified at this price tier; Apache-2.0 means zero termination risk; cheaper than Kimi K2.6 for same quality |
| 4 | **Observer audits** (background QA, 71 events/mo in current data) | ~200-500k tokens | Mid-tier, cheap | **DeepSeek V4 Flash** ($0.21/M) | Already in pool; vast overcapacity at $30 budget; engine quality is overserving this tier |
| 5 | **Bulk batch / simple Q&A** (status checks, simple dispatches, hot-loop polling) | 500k-2M tokens | Cheapest workable | **DeepSeek V4 Flash** ($0.21) or **Qwen3 Turbo** ($0.09) | Use the cheapest engine that produces parseable output; Doubao at $0.07 if Chinese-mainland registration friction is acceptable |

**Key insight**: only tiers #1 and #2 need premium engines. Tiers #3-5 can be served by mid-or-cheap-tier engines, and forcing premium-tier engines onto them is the classic over-spec'd-tool mistake. The harness's job is to route the right tier to the right engine — not to send everything to the most-expensive option "to be safe".

---

## Revised $195/mo budget allocation

Replacing GLM with Qwen 3.6 Plus:

| Engine | $/mo | Role | Capacity at $/M | Δ vs prior GLM pick |
|---|---|---|---|---|
| Claude Code (direct, NOT via harness) | $100 | Tier 1 strategic reasoning + daily IDE | Opus 4.7 via Max base tier | unchanged |
| MiMo Token Plan Standard | $15 | Tier 2 cross-engine voice (Xiaomi lineage) | ~200M credits/mo | unchanged |
| DeepSeek V4 Flash PAYG | $30 | Tier 4 + Tier 5 (observer + bulk) + cheap-tier code | **~140M tokens/mo** | unchanged |
| **Qwen 3.6 Plus PAYG** | $50 | **Tier 2 + Tier 3** (cross-engine voice + code generation) | **~51M tokens/mo** | +34% capacity vs GLM at same price |

Across the four engines + Claude Code direct, every tier in the usage table is now served at a cost-effective price point:

- Tier 1 → Claude Code direct
- Tier 2 → MiMo + Qwen + (DeepSeek V4 Pro spot-buy if needed, ~$1-2 per panel)
- Tier 3 → Qwen 3.6 Plus
- Tier 4 → DeepSeek V4 Flash
- Tier 5 → DeepSeek V4 Flash (or Qwen3 Turbo via the same DashScope account for ultra-cheap)

**Total monthly capacity**: ~340M tokens across the 4 paid engines + unlimited Opus via Claude Code subscription. That's ~4x the operator's audit-measured workload (~80M tokens including CI fixtures × ~30M real). Comfortable headroom.

---

## Alternative split (if maximizing engine count over depth)

If the operator wants 5 lineages instead of 4, replace the single $50 Qwen slot with a split:

| Engine | $/mo | Capacity | Role |
|---|---|---|---|
| Qwen 3.6 Plus PAYG | $30 | ~31M tokens | Tier 2/3 Alibaba lineage |
| Gemini 2.5 Flash PAYG | $10 | ~53M tokens | Tier 4 Google lineage diversity hedge |
| Qwen3 Turbo or Doubao PAYG | $10 | ~70-110M tokens | Tier 5 ultra-cheap bulk |

**Trade-offs**: more lineage diversity (4 → 5), but Qwen capacity drops 39% (51M → 31M). Recommended only if multi-engine panels become weekly and want Google's voice in the pool. Otherwise stick with the focused $50-on-Qwen allocation.

---

## What changes in the master plan

The row **W14-KIMI-REPLACEMENT-WITH-GLM** is renamed and repointed:

**Before**: `W14-KIMI-REPLACEMENT-WITH-GLM` — drop Kimi, add GLM-5.1 adapter ($1.30/M, ~38M tokens at $50)

**After**: `W14-KIMI-REPLACEMENT-WITH-QWEN` — drop Kimi, add Qwen 3.6 Plus adapter ($0.97/M, ~51M tokens at $50)

Implementation cost is structurally identical (both are OpenAI-compatible chat-completions schemas, both use the existing `StreamingTransport` base). The change is just:
- Endpoint: `dashscope.aliyuncs.com/compatible-mode/v1` (Qwen) instead of `open.bigmodel.cn/api/paas/v4` (GLM)
- Env var: `DASHSCOPE_API_KEY` instead of `GLM_API_KEY`
- Default model: `qwen3.6-plus` instead of `glm-5.1`

GLM is NOT removed from the candidate pool — operator could add it later as a 5th engine (the Anthropic-API-compat is genuinely unique). But Qwen 3.6 Plus gets the $50 slot first because of the better $/quality ratio.

---

## Sources

- [Qwen 3.6 Max-Preview vs Plus vs Kimi K2.6 — Lushbinary](https://lushbinary.com/blog/qwen-3-6-max-preview-vs-plus-vs-kimi-k2-6-comparison/)
- [Kimi K2.6 vs Qwen 3.6 vs Opus 4.7 vs GPT-5.5 (BuildFastWithAI)](https://www.buildfastwithai.com/blogs/kimi-k2-6-vs-qwen-3-6-vs-claude-opus-4-7-vs-gpt-5-5-2026)
- [Kimi K2.6 vs GLM 5.1 vs Qwen 3.6 Plus vs MiniMax M2.7 (Atlas Cloud)](https://www.atlascloud.ai/blog/guides/kimi-k2-6-vs-glm-5-1-vs-qwen-3-6-plus-vs-minimax-m2-7-coding-2026)
- [Late-April 2026 Chinese LLM Stack (dev.to)](https://dev.to/bean_bean/the-late-april-2026-chinese-llm-stack-qwen-36-deepseek-v4plus-kimi-k26-minimax-m27-glm-51-2bif)
- [Cheapest LLM API for Startups 2026 (TokenMix)](https://tokenmix.ai/blog/cheapest-llm-api-for-startups)
- [LLM Leaderboard 2026 (llm-stats)](https://llm-stats.com/)
- [Best LLMs May 2026 (Future AGI)](https://futureagi.com/blog/best-llms-may-2026/)
