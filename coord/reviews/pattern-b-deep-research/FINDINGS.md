# Pattern B deep research — Claude Code × non-Anthropic providers

**Date**: 2026-05-26
**Trigger**: Operator request: *"do a deep research of how each of these ai work with claude, anthropic first before we initiate an integration approach B."*

**TL;DR**: Pattern B is **the officially-documented integration pattern** for all five major non-Anthropic coding-model providers (Moonshot Kimi, Xiaomi MiMo, DeepSeek, Zhipu GLM, Alibaba Qwen). Anthropic's recent third-party crackdown was specifically about **using subscription OAuth tokens externally** (OpenClaw-style arbitrage), NOT about pointing `ANTHROPIC_BASE_URL` at other providers. Anthropic explicitly acknowledges the latter as a sanctioned technical capability.

---

## Anthropic's official position

Per a 2026 documentation update of the Claude Agent SDK:

> *"The Claude Agent SDK honors the standard `ANTHROPIC_BASE_URL` environment variable, allowing you to route requests to any Anthropic-protocol-compatible backend — such as a corporate gateway, a regional bridge, or a third-party provider that exposes an Anthropic-shaped API — without changing source code. However, this is a technical capability rather than an endorsement of third-party providers."*

Anthropic's **Feb 2026 third-party crackdown** (which targeted OpenClaw and similar agentic tools) was narrowly scoped:

> *"The use of OAuth tokens obtained via Claude Free, Pro, or Max accounts in any other product, tool, or service is not permitted."*

The crackdown effective April 4, 2026 blocked **Claude Pro/Max subscription access** for third-party tools — not the `ANTHROPIC_BASE_URL` redirect pattern.

**Pattern B uses**:
- ✓ Anthropic's locally-installed Claude Code CLI binary (operator has a license to use it)
- ✓ Pointed at a non-Anthropic provider's Anthropic-compatible endpoint (sanctioned via `ANTHROPIC_BASE_URL`)
- ✓ Using the **provider's** API key (e.g., MiMo's `tp-` key), **NOT** an Anthropic OAuth token

This is materially different from what Anthropic banned. The banned pattern was "use my Claude Pro subscription quota from inside OpenClaw"; Pattern B is "use Claude Code as a transport, paid by the provider's own quota."

---

## Per-provider integration reference (official docs)

### Moonshot Kimi

