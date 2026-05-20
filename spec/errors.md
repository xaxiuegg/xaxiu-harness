# Spec: Error taxonomy (Wave A.5)

## Two-axis tag

Every error in xaxiu-harness carries a tag `L<level>.<domain>.<code>` plus a message.

### Severity (L1-L5)

| Level | Name | Definition | Default behavior |
|---|---|---|---|
| L1 | INFO | Expected event worth noting | Log, continue |
| L2 | WARN | Degraded path succeeded | Log w/ detail, continue |
| L3 | ERROR | Operation failed; system intact | User-visible error, exit non-zero, continue running for other operations |
| L4 | CRITICAL | Integrity threat; partial halt | Quarantine affected state, halt automation for that domain, emit forensic detail |
| L5 | FATAL | Operator action needed (loop never globally halts; only affected phase pauses with auto-retry) | Pause affected phase, write to notification target, retry on backoff |

L5 is the only escalation trigger for the operator under the full-dev-authority directive. L1-L4 stay autonomous.

### Domain

One of: `dispatch | engines | state | secrets | schema | network | config | observer`

### Code

Short stable identifier with `E_` prefix. Used for programmatic matching and runbook lookups. Examples: `E_DISPATCH_EXHAUSTED`, `E_DPAPI_UNREADABLE`, `E_SCHEMA_VIOLATION`.

## Python class hierarchy

`src/harness/errors.py` defines:

- `HarnessError(Exception)` — base class with `level: int (1-5)`, `domain: str`, `code: str`, `message: str`, optional `context: dict`.
- `tag()` method → `"L<n>.<domain>.<code>"`.
- `to_dict()` method → JSON-serializable payload with all fields.
- Subclasses set defaults via class-level attributes; instances can override `context` only.

First-wave subclasses (more added by Wave A.6 retrofit):

| Subclass | Tag | Raised by |
|---|---|---|
| `DispatchExhausted` | `L3.dispatch.E_DISPATCH_EXHAUSTED` | dispatcher when all engines failed for a packet |
| `EngineTimeout` | `L3.engines.E_ENGINE_TIMEOUT` | engine HTTP client when request exceeds timeout |
| `EngineRefusal` | `L3.engines.E_ENGINE_REFUSAL` | guards when output matches refusal pattern |
| `PacketTrap` | `L4.engines.E_PACKET_TRAP` | guards when output is a DSML tool-call attempt |
| `SchemaViolation` | `L4.schema.E_SCHEMA_VIOLATION` | jsonl writer / adapter loader on unknown fields |
| `DpapiUnreadable` | `L5.secrets.E_DPAPI_UNREADABLE` | secrets when DPAPI decrypt fails |
| `AllEnginesUnreachable` | `L5.network.E_ALL_ENGINES_UNREACHABLE` | dispatcher when every engine is in cooldown/unreachable |
| `GitPushFailed` | `L5.network.E_PUSH_FAILED` | integrating supervisor on auth/network push errors |
| `ConfigCorruption` | `L5.config.E_CONFIG_CORRUPTION` | adapter loader on YAML parse failure |
| `WavePersistentlyFailing` | `L5.dispatch.E_WAVE_PERSISTENTLY_FAILING` | manager after 3+ cross-engine retries fail |

## Exit-code mapping (for CLI)

- L1, L2 → exit 0
- L3 → exit 1
- L4 → exit 3
- L5 → exit 4
- Click usage errors → exit 2 (reserved)

## JSONL log integration (Wave A.6)

The closed-schema JSONL log gains two optional fields: `error_level: int|None`, `error_code: str|None`. Schema version bumps from 1 → 2. Old records (v1) remain valid.

## Operator-readable notification

Whenever an L4 or L5 is raised, the writer also appends a one-line summary to `coord/dev_loop/escalations.md`:

```
[2026-05-20T05:00:00Z] L5.secrets.E_DPAPI_UNREADABLE — DPAPI store cannot be decrypted on machine MASTER. Operator: re-encrypt secrets via `harness env --reset-dpapi`. Retry every 1h.
```

This is the file the operator reads to know what's wrong. It's always current; the manager rewrites it each tick.

## Open questions for later waves

- Should L4 also surface to the operator on first occurrence (with retry), or stay autonomous? Currently: autonomous, surfaces only if persistent.
- Internationalization of messages: deferred until/unless we ship to non-English operators.
