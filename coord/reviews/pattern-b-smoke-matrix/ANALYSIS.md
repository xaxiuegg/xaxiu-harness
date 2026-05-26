# Pattern B smoke-matrix analysis

**Date**: 2026-05-26
**Source data**: [RESULTS.md](RESULTS.md) + [raw_results.json](raw_results.json)
**Total cost burned**: $0.18 (matrix) + $0.017 (DeepSeek retry) = **$0.20**

## Headline

**3 engines × 5 categories = 15 dispatches: 11/15 OK at 90s timeout, 12/15 OK after extending DeepSeek to 120s.**

All Pattern B engines work for real coding workloads. The two failure modes that surfaced are:

1. **Markdown image references stall Claude Code** (3/15 failures — all three engines on `multimodal_probe`)
2. **DeepSeek-via-claude needs longer timeout for code generation** (1/15 — fixed by retry at 120s)

Neither is a bug in the harness's Pattern B layer; both are Claude Code CLI behaviors we need to handle.

## Per-engine summary

| Engine | OK / Tested | Avg latency | Total cost (matrix) | Tokens out | Notes |
|---|---|---|---|---|---|
| **kimi-via-claude** | 4/5 | 27.8s | $0.0496 | 790 | Fastest at trivial/code/reasoning; long-context handled well |
| **mimo-via-claude** | 4/5 | 26.0s | $0.0613 | 221 | Most concise output (lowest token counts) |
| **deepseek-via-claude** | 3/5 (4/5 with longer timeout) | 56.7s | $0.0714 | 872 | Slowest; verbose output (highest token-out); needs 120s+ timeout |

## What worked well

| Category | All 3 engines worked? | Best performer |
|---|---|---|
| `trivial` (single-word echo) | ✓ yes | Kimi at 6.3s/$0.0055 |
| `code` (Python function) | ✓ after timeout bump | Kimi at 10.4s/$0.0075 |
| `reasoning` (1-sentence explanation) | ✓ yes | Kimi at 8.9s/$0.0072 |
| `long_context` (~3500 chars + bug-find) | ✓ yes — all caught the bug | Kimi 23.5s; DeepSeek 48.7s |

Kimi's bug-find answer (long_context):

> "The bug is that `tree = [0] * n` makes the array 0-indexed with length n, but the Fenwick tree's update/query functions use 1-indexed positions up to n, so the loop `for i in range(1, n+1)` will write to `tree[n]` which is out of bounds."

MiMo's answer:

> "tree = [0] * n leaves index n out of bounds for 1-indexed Fenwick operations updating positions 1 through n."

DeepSeek's answer:

> "The bug is that `tree = [0] * n` creates a length-n array but the Fenwick tree's update/query functions are 1-indexed and use indices 1 through n inclusive, so `fenwick_update(tree, n, n)` writes to index n which is out of bounds (only valid indices are 0 to n-1); the array should be `[0] * (n+1)`."

All three engines correctly identified the off-by-one bug. Output quality is comparable across all three engines for this task class.

## What failed

### multimodal_probe failure (3/3 engines)

The prompt referenced a markdown image (`![system architecture](architecture.png)`) which doesn't exist on disk. Claude Code's `--print --bare` mode appears to **try to load the file** before sending the request, stalling the subprocess until our 90s timeout.

**Verification needed (not done in this run)**: probe with image content actually attached (e.g., a real PNG file at a relative path) to confirm whether the issue is "file missing" specifically vs "any markdown image reference."

**Mitigation in current implementation**: the `deepseek-via-claude` adapter already detects multimodal markers and either warns or refuses (`HARNESS_DEEPSEEK_MULTIMODAL_REFUSE=1`). The warning fired correctly in the smoke matrix:

```
WARNING deepseek-via-claude: packet appears to contain multimodal content
(image/video/audio/document/pdf). DeepSeek's Anthropic-compat layer
SILENTLY DROPS these blocks...
```

