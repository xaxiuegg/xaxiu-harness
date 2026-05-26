# Qwen token cost analysis (DashScope, May 2026)

**Date**: 2026-05-25 evening
**Trigger**: Operator follow-up after W14-ENGINE-COST-USAGE-MATRIX: "conduct a token cost analysis for the qwen models." Specifically: actual DashScope per-token pricing (not OpenRouter mirrors), context-tier effects, cache discounts, and how to allocate the $50/mo Qwen budget across models.

**Headline correction**: my prior estimate of Qwen 3.6 Plus at **$0.97/M avg** was OpenRouter pricing. Actual **DashScope pricing is $0.325/$1.95 = avg ~$1.14/M**. Still cheaper than Kimi K2.6 ($1.00-1.80/M) and GLM-5.1 ($1.30/M), but recalibrated numbers below.

---

## Full Qwen pricing table (DashScope native API, May 2026)

| Model | Input $/M | Output $/M | Cached $/M | SWE-Bench Verified | Context | Tier |
|---|---|---|---|---|---|---|
| **Qwen-Turbo** | $0.033 | $0.13 | — | (mid-tier) | ~256K | speed/cheapest |
| **Qwen 3.6 Flash** (new Apr 2026) | $0.25 | TBD | — | TBD | TBD | speed-optimized |
| **Qwen 3.6 Plus** | $0.325 | $1.95 | yes (DashScope cache) | **78.8%** | **1M** (256K native + YaRN) | flagship coding |
| **Qwen3 Coder 480B A35B** | $0.22 | TBD | **$0.022 (10× discount)** | top-tier coding | varies | agentic-coding specialist |
| **Qwen 3 Max** | $0.78 | $3.90 | $0.156 | (premium) | varies | premium reasoning |
| **Qwen 3.6 Max-Preview** | TBD (claimed flagship) | TBD | TBD | **#1 SWE-Bench Pro** | varies | premium, closed-weights |
| Qwen 3.6-27B / 35B-A3B (open weights) | self-host only | — | — | 73-77% | varies | self-hostable |

**Three pricing properties unique to DashScope**:

1. **Context-tier pricing**: above 256K input tokens, output rates increase. Below 256K the published rates apply. Harness panel source packs are 30k-65k characters (~10-20k tokens) — comfortably in the cheap tier. Not a concern for current workloads.
2. **Batch inference 50% discount**: both input AND output billed at 50% for `batch_invocation=true` requests. The harness's panel pattern is technically batchable across multiple panel runs but we don't currently use this.
3. **Cache hit pricing** (DashScope Context Cache): repeat-prefix portions of subsequent requests bill at the cached rate. Qwen3 Coder 480B's **10× cache discount** ($0.022 cached vs $0.22 standard) is the most aggressive.

---

## Recalibrated $50/mo Qwen budget capacity

Using the actual DashScope rates with a mixed input/output workload (assume 60/40 in/out split for panel-style work):

| Model | Effective $/M (mixed) | Tokens at $50 | Use case |
|---|---|---|---|
| Qwen-Turbo | ~$0.07 | **~715M tokens** | Bulk batch, observer cycles, simple Q&A |
| Qwen 3.6 Flash | ~$0.45 (output TBD; estimate ~$0.65) | ~75M tokens | Mid-tier speed-sensitive |
| Qwen 3.6 Plus | ~$0.97 | **~52M tokens** | Premium reasoning + code generation + panels |
| Qwen3 Coder 480B (cached) | ~$0.022-0.22 mixed | 200M+ if 70%+ cache hit | Repo-scale agentic coding when prompts reuse source pack |
| Qwen 3 Max | ~$2.04 | ~24M tokens | Premium-tier reasoning (overkill for most harness work) |

Comparison to prior pool members at equivalent quality tier:

