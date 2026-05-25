# Kimi Code termination — root-cause investigation

**Date**: 2026-05-25
**Trigger**: Friday v1.0.0 release-gate panel hit `HTTP 403 access_terminated_error` on every Kimi dispatch. Operator note: "Kimi Access termination seems to span other users as well."
**Status**: Root cause identified with high confidence. **Getting a new key will NOT fix this.**

---

## The 403 body (verbatim)

```
HTTP 403: {"error":{"message":"Access terminated. Review our Community Guidelines
(https://www.kimi.com/code/docs/kimi-code/community-guidelines.html) or contact
support@moonshot.cn for assistance.","type":"access_terminated_error"}}
```

Confirmed via raw `urllib` against all 3 Kimi endpoints:
- `api.kimi.com/coding/v1` → **HTTP 403 access_terminated_error** (the Kimi Code endpoint our key was issued for)
- `api.moonshot.ai/v1` → HTTP 401 invalid_authentication (Platform endpoint — wrong key type, expected)
- `api.moonshot.cn/v1` → HTTP 401 invalid_authentication (China Platform — same)

---

## Root cause

Kimi Code enforces a **User-Agent allowlist** and a **community-guidelines ban on client-identity tampering**. The harness violates both.

### Evidence #1: the harness ships a UA-spoofing default

[src/harness/engines/concrete.py:69-76](../../../src/harness/engines/concrete.py):

```python
def _make_kimi_user_agent() -> str:
    """Kimi Code API requires a whitelisted User-Agent (gate per
    ``reference_kimi_features_canonical``).  Default to ``claude-code/0.1.0``
    which is verified-working from inside Claude Code sessions; override
    via ``KIMI_USER_AGENT`` for other approved agents
    (e.g. ``KimiCLI/1.5``).
    """
    return os.environ.get("KIMI_USER_AGENT", "claude-code/0.1.0")
```

The harness explicitly identifies itself as `claude-code/0.1.0` — Anthropic's Claude Code CLI — to get past Kimi's UA gate. This was a deliberate workaround, documented as such, with the rationale that it was "verified-working from inside Claude Code sessions".

### Evidence #2: Kimi Code community guidelines forbid this

