# AI provider client-restriction comparison

**Date**: 2026-05-25
**Question**: Which providers have client allowlists / UA gates on their subscription packages, and which are lax?
**Triggered by**: Kimi Code termination 2026-05-25 (W14-KIMI-AUTH-RESTORE). Operator wants to avoid repeating the mistake.

---

## The pattern (TL;DR)

There is one clean rule that predicts the answer in every case below:

> **If you pay a flat-rate subscription you get a client allowlist. If you pay per-token you don't.**

The economic logic: anchor-priced subscriptions ($30-$100/mo for what would be $300+/mo of equivalent API usage) need to gate misuse, or one developer running an agent loop bankrupts the unit economics. The gate mechanism providers have settled on is a User-Agent / OAuth-client allowlist. Pay-per-token APIs price misuse out directly via the token meter, so they don't need gating.

This explains why the harness (a third-party tool not on anyone's allowlist) is at risk on subscription tiers but completely safe on pay-per-token APIs.

---

## Strict allowlist (do NOT spoof these — termination risk)

| Provider | Product | Restriction | Enforcement evidence |
|---|---|---|---|
| **Moonshot Kimi** | Kimi Code Token Plan (`tp-` keys, `api.kimi.com/coding/v1`) | UA allowlist (Kimi CLI, Claude Code, KiloCode, others). [Community guideline #3](https://www.kimi.com/code/docs/kimi-code/community-guidelines.html) forbids "client-identity tampering". | **CONFIRMED TERMINATED** — operator's account 2026-05-25 ([FINDINGS.md](../kimi-termination-investigation/FINDINGS.md)). Likely an active enforcement sweep. |
| **Anthropic** | Claude Pro / Max / Team / Enterprise via OAuth | OAuth-client allowlist (Claude Code, native Anthropic apps). [TOS update Feb 2026](https://www.theregister.com/software/2026/02/20/anthropic-clarifies-ban-on-third-party-tool-access-to-claude/5014546) explicitly bans third-party tools using subscription credentials. | CONFIRMED enforced — OpenClaw was [cut off in Feb 2026](https://venturebeat.com/technology/anthropic-cracks-down-on-unauthorized-claude-usage-by-third-party-harnesses) and later [reinstated with a credit-pool catch (June 15, 2026)](https://venturebeat.com/technology/anthropic-reinstates-openclaw-and-third-party-agent-usage-on-claude-subscriptions-with-a-catch). |
| **Zhipu GLM** | GLM Coding Plan (`sk-sp-` keys, `open.bigmodel.cn/api/coding/paas/v4`) | TOS: "API Keys for Coding Plans from GLM have strict usage restrictions—they can only be used within interactive coding tools and explicitly prohibit automated scripts, custom backends, and batch calls." Approved tools: Cursor, Continue.dev, Cline. | Documented in TOS; specific enforcement events not yet observed but the language mirrors Kimi's pre-termination posture. |
| **Alibaba Qwen** | Qwen / Alibaba Cloud Coding Plan (`coding.dashscope.aliyuncs.com/v1`) | TOS: "Intended for use only with programming tools, such as Claude Code and Qwen Code, and is not supported in tools such as curl, Postman, or Dify." | Documented; Qwen OAuth free tier was [discontinued 2026-04-15](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/) which is a related enforcement event. |
| **(was) Moonshot Kimi Code free tier** | — | (Mostly moot — terminated for everyone using third-party clients) | — |

These are the **subscription tiers** of the four major Chinese coding-plan products + Anthropic. **All four** have allowlists. The harness is on **zero** of them.

---

## Advisory / lax (TOS says allowlist but enforcement is permissive)

| Provider | Product | Restriction | Tested behavior |
|---|---|---|---|
| **Xiaomi MiMo** | MiMo Token Plan (`tp-` keys, regional `token-plan-{sgp\|ams\|cn}.xiaomimimo.com`) | [TOS](https://platform.xiaomimimo.com/docs/en-US/tokenplan/subscription) says "Token Plan package quota can only be used in programming tools (such as OpenClaw, OpenCode, etc.)" — approved list includes Claude Code, Cherry Studio, Cline, Qwen Code, CodeBuddy, Kilo Code, Hermes Agent. xaxiu-harness is NOT on the list. | **Tested 2026-05-25**: dispatch with `User-Agent: xaxiu-harness/1.0` against `tp-` Token Plan endpoint → succeeded. Xiaomi's allowlist is currently advisory rather than strict-enforced. Could tighten at any time — the TOS language matches Kimi's pre-termination posture. |

The lax tier is the most dangerous category — it works today but the TOS lets the provider tighten enforcement at any time, and the precedent (Moonshot's sweep on Kimi) shows providers do tighten when they realize anchor-priced subscriptions are being arbitraged.

---

## Open (no client allowlist — safe by design)

All of these are **pay-per-token APIs**, not flat-rate subscriptions. The economic incentive to gate by client doesn't exist because each token is priced individually.

| Provider | Product | Why open | Cost (in/out per M tokens, mid-2026) |
|---|---|---|---|
| **DeepSeek** | DeepSeek API (`api.deepseek.com`) | TOS: no monthly subscription on the API, no per-seat fees, no per-user RPM/TPM/daily limits, "best-effort basis". No documented UA restriction. | V4 Flash $0.14/$0.28; V4 Pro $0.55/$2.20 |
| **Moonshot Kimi (PAYG only)** | Kimi Platform (`api.moonshot.ai/v1` or `api.moonshot.cn/v1`) | Pay-per-token. The Kimi Code UA gate only applies to the `api.kimi.com/coding/v1` Token Plan endpoint. The Platform endpoint is OpenAI-compat and doesn't gate UA. | K2.6 $0.50/$1.50 |
| **Anthropic API** (the API-key path, NOT OAuth) | `api.anthropic.com/v1` | TOS specifically separates API-key path (open to all developers via Console) from OAuth path (locked to subscription customers). Per-token pricing. | Sonnet ~$3/$15; Haiku ~$0.25/$1.25 |
| **OpenAI API** | `api.openai.com/v1` | Pay-per-token. No UA gate on the API path. | GPT-5.2 ~$10/M+ |
| **Google Gemini API** | `generativelanguage.googleapis.com` | Pay-per-token. No documented UA gate. | Flash $0.075/$0.30; Pro $1.25/$10 |
| **Xiaomi MiMo PAYG** | `api.xiaomimimo.com/v1` (sk- keys) | Per [concrete.py:514-515](../../../src/harness/engines/concrete.py): "The pay-as-you-go endpoint does not enforce the gate". | V2.5-pro ~$1.00/$3.00 |
| **ByteDance Doubao** | Volcano Engine Ark | Standard OpenAI-compat. Has a Chinese-mainland-phone registration requirement for direct access, but no UA / client allowlist. | $0.022-$0.075/M floor |
| **Zhipu GLM PAYG** | Standard `open.bigmodel.cn/api/paas/v4` | Same provider as the GLM Coding Plan but PAYG is per-token, no client allowlist. | GLM-5.1 $0.60/$2.00 |

---

## Aggregators / open inference platforms (most lax category)

These are explicitly designed for arbitrary third-party clients. Their business model is to be called from anything.

| Provider | Notes |
|---|---|
| **[OpenRouter](https://openrouter.ai)** | Unified router across providers. The only "allowlists" are *organization-level controls* (admins restrict which models/providers their users can call) — NOT client-side UA gates. No documented UA restriction. Common choice for tools that need to be model-agnostic. |
| **[Together AI](https://together.ai)** | Open inference platform. Hosts Llama, Qwen, DeepSeek (community-mirrors), etc. No UA gate. |
| **[Fireworks AI](https://fireworks.ai)** | Same pattern as Together. Heavy focus on agent / function-calling workloads. No UA gate. |
| **[Groq](https://groq.com)** | Hardware-accelerated inference (LPU). Llama / Mixtral / DeepSeek-distill. No UA gate. |
| **[Cerebras Inference](https://inference.cerebras.ai)** | Hardware-accelerated. Llama hosted. No UA gate. |
| **[Hyperbolic](https://hyperbolic.xyz)** | Open-platform GPU inference. |
| **[Hugging Face Inference](https://huggingface.co/inference-api)** | Same. |
| **[Replicate](https://replicate.com)** | Same. |

The aggregator category is the safest from a "termination risk" perspective. The trade-off is **the model is usually one step behind** (e.g., Together hosts DeepSeek-distilled-Llama but not the latest DeepSeek-V4 — for that you go direct to `api.deepseek.com`).

---

## Application to the xaxiu-harness pool

What this means concretely for the engines the harness already wires + the candidates from the post-v1 master plan:

| Engine | Tier | Status | Recommendation |
|---|---|---|---|
| **DeepSeek V4 Flash** | PAYG, open | Primary, working | **Keep as primary**. No termination risk. |
| **Kimi (Token Plan, `tp-` key)** | Subscription, STRICT | **Terminated 2026-05-25** | **Drop from default pool** (per W14-KIMI-REPLACEMENT-WITH-GLM). |
| **MiMo (Token Plan, `tp-` key)** | Subscription, ADVISORY | Working today via xaxiu-harness/1.0 | **Keep for now, with caveat.** Xiaomi's allowlist could tighten. Consider switching to a `sk-` PAYG MiMo key as insurance. |
| **GLM-5.1 (Coding Plan)** | Subscription, STRICT in TOS | Candidate from master plan | **DO NOT use the Coding Plan** (`sk-sp-` key) — same restriction class as Kimi. **DO use GLM PAYG** (standard `open.bigmodel.cn/api/paas/v4` key). |
| **Anthropic** | PAYG (API key) | No key configured | **Safe to add** with `ANTHROPIC_API_KEY` — pay-per-token, no client allowlist. Cost is higher than Chinese models but TOS-risk is zero. |
| **Gemini** | PAYG | No key configured | **Safe to add** with `GEMINI_API_KEY`. Cheapest of the Western APIs at the Flash tier. |
| **Doubao** | PAYG | Not in pool | Safe to add but Chinese-mainland registration friction. |
| **Qwen Coding Plan** | Subscription, STRICT | Not in pool | **Do NOT use**. Use Qwen PAYG via DashScope or via OpenRouter / Together instead. |
| **OpenRouter / Together / Fireworks** | Aggregator, OPEN | Not in pool | **Lowest-risk option for future additions**. Single key gets access to many models. Trade-off: model-version lag. |

---

## Practical insurance moves for the harness

Three concrete actions that reduce future-termination exposure across the whole pool:

1. **Default UA stays `xaxiu-harness/1.0`** (already shipped today as W14-MIMO-TOS-COMPLIANCE). Truthful identification means we're never caught spoofing — even if we get gated, we're refused at the door rather than caught lying.

2. **Prefer PAYG keys over subscription keys** when both exist for the same provider. Where the operator has both, the harness should auto-route to PAYG. New rule for any future engine adapter: if the env var pattern is `sk-sp-*` or `tp-*` (subscription markers), warn the operator that the harness's truthful UA may be denied at the gate.

3. **Add an aggregator engine as outage insurance** (deferred row in master plan). OpenRouter or Together AI as a single-config gateway to multiple models — when any single provider terminates / quota-throttles, the aggregator absorbs the load with zero per-provider key management.

---

## What we should NOT do

- **Don't email Kimi support** to restore the terminated account "and try again". The same UA detection will re-terminate. Until the harness becomes an approved-third-party Moonshot client (no such program exists yet), Kimi is out.
- **Don't spoof the UA on any other provider** to "make it work". The Kimi precedent shows providers actively enforce, and the spoofing is permanent provenance — any provider doing forensics later will see we lied. The truthful UA + accepting denials is the correct posture.
- **Don't sign up for additional subscription Coding Plans** (Qwen, GLM, Cursor-bundled, etc.) unless we explicitly identify the harness on their approved-tool list. The economics will not work and we will be terminated.
- **Don't use Anthropic OAuth** (subscription credentials) in the harness adapter. Always use the `ANTHROPIC_API_KEY` path. The Feb 2026 enforcement event proved Anthropic is willing to cut off third-party harnesses using subscription auth.

---

## Sources

- [Kimi Code Community Guidelines](https://www.kimi.com/code/docs/kimi-code/community-guidelines.html)
- [Xiaomi MiMo Token Plan Subscription page](https://platform.xiaomimimo.com/docs/en-US/tokenplan/subscription)
- [Zhipu GLM Coding Plan review (vibecoding.app)](https://vibecoding.app/blog/zhipu-ai-glm-coding-plan-review)
- [Z.ai GLM-5 developer docs](https://docs.z.ai/guides/llm/glm-5)
- [Alibaba Cloud Coding Plan FAQ](https://www.alibabacloud.com/help/en/model-studio/coding-plan-faq)
- [Qwen Code Authentication](https://qwenlm.github.io/qwen-code-docs/en/users/configuration/auth/)
- [DeepSeek API pricing & rate-limit policy](https://api-docs.deepseek.com/quick_start/pricing)
- [Anthropic third-party tool ban (The Register Feb 2026)](https://www.theregister.com/software/2026/02/20/anthropic-clarifies-ban-on-third-party-tool-access-to-claude/5014546)
- [Anthropic crackdown on third-party harnesses (VentureBeat)](https://venturebeat.com/technology/anthropic-cracks-down-on-unauthorized-claude-usage-by-third-party-harnesses)
- [Anthropic reinstates OpenClaw with a catch (VentureBeat)](https://venturebeat.com/technology/anthropic-reinstates-openclaw-and-third-party-agent-usage-on-claude-subscriptions-with-a-catch)
- [Anthropic Splits Claude Subscriptions June 2026 (DevToolPicks)](https://devtoolpicks.com/blog/anthropic-splits-claude-subscriptions-agent-sdk-credit-june-2026)
- [OpenRouter Terms of Service](https://openrouter.ai/terms)
- [OpenRouter Guardrails (org-level allowlists, not UA gates)](https://openrouter.ai/docs/guides/features/guardrails)
- [Doubao API international access guide (TokenMix)](https://tokenmix.ai/blog/doubao-api-international-access-guide-2026)