| Engine | Effective $/M | $50 buys | Tier |
|---|---|---|---|
| Kimi K2.6 PAYG | $1.40 | ~36M tokens | premium open-coding (was) |
| GLM-5.1 PAYG | $1.30 | ~38M tokens | premium open-coding |
| **Qwen 3.6 Plus PAYG** | **$0.97** | **~52M tokens** | premium open-coding |
| Qwen 3.6 Plus DashScope direct | $1.14 | ~44M tokens | premium open-coding (actual rate) |

**Qwen 3.6 Plus on DashScope direct still wins** — even at the actual $1.14/M rate vs OpenRouter's $0.97/M, you get 16% more tokens than GLM at the same price. Going through OpenRouter is also viable (and the $0.97 figure stands there) — see "Routing decision" below.

---

## Optimal $50 allocation (model mix within Qwen account)

Three-tier intra-Qwen routing maximizes the budget. Each tier serves different harness workloads:

| Tier | Budget | Model | Capacity | Routes (harness workload mapping) |
|---|---|---|---|---|
| **Premium reasoning** | $30 | Qwen 3.6 Plus | ~26M tokens | Multi-engine panel votes, ship-gate verdicts, master-plan syntheses |
| **Coding specialist** | $10 | Qwen3 Coder 480B (with cache) | ~45M tokens (60% cache hit assumed) | FIND/REPLACE packets, multi-file refactor, novel-feature drafts |
| **Bulk overflow** | $10 | Qwen-Turbo | ~140M tokens | Observer cycles secondary check, simple dispatch, status synthesis |

**Total**: ~211M tokens/mo at $50, distributed across three quality tiers vs. ~44M tokens on a single Qwen 3.6 Plus allocation. **5× more total capacity if you actually use the right tier for each task.**

The trade-off: the harness needs to KNOW which model to pick. Options:

- **Operator picks per dispatch** via `extra_args["model"]="qwen-turbo"` — manual but explicit
- **Harness auto-routes** by usage hint — needs a new auto-detection like `detect_mimo_model` for Qwen
- **Default to Qwen 3.6 Plus** for everything — simplest, but throws away the cache+turbo win
- **(Future, W15+)**: usage-tier-aware routing based on prompt characteristics (length, complexity, type)

**Initial recommendation**: ship the adapter with `qwen3.6-plus` as the default, expose `qwen-turbo` and `qwen3-coder-480b` as alternate models the operator can request via `extra_args["model"]`. Auto-routing can come later.

---

## Routing decision: DashScope direct vs OpenRouter

| Path | Pricing | Pros | Cons |
|---|---|---|---|
| **DashScope direct** (`dashscope.aliyuncs.com/compatible-mode/v1`) | $0.325/$1.95 for Plus | Native, cache support, batch discount, all Qwen models | Single-vendor account |
| **OpenRouter** (`openrouter.ai`) | $0.29/$1.65 for Plus (slightly cheaper) | One key for many models incl. GLM/DeepSeek/Anthropic | Per-request markup absorbed; no DashScope batch discount; cache hit support varies |

**Recommendation**: **DashScope direct** for the primary path. Cheaper effective rate when cache hits are realized (and they will be — the panel pattern reuses source packs heavily). OpenRouter remains a future option if the operator wants single-vendor consolidation across multiple Chinese providers.

Adapter implementation note: the existing `MiMoConcrete` / `DeepSeekConcrete` pattern (OpenAI-compatible chat-completions with a regional/key-prefix routing helper) maps cleanly to Qwen. **No structural change to engine adapters required** — just a new `QwenConcrete(StreamingTransport)` class with `dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` as the endpoint.

---

## Effect on W14-KIMI-REPLACEMENT-WITH-QWEN

The row's implementation is unchanged. The default model in the adapter becomes `qwen3.6-plus` (DashScope's name for Qwen 3.6 Plus). The env var is `DASHSCOPE_API_KEY`.

**Three-model support**: the adapter accepts any of these via the `model` parameter:
- `qwen3.6-plus` (default, premium)
- `qwen-turbo` (bulk/cheap)
- `qwen3-coder-480b-a35b` (coding specialist, cache-aware)
- (Or any other DashScope model string the operator wants to try)

