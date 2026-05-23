# Engine reliability — production guidance

**Last updated**: 2026-05-23 (post-W5-3ENGINE comprehensive testing)

## Summary

| Engine | Path | Use case | Reliability |
|--------|------|----------|-------------|
| MiMo Pro v2.5 | `swarm/mimo` (auto-routes to mimo-v2.5-pro) | Default worker for any task | 2/2 standalone in pilots; 3/3 at 8192 budget |
| DeepSeek v4-flash | `swarm/deepseek` (force `--model deepseek-v4-flash` via W5-N) | Reasoning-heavy worker OR fallback rescuer | 0/3 standalone for FILE/REPLACE (drifts to prose+markdown); 100% as fallback to rescue MiMo drift |
| Kimi K2.6 (CLI) | `swarm/kimi` (uses xaxiu-swarm CLI, agentic) | Tool-using tasks (open files, navigate repo) | 2/3 pilot; CONTENT-SHAPE DEPENDENT |
| Kimi K2.6 (HTTP API) | `swarm/kimi-api` (direct HTTP) | Short non-thinking tasks only | 0/3 source-laden — hits 60s server-side thinking cap |

## Cost

- MiMo: $0 via tp- (Token Plan) subscription — flat rate, "unlimited" effective budget
- Kimi (both paths): $0 via tp- subscription
- DeepSeek: pay-per-token, ~$0.001-0.003 per typical dispatch

## Production patterns

### Default for code-edit work
```
--engine swarm/mimo
```

### Belt-and-suspenders for code edits (DeepSeek can be primary too)
```
--engine swarm/mimo --fallback-engine swarm/deepseek
```

### Reasoning-heavy task (planning, spec composition, code review)
```
--engine swarm/deepseek --fallback-engine swarm/mimo
```

### Agentic / repo-navigation task
```
--engine swarm/kimi --fallback-engine swarm/mimo
```

## Known failure modes

1. **DeepSeek prose+markdown drift** (~50% of FILE/REPLACE on real code):
   engine narrates what it would do + emits the file in a ``` fence
   instead of FILE/REPLACE blocks.  Worker parses 0 edits; W4-A fires
   `silent_no_op`; fallback engine rescues.
2. **MiMo silent-empty at tight max_tokens** (W4-G campaign at 1500
   tokens): engine spent all budget on thinking, emitted 0 final
   tokens.  Resolved by leaving `max_tokens` at default (32k) in
   production code paths.  Probe scripts must omit `max_tokens`.
3. **Kimi HTTP API 60s thinking-time cap**: server-side limit on
   `api.kimi.com/coding/v1/chat/completions`.  Big packets hit it,
   return `err=internal`.  Use `swarm/kimi` (CLI agentic) instead for
   anything > 1KB.
4. **Engine SEARCH-text drift on FILE/REPLACE**: subtle whitespace or
   signature changes (e.g. `def main():` vs `def main() -> int:`).
   W5-J CRLF-tolerant + W5-R whitespace-fuzzy matching rescue most.
   Truly different content can only be rescued by fallback engine
   retry.