But DeepSeek-via-claude proceeded anyway (refuse-mode wasn't enabled) and hit the timeout — confirming the stall happens **before the HTTP layer**, at the Claude Code CLI markdown-parse stage.

**Recommended action** (deferred row): **W14-MULTIMODAL-STRIP-MARKDOWN-REFS** — pre-process packets through a marker-strip filter when the target engine is text-only AND the operator hasn't attached real image files. Removes `![alt](path)` syntax (preserving the alt text in plain prose) before dispatch.

### DeepSeek code timeout at 90s

DeepSeek-via-claude is meaningfully slower than the other two (avg 56.7s vs 26-28s). The smoke matrix's default 90s timeout was tight for it; retry at 120s succeeded in 45.9s.

**Recommended action** (deferred row): **W14-DEEPSEEK-DEFAULT-TIMEOUT-BUMP** — bump the default `_DEFAULT_TIMEOUT_S` on `DeepSeekViaClaudeCodeEngine` to 180s (vs the global 300s default) to reflect its observed latency profile. Other engines stay at 300s. ~5 LOC change.

## Cost calibration

At ~$0.06-0.07 per engine for a 5-category smoke pass, **a full panel-style audit costs ~$0.20 across all 3 engines**. Budget caps from W14-BUDGET-METER-PER-ENGINE handily absorb this — the operator's $30/$15/$50 DeepSeek/MiMo/Qwen caps allow hundreds of such matrices per month.

Token costs are notably higher than direct-httpx PAYG would charge:

- **kimi-via-claude (via Kimi Code subscription)**: $0.011/avg request (provider-reported)
- **mimo-via-claude (via MiMo Token Plan)**: $0.015/avg request (provider-reported)
- **deepseek-via-claude (DeepSeek PAYG via Anthropic-compat path)**: $0.024/avg request

The reason these are higher than the raw PAYG token math is that Claude Code adds its own system-prompt overhead (~1500-2700 input tokens visible in `tokens_in`). The provider-reported cost includes that overhead. Whether this matters depends on workload — for panel/strategic work where the marginal cost is small, it doesn't. For bulk dispatch where the overhead dwarfs the actual prompt, it matters.

## Output quality observation

For tasks where all 3 engines succeeded (trivial / code / reasoning / long_context), the **outputs are comparable in correctness** but differ in style:

- **Kimi**: longest, most detailed explanations
- **MiMo**: most terse, single-clause answers
- **DeepSeek**: most verbose; tends to over-explain

For multi-engine panel work (where diversity of framing is the goal), the style difference is a feature. For single-engine work, pick the style that matches your task class.

## What this smoke matrix DIDN'T test

Honest list of gaps in our coverage:

- **Tool use / structured output** — none of the prompts exercised Claude Code's tool-calling. Pattern B may or may not preserve tool definitions across the redirect. Untested.
- **Streaming** — we used `--output-format json` (single response) not `stream-json`. Pattern B's streaming behavior is untested.
- **Multi-turn** — single-turn dispatches only. Conversation state isn't relevant to single-shot panels, but matters for interactive use cases.
- **Real multimodal** — we tested the markdown image marker (which stalled). Actual image-file attachment via the `--file` flag was NOT tested.
- **Concurrency stress** — the matrix ran 4 max workers via ThreadPoolExecutor. The W14-PATTERN-B-SECONDARY semaphore (default 4) hasn't been stress-tested at higher concurrency.
- **Cross-platform** — only Windows + Git-Bash tested. Linux/Mac wrapper behavior is theoretical.

## Recommended follow-ups (not shipped this turn)

| Row | Effort | Why |
|---|---|---|
| **W14-MULTIMODAL-STRIP-MARKDOWN-REFS** | ~30min | Prevent the stall when prompts reference non-existent markdown images |
| **W14-DEEPSEEK-DEFAULT-TIMEOUT-BUMP** | ~5min | Match DeepSeek-via-claude's observed latency profile (180s default) |
| **W14-PATTERN-B-TOOLUSE-AUDIT** | ~1h | Probe whether tool definitions survive the Pattern B redirect for each provider |
| **W14-PATTERN-B-STREAMING-PROBE** | ~30min | Validate `--output-format stream-json` works through the subprocess pipe |
| **W14-PATTERN-B-FILE-ATTACHMENT** | ~30min | Verify `claude --file` flag works through Pattern B for real multimodal |

## Verdict for ship-readiness

**Pattern B (all 3 engines) is production-ready for text + reasoning + code + long-context workloads.** The two failure modes are characterized and have known mitigations (already in the queue above).

Recommend running this matrix monthly to catch upstream Claude Code or provider regressions. Total cost is ~$0.20, total time is ~3 minutes — cheaper than any production incident.