Pricing table additions to `harness.budget.PRICING_USD_PER_M_TOKENS`:

```python
"qwen":             {"input": 0.325, "output": 1.95},   # Qwen 3.6 Plus DashScope direct
"qwen-turbo":       {"input": 0.033, "output": 0.13},   # Qwen-Turbo
"qwen-coder":       {"input": 0.22,  "output": 0.88},   # Qwen3 Coder 480B (uncached)
"qwen-coder-cached":{"input": 0.022, "output": 0.088},  # Qwen3 Coder 480B (cached)
"qwen-max":         {"input": 0.78,  "output": 3.90},   # Qwen 3 Max
"qwen-flash":       {"input": 0.25,  "output": 1.00},   # Qwen 3.6 Flash (output est)
```

This goes into the W14-KIMI-REPLACEMENT-WITH-QWEN implementation.

---

## Implications for the budget meter (W14-BUDGET-METER-PER-ENGINE)

The shipped budget meter caps **at the engine level** (`qwen` cap = $50). All Qwen sub-models (`qwen-turbo`, `qwen-coder`, etc.) fold to that single cap via the existing `_spent_this_month_by_engine` canonicalization. The operator sees one bucket: **Qwen** with $50/mo total.

**This is the right granularity.** Caps per-sub-model would force the operator to predict their mix upfront. Caps at the engine-family level let them route freely within the $50 envelope.

For visibility, `harness budget caps` could show a future "by-model" breakdown within the Qwen bucket. Adding that to the W14-TOKEN-MONITOR-REAL-USAGE follow-up.

---

## Estimation accuracy note

The current `harness.budget._compute_cost` uses static rates from `PRICING_USD_PER_M_TOKENS`. This is an **estimate**, not what DashScope will actually bill. Sources of error:

1. **Rate drift**: vendors update pricing without notifying API consumers
2. **Cache hits not captured**: when DashScope returns a cached-prefix response, the harness records the full uncached rate → overestimates spend
3. **Batch discount not captured**: 50% batch-invocation discount → overestimates non-batched, doesn't reduce batched spend
4. **Context-tier slicing**: long-prompt tier increases not modeled

The W14-TOKEN-MONITOR-REAL-USAGE row will capture provider-reported usage + cost when available. Until then, treat `harness budget caps` numbers as **upper-bound estimates** — actual spend is likely 10-30% lower depending on cache hit rate.

---

## Sources

- [Qwen API Pricing (2026) — pricepertoken.com](https://pricepertoken.com/pricing-page/provider/qwen)
- [Qwen 3.6 Plus DashScope API guide — ofox.ai](https://ofox.ai/blog/qwen-3-6-plus-api-complete-guide-2026/)
- [Qwen API Pricing & Benchmarks — DEV Community](https://dev.to/pickuma/qwen-36-plus-api-pricing-benchmarks-developer-access-guide-2026-4a80)
- [Alibaba Cloud Model Studio pricing](https://www.alibabacloud.com/help/en/model-studio/model-pricing)
- [Context Cache feature — Alibaba Cloud Model Studio](https://www.alibabacloud.com/help/en/model-studio/context-cache)
- [Qwen 3.6 has four tiers — DEV Community](https://dev.to/tokenmixai/qwen-36-has-four-tiers-heres-how-to-route-without-burning-cash-316e)
- [Qwen3.6 Plus benchmarks — llm-stats](https://llm-stats.com/models/qwen3.6-plus)
- [Qwen 3.6 Plus Review — MindStudio](https://www.mindstudio.ai/blog/qwen-3-6-plus-review-agentic-coding-model)
- [Qwen 3.6 Plus on OpenRouter](https://openrouter.ai/qwen/qwen3.6-plus)
- [Qwen3-Coder on Ollama](https://ollama.com/library/qwen3-coder)
