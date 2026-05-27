# W14-MIMO-PRODUCTION-VALIDATION — synthesis

**Date**: 2026-05-26
**Method**: 10 prompts × 3 engines + 10-way concurrent MiMo stress.

## Per-engine summary (corpus phase)

| Engine | OK / 10 | Score / 30 checks | Total cost | Avg latency | Avg tokens out |
|---|---|---|---|---|---|
| `mimo-via-claude` | 10/10 | 31/31 | $0.0875 | 36.8s | 110 |
| `deepseek-via-claude` | 10/10 | 30/31 | $0.1105 | 10.2s | 147 |
| `kimi-via-claude` | 10/10 | 30/31 | $0.2452 | 39.0s | 839 |

## Per-prompt comparison

Score format: ✓N/M (N checks passed of M total).

| Prompt | Category | mimo | deepseek-flash | kimi |
|---|---|---|---|---|
| code_function | code-gen | ✓3/3 (55.9s) | ✓3/3 (16.5s) | ✓3/3 (31.0s) |
| reasoning_short | reasoning | ✓2/2 (16.8s) | ✓2/2 (10.3s) | ✓2/2 (21.6s) |
| structured_json | structured-output | ✓3/3 (18.9s) | ✓3/3 (12.2s) | ✓3/3 (14.9s) |
| long_context_bugfind | long-context | ✓2/2 (58.3s) | ✓2/2 (14.9s) | ✓1/2 (69.2s) |
| multi_turn_instruction | multi-step-instruction | ✓4/4 (16.9s) | ✓4/4 (6.2s) | ✓4/4 (22.7s) |
| concise_constraint | length-compliance | ✓4/4 (17.0s) | ✓4/4 (8.2s) | ✓4/4 (50.4s) |
| no_tool_call_markup | markup-clean | ✓5/5 (33.5s) | ✓5/5 (8.2s) | ✓5/5 (16.5s) |
| audit_class_short | audit-class | ✓3/3 (41.5s) | ✓3/3 (10.0s) | ✓3/3 (42.3s) |
| contradictory_instructions | adversarial | ✓1/1 (58.8s) | ✓0/1 (7.7s) | ✓1/1 (71.9s) |
| find_replace_format | structured-edit | ✓4/4 (49.9s) | ✓4/4 (8.0s) | ✓4/4 (49.4s) |

## Concurrency stress (Phase 3)

Fired 10 simultaneous MiMo dispatches.

- Success: 10/10
- Latency: min 11.8s, p50 18.4s, p95 27.7s, max 27.7s
- Total cost: $0.0332
- Rate-limit / throttling observed: no

## Audit-panel concerns: empirical answers

**Tool-call XML markup quirk** — does MiMo emit unexecuted `<tool_call>` / `<function_call>` markup that breaks downstream parsing?

**Clean: 0/10 MiMo responses contained tool-call XML markup.**  The `--tools ""` flag combined with our explicit 'no tool-call markup' instructions in some prompts is effective.

**Word-count compliance** — does MiMo respect explicit length caps in prompts?

**Clean: MiMo respected all word-count caps.**

## Verdict

- MiMo score: 100%
- DeepSeek-flash score: 97%
- Kimi score: 97%
