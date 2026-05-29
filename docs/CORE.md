# xaxiu-harness — the usable core

> The post-2026-05-29 trim north-star. The harness grew into a ~20k-LOC,
> 60-verb "platform"; this is the small core it is being trimmed back to.
> Full pre-trim state is restorable: `git checkout archive/pre-trim-2026-05-29`.

## What this is (one line)
A **cross-vendor LLM command surface**: ask the same question to several engines
(DeepSeek / MiMo / Kimi / …) and compare them side-by-side, with cost tracking
and an OpenAI-compatible proxy. **The value is the cross-vendor layer, not any
single engine.**

## The core — what you actually use
| Verb | What it does |
|---|---|
| `ask "…" [--panel \| --audit] [--engines a,b,c]` | **THE verb.** Ask 1 or N engines and compare. The cross-vendor compare is the harness's only real moat. |
| `proxy start --upstream X` | OpenAI-compatible HTTP endpoint for third-party tools. |
| `keys` / `env` | Manage provider API keys (live User-scope resolution — survives rotation). |
| `doctor` / `introspect` | Health-check + one-call surface discovery. |

The audit ledger (cost + forensic trail) writes automatically on every `ask`.

## The architecture — who owns what
```
xaxiu-harness   orchestration + observability ABOVE vendors
                (ask/compare • proxy • keys • audit) — does NOT wrap CLIs
      │  agentic / multi-file work →
      ▼
xaxiu-swarm     the SOLE wrapper of the Kimi CLI (multi-file agentic dispatch)
      ▼
Kimi CLI /      execution substrate: subagents, web research (FetchURL),
provider /v1    tools. The Kimi CLI can drive Kimi OR MiMo/DeepSeek/Qwen.
```
**Rule (panel-validated, DeepSeek + Kimi):** *Harness does not wrap CLIs — swarm
does. Native Claude Code (`/goal`, Workflows, subagents, hooks) handles
single-vendor in-session orchestration. The harness stays the cross-vendor
layer above all of them.*

## Engines available to `ask`
- **Direct HTTP (Pattern A):** `deepseek`, `mimo`, `qwen`.
- **Via Claude Code subprocess (Pattern B):** `deepseek-via-claude`,
  `mimo-via-claude`, `kimi-via-claude` (TOS-correct for UA-gated providers).
- **Agentic Kimi (subagents + web research):** `kimi-cli` (drives the Kimi CLI;
  can also drive MiMo as a provider for agentic web research).

## Trim status (2026-05-29, in progress)
- **Done:** archived full v1 (`archive/pre-trim-2026-05-29`); deleted dead
  `web_search` + `claude-via-cc` engines (~750 LOC); fixed the P16 live-key
  regression; verified the core reliable live (`ask` + providers + `kimi-cli`).
- **In progress (careful, coupled):** route `coord` → swarm; replace
  `loops`/`observer`/`orchestrator` with native Claude (preserving cross-vendor
  observability as `ask --panel`, NOT Claude-only hooks); remove `dashboard`
  + the one-off verbs + dev-loop global flags; clean inert base-engine code.

## When NOT to reach for the harness
- **Agentic multi-file work** → `xaxiu-swarm`.
- **In-session "keep going" / orchestration** → native Claude (`/goal`, Workflows).
- **A single quick call** → call the provider (or `WebSearch`) directly.