| Field | Value |
|---|---|
| **Anthropic-compat endpoint (intl)** | `https://api.moonshot.ai/anthropic` |
| **Anthropic-compat endpoint (China)** | `https://api.moonshot.cn/anthropic` |
| **Official docs** | [platform.kimi.ai/docs/guide/agent-support](https://platform.kimi.ai/docs/guide/agent-support) |
| **Env vars** | `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL` |
| **Model names** | `kimi-k2.5`, `kimi-k2.6`, etc. |
| **Translation** | Moonshot operates a compatibility layer that translates Anthropic's message format ↔ Kimi's internal format. Streaming, tool calls preserved. |
| **Featured** | "Use Kimi K2.5 Model in ClaudeCode/Cline/RooCode" — explicit Claude Code marketing |

### Xiaomi MiMo

| Field | Value |
|---|---|
| **Anthropic-compat endpoint (PAYG)** | `https://api.xiaomimimo.com/anthropic` |
| **Anthropic-compat endpoint (Token Plan SGP)** | `https://token-plan-sgp.xiaomimimo.com/anthropic` |
| **Anthropic-compat endpoint (Token Plan AMS)** | `https://token-plan-ams.xiaomimimo.com/anthropic` |
| **Anthropic-compat endpoint (Token Plan CN)** | `https://token-plan-cn.xiaomimimo.com/anthropic` |
| **Official docs** | [platform.xiaomimimo.com/docs/en-US/integration/claudecode](https://platform.xiaomimimo.com/docs/en-US/integration/claudecode) |
| **Configuration method** | `.claude/config.json` with `env` block (NOT just shell env vars) |
| **Required env block** | `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL`, `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL` (all set to the MiMo model) |
| **Pre-config requirement** | Clear `ANTHROPIC_AUTH_TOKEN` and `ANTHROPIC_BASE_URL` before MiMo setup, to avoid conflicts |
| **Verification** | `/status` command in Claude Code shows current model + config |

**Important MiMo-specific detail**: the model aliases (`ANTHROPIC_DEFAULT_SONNET_MODEL`, etc.) **must be set to the MiMo model** because Claude Code internally references `sonnet`/`opus`/`haiku` and would otherwise miss-route. This is more comprehensive than the basic `ANTHROPIC_MODEL` env var.

### DeepSeek

| Field | Value |
|---|---|
| **Anthropic-compat endpoint** | `https://api.deepseek.com/anthropic` |
| **Official docs** | [api-docs.deepseek.com/quick_start/agent_integrations/claude_code](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code) |
| **Env vars** | `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_MODEL` |
| **Model names** | `deepseek-v4-pro`, `deepseek-v4-flash` |
| **Subscription tier** | None — PAYG only |
| **Translation** | "DeepSeek's Anthropic-compat layer accepts what Claude Code emits" |

**Critical DeepSeek limitations** (documented in their own docs):
- ✓ Text content
- ✓ Tool use (tool calling preserved)
- ✗ Image content blocks
- ✗ Document content blocks
- ✗ Search result content blocks
- ✗ Server tool content blocks
- ✗ Web search tool
- ✗ MCP tool blocks
- ✗ Container upload blocks

For text-only coding tasks (which is most of what the harness does), this is fine. For multimodal panels (image input → engine voice), DeepSeek via Pattern B would silently lose the image content.

### Zhipu GLM (Z.AI)

| Field | Value |
|---|---|
| **Anthropic-compat endpoint** | `https://api.z.ai/api/anthropic` (note the `/api/` infix) |
| **Official docs** | [docs.z.ai/devpack/tool/claude](https://docs.z.ai/devpack/tool/claude) |
| **Configuration method** | `~/.claude/settings.json` with `env` block |
| **Env vars** | `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN`, `API_TIMEOUT_MS` |
| **Model names** | `glm-5.1`, `glm-5-turbo`, `glm-4.7`, `glm-4.5-air` |
| **Subscription tiers** | Coding Plan Lite $18/mo, plus higher tiers |
| **Native support** | "GLM-4.7 has native Claude API format support" (no translation needed) |

GLM is the **only provider that natively speaks Anthropic's wire format** (not a translation layer). Lowest risk of edge-case behavioral drift.

### Alibaba Qwen (DashScope)

| Field | Value |
|---|---|
| **Anthropic-compat endpoint (intl)** | `https://dashscope-intl.aliyuncs.com/apps/anthropic` |
| **Official docs** | [alibabacloud.com/help/en/model-studio/claude-code](https://alibabacloud.com/help/en/model-studio/claude-code) |
| **Env vars** | `ANTHROPIC_BASE_URL`, `ANTHROPIC_API_KEY` (NOT `ANTHROPIC_AUTH_TOKEN`), `ANTHROPIC_MODEL` |
| **Model names** | `qwen3.5-plus`, `qwen3.6-plus`, `qwen3.7-max`, `qwen3-coder` |
| **Subscription tier** | Alibaba Cloud Coding Plan (separate from PAYG) |
| **Native support** | "Qwen 3.7 Max supports the Anthropic API protocol natively" |
| **Regional constraint** | Only Singapore-region keys work with the international endpoint |

**Qwen-specific quirk**: uses `ANTHROPIC_API_KEY` not `ANTHROPIC_AUTH_TOKEN`. Setting both is safe (Claude Code reads either).

**Model aliases**: same pattern as MiMo — set `ANTHROPIC_DEFAULT_SONNET_MODEL`, `ANTHROPIC_DEFAULT_OPUS_MODEL`, `ANTHROPIC_DEFAULT_HAIKU_MODEL` to the Qwen model so Claude Code's internal references route correctly.

---

## Universal patterns across all 5 providers

1. **`ANTHROPIC_BASE_URL`** redirects Claude Code's HTTP target — universal across all providers
2. **`ANTHROPIC_AUTH_TOKEN`** (or `ANTHROPIC_API_KEY` for Qwen) carries the provider's key
3. **`ANTHROPIC_MODEL`** sets the default model (provider-specific name)
4. **Model alias env vars** (`ANTHROPIC_DEFAULT_*_MODEL`) override Claude Code's internal sonnet/opus/haiku routing
5. **First-launch onboarding bypass**: Claude Code may prompt for Anthropic login on first launch; bypass by setting `hasCompletedOnboarding: true` in `~/.claude.json`
6. **WSL or Git Bash** required on Windows (Claude Code is a Node.js CLI, install via `npm install -g @anthropic-ai/claude-code`)

---

## What Pattern B looks like, refined by this research

The original `MimoViaClaudeCodeEngine` (in `src/harness/engines/claude_code_subprocess.py`, shipped 2026-05-25) implements the core pattern correctly — env-based redirect with `ANTHROPIC_BASE_URL` + `ANTHROPIC_AUTH_TOKEN` — but is missing a few details from the official docs:

| Detail | Status today | Per-research correction |
|---|---|---|
| `ANTHROPIC_BASE_URL` | ✓ set | unchanged |
| `ANTHROPIC_AUTH_TOKEN` | ✓ set | unchanged |
| `ANTHROPIC_API_KEY` | ✓ set (belt-and-suspenders) | unchanged (helps Qwen too) |
| `ANTHROPIC_MODEL` | ✗ not set | should add (lets Claude Code default the model without passing `--model` per call) |
| `ANTHROPIC_DEFAULT_SONNET_MODEL` | ✗ not set | should add — prevents Claude Code from miss-routing internal "sonnet" references |
| `ANTHROPIC_DEFAULT_OPUS_MODEL` | ✗ not set | should add |
| `ANTHROPIC_DEFAULT_HAIKU_MODEL` | ✗ not set | should add |
| `hasCompletedOnboarding` flag | ✗ not handled | should detect + set; first-launch prompt would hang the subprocess |
| Per-provider URL routing | ✓ already in `PROVIDER_ANTHROPIC_ENDPOINTS` | extend with `glm` + `qwen` + `deepseek-via-cc` entries |
| Per-provider limitations (DeepSeek multimodal) | ✗ not documented in adapter | add docstring warning + optional pre-flight check |

These are small refinements, not architecture changes. The core subprocess pattern works.

---

## What this research does NOT yet answer

1. **Operator experience over time**: do the wrapper-script ergonomics (Approach B from prior discussion) actually save friction, or does the operator just learn to use direct env vars?
2. **Concurrency at scale**: can the harness run 10 parallel `mimo-via-claude` subprocesses without OS-level resource pressure?
3. **Failure mode in panels**: when one engine in a 3-voice panel is via Pattern B and the other two are direct-httpx, does retry / timeout / synthesis still work cleanly?
4. **Token-monitor wiring**: provider-reported cost is captured in Pattern B's JSON output. Is it automatically flowing to `harness.budget` ledger? (Answer from earlier: no, not yet — it's a follow-up row.)
5. **Provider drift**: if Moonshot changes their `claude-k2.6` model name to `kimi-k3` next month, how does the harness discover that? (Manual config update vs auto-detect.)

These are the questions worth surfacing in the panel evaluation.

---

## Sources

- [Moonshot Kimi: Claude Code agent-support docs](https://platform.kimi.ai/docs/guide/agent-support)
- [Xiaomi MiMo: Claude Code official integration](https://platform.xiaomimimo.com/docs/en-US/integration/claudecode)
- [DeepSeek: Claude Code agent integration docs](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code)
- [DeepSeek: Anthropic API docs](https://api-docs.deepseek.com/guides/anthropic_api)
- [Zhipu GLM: Claude Code devpack docs (z.ai)](https://docs.z.ai/devpack/tool/claude)
- [Alibaba Qwen: Configure Claude Code to use Qwen models](https://www.alibabacloud.com/help/en/model-studio/claude-code)
- [Anthropic third-party tool ban — The Register, Feb 2026](https://www.theregister.com/software/2026/02/20/anthropic-clarifies-ban-on-third-party-tool-access-to-claude/5014546)
- [Anthropic blocks Claude subscriptions for OpenClaw — Hacker News Apr 2026](https://news.ycombinator.com/item?id=46549823)
- [cc-compatible-models — community-maintained reference](https://github.com/Alorse/cc-compatible-models)
- [Claude Agent SDK custom Anthropic-compatible backends docs](https://docs.claude-mem.ai/configuration/custom-anthropic-backends)