From [https://www.kimi.com/code/docs/kimi-code/community-guidelines.html](https://www.kimi.com/code/docs/kimi-code/community-guidelines.html) (fetched 2026-05-25), the four prohibited use cases:

| # | Prohibition (verbatim CN) | English |
|---|---|---|
| 1 | 不以商业化为目的转售账号或 API 访问权限 | Do not resell accounts or API access for commercial purposes |
| 2 | 不将 Kimi Code 的能力以任何形式二次分售 | Do not repackage Kimi Code's capabilities |
| 3 | **不伪造或篡改客户端身份信息** | **Do not forge or tamper with client identity information** |
| 4 | 不进行模型蒸馏训练 | Do not conduct model distillation training |

Item #3 is exactly what the harness does. The `claude-code/0.1.0` UA is a forged client identity used to bypass the gate.

### Evidence #3: third-party confirmation of the gate + the workaround pattern

From a public dev.to writeup ([DeepSeek vs Qwen vs Kimi vs GLM 2026](https://dev.to/truelane/deepseek-vs-qwen-vs-kimi-vs-glm-which-ai-api-actually-wins-in-2026-a-cost-optimizers-verdict-4235)) and the GLM Coding endpoint docs:

> "Kimi's API uses user-agent allowlisting and only allows known coding CLIs (including Kimi CLI and Claude Code) through user-agent sniffing. To work around API access restrictions, a User-Agent header of `kimi-cli/1.0` was used."

The "workaround" is widely documented. So is the enforcement: **Moonshot now actively detects and terminates accounts using non-approved clients**.

### Enforcement policy

The community guidelines state (verbatim):

> 先评估情况，再根据情节进行**暂停访问**等处理
> ("Evaluate circumstances, then implement suspension of access based on severity")

> 通过未授权渠道获取服务的用户将面临账号关闭，损失由用户承担
> ("Users obtaining service through unauthorized channels face account closure, with losses borne by the user")

---

## Why getting a new key will NOT fix this

If the operator gets a new Kimi Code account and the harness keeps sending `User-Agent: claude-code/0.1.0`, Kimi will detect it and terminate again on first or second use. The detection signal (UA mismatch vs. expected Claude Code traffic pattern) doesn't depend on the key — it depends on the dispatched requests.

Confirmed by the operator's observation: **"Kimi Access termination seems to span other users as well"** — this matches a provider-side enforcement sweep, not a single-account flag. The community guidelines were likely updated (or enforcement tightened) in the period before today's termination event.

---

## What we should do

### Immediate (within v1.0.0.x patch window)

1. **STOP shipping the spoofed UA default**. Change [src/harness/engines/concrete.py:76](../../../src/harness/engines/concrete.py) from `"claude-code/0.1.0"` to `"xaxiu-harness/1.0"`. Accept that this will mean Kimi denies xaxiu-harness traffic at the gate. The current behavior is non-compliant and we should not ship it past v1.0.0.

2. **Drop Kimi from the default fallback chain** (already gated by W13-ENGINE-FAILURE-VISIBILITY + the master plan's W14-DISPATCH-HEALTH-AWARE-FALLBACK). Kimi becomes `disabled` until Moonshot offers an approved third-party agent license.

3. **Update W14-KIMI-AUTH-RESTORE** to reflect: do NOT email support to restore — the harness as-built violates the guidelines. Restoration only makes sense if (a) Moonshot accepts xaxiu-harness as an approved agent or (b) the harness is rebuilt to use legitimate Kimi-issued credentials and a non-spoofed UA. Both are open-ended.

### Replacement engines (alternatives survey)

Engines that are **OpenAI-compatible**, don't have UA-allowlist gates, and are production-stable as of May 2026:

| Engine | Per-M tokens (in/out) | Notes | Recommendation |
|---|---|---|---|
| **DeepSeek V4 Flash** (already pool) | $0.14 / $0.28 | Existing primary. Anthropic + OpenAI compatible. Continues. | **Keep as primary** |
| **GLM-5.1** (Zhipu) | $0.60 / $2.00 | Open-weight under MIT. OpenAI + Anthropic API compatible. Scored 85 on BenchLM, 77.8% on SWE-bench Verified — near Claude Opus 4.5 on agentic coding. No UA gate. | **Top pick to replace Kimi slot** |
| **Qwen 3.6 Max-Preview** (Alibaba) | $0.40 / $1.20 | Open-weight. OpenAI-compatible. Mature SDK. Lower SWE-bench than GLM but cheaper. | **Second pick — cheaper backup** |
| **Doubao 1.6** (ByteDance) | ~$0.075 / M | Cheapest. Less mature SDK + less English-language tooling. | Tier-3 fallback only |
| **MiMo v2.5-pro** (Xiaomi) — already pool | tp- subscription | Existing pool member. Continues. | Keep |
| **MiniMax M2.7** | not surveyed | Separate from MiMo (which is Xiaomi). Skip pending more data. | Skip |

Recommendation: **add GLM-5.1 as the Kimi-replacement engine**. Open-weight + MIT licensed + benchmark performance close to Claude Opus = zero termination risk + good fallback quality.

### Implementation path

This becomes a new top-priority row in the master plan:

> **W14-KIMI-REPLACEMENT-WITH-GLM** (M, ~5h)
>
> Drop Kimi from the production engine pool. Add GLM-5.1 as a new engine adapter using the existing `StreamingTransport` base + OpenAI-compatible chat-completions schema. Set `_make_kimi_user_agent` to `xaxiu-harness/1.0` to bring the existing Kimi code into TOS compliance (Kimi traffic will now be denied, which is the correct outcome). MiMo's existing transport pattern is the reference implementation.

This row should ship in the THIS WEEK lineup, ideally before W14-DISPATCH-HEALTH-AWARE-FALLBACK so the fallback already knows about GLM.

---

## Sources

- [Kimi Code Community Guidelines (CN, official)](https://www.kimi.com/code/docs/kimi-code/community-guidelines.html)
- [DeepSeek vs Qwen vs Kimi vs GLM: Which AI API Actually Wins in 2026? — dev.to](https://dev.to/truelane/deepseek-vs-qwen-vs-kimi-vs-glm-which-ai-api-actually-wins-in-2026-a-cost-optimizers-verdict-4235)
- [Best Chinese AI Models 2026 — TokenMix](https://tokenmix.ai/blog/best-chinese-ai-models-2026-comparison-guide)
- [Chinese AI Models 2026: GLM-5, DeepSeek, Kimi K2.5 — deathscore.ai](https://deathscore.ai/research/chinese-ai-models/en)
- [The Late-April 2026 Chinese LLM Stack — dev.to](https://dev.to/bean_bean/the-late-april-2026-chinese-llm-stack-qwen-36-deepseek-v4plus-kimi-k26-minimax-m27-glm-51-2bif)
- [MoonshotAI/kimi-cli — GitHub (official)](https://github.com/MoonshotAI/kimi-cli)
- [Kimi K2.5 in Claude Code / Cline / RooCode — platform.kimi.ai](https://platform.kimi.ai/docs/guide/agent-support)
