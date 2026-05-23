# Engine reliability — production guidance

**Last updated**: 2026-05-23 (post-W5-V wiring fix + W5-W max_tokens unbounded)

## Summary

| Engine | Path | Use case | Reliability |
|--------|------|----------|-------------|
| MiMo Pro v2.5 | `swarm/mimo` (auto-routes to mimo-v2.5-pro) | Default worker for any task | 2/3 source-laden (W5-V verify); intermittent `err=internal` on medium packets |
| DeepSeek v4-flash | `swarm/deepseek` (force `--model deepseek-v4-flash` via W5-N) | Reasoning-heavy worker OR fallback rescuer | 3/3 source-laden (W5-V verify); 100% as fallback to rescue MiMo drift |
| Kimi K2.6 (HTTP API) | `swarm/kimi-api` (direct HTTP, streaming SSE) | Code review, reasoning, large packets | **3/3 source-laden (W5-V verify); was 0/5 pre-W5-V** |
| Kimi K2.6 (CLI) | `swarm/kimi` (uses xaxiu-swarm CLI, agentic) | Tool-using tasks (open files, navigate repo) | 2/3 pilot; agentic via Edit/Write tools |

## Cost

- MiMo: $0 via tp- (Token Plan) subscription — flat rate, "unlimited" effective budget
- Kimi (both paths): $0 via tp- subscription
- DeepSeek: pay-per-token, ~$0.001-0.003 per typical dispatch

## Production patterns

### Default for code-edit work
```
--engine swarm/mimo --fallback-engine swarm/deepseek
```

### Reasoning-heavy task (planning, spec composition, code review)
```
--engine swarm/deepseek --fallback-engine swarm/mimo
```

### Source-laden code review (Kimi now works post-W5-V)
```
--engine swarm/kimi-api --fallback-engine swarm/deepseek
```

### Agentic / repo-navigation task
```
--engine swarm/kimi --fallback-engine swarm/mimo
```

## W5-V Kimi wiring fix (2026-05-23) — RESOLVED 0/10 historical

Three bugs that caused Kimi to silent-empty on 100% of source-laden packets:

1. **Missing `stream=true` in payload**: non-streaming requests on
   `api.kimi.com/coding/v1/chat/completions` hit a 60s server-side
   thinking cap and return `err=internal` (which the old probe code
   parsed as silent-empty).  Fix: always set `stream=true`.
2. **Non-standard SSE format**: Kimi emits `data:{json}\n\n` (no space
   after colon) instead of the OpenAI-standard `data: {json}\n\n`.
   The harness's SSE parser only handled the standard format.  Fix:
   accept BOTH `data: ` AND `data:` prefixes.
3. **Missing `import json` in concrete.py**: streaming code path
   referenced `json.loads` without the import; raised silently inside
   the iter_lines loop and produced empty content.  Fix: explicit
   import at module top.

**Verified 2026-05-23 via `scripts/verify_source_laden_3engines.py`**:
3/3 packets (5.7KB, 1KB, 23KB source) all return clean JSON.
Latency 33-287s depending on packet + reasoning depth.

## W5-W max_tokens unbounded (2026-05-23)

Operator directive: don't artificially cap max_tokens on
unlimited-subscription engines (Kimi/MiMo via tp- keys).

Engine defaults raised in `src/harness/engines/concrete.py`:
- Kimi K2.6: 32K → 200K (Kimi supports 256K total context)
- MiMo V2.5: 32K → 131K (hardware max)
- DeepSeek: unchanged at 32K (sk- pay-per-token, cost-bounded)

Empirical observation: Kimi naturally produces reasonable outputs
(~200 chars for JSON probes) even with unbounded ceiling — the
ceiling is a safety stop, not a budget allocation.  Reasoning tokens
(5K-8K observed on 23KB packets) consume the headroom but the engine
still terminates naturally.

## Known failure modes

1. **DeepSeek prose+markdown drift** (~50% of FILE/REPLACE on real code):
   engine narrates what it would do + emits the file in a ``` fence
   instead of FILE/REPLACE blocks.  Worker parses 0 edits; W4-A fires
   `silent_no_op`; fallback engine rescues.
2. **MiMo intermittent `err=internal`** on small-to-medium packets
   (~60s gateway timeout, observed 1/9 W5-V verify): treat as
   transient; W5-O fallback chain rescues.  Not a wiring bug — the
   upstream gateway flakes.
3. **Engine SEARCH-text drift on FILE/REPLACE**: subtle whitespace or
   signature changes (e.g. `def main():` vs `def main() -> int:`).
   W5-J CRLF-tolerant + W5-R whitespace-fuzzy matching rescue most.
   Truly different content can only be rescued by fallback engine
   retry.
