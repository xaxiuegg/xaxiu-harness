<!-- persona=P2-dependency-mapper status=OK (25774ms) -->

# P2-dependency-mapper

## Dependency Map for W11 Agent-First Rows

| Row | Depends On | Enables | Shared Write-Set |
|-----|------------|---------|------------------|
| **W11-AGENT-INIT-VERB** | Existing: `scaffold_adapter`, `advisory_lock`, `atomic_write_json` | W11-DPAPI-CROSS-PLATFORM, W11-CLAUDE-MD-TEMPLATE, W11-PYTHON-SDK-API (indirect), W11-DISPATCH-CACHE (uses .harness dir) | `.harness/` state dir, `.env`, `CLAUDE.md`, adapter files |
| **W11-DPAPI-CROSS-PLATFORM** | W11-AGENT-INIT-VERB (needs project root), Existing: `dpapi.encrypt_secret`, `has_secret` | W11-AGENT-TELEMETRY (secrets for budget?) | `.env` (adds secrets section) |
| **W11-CLAUDE-MD-TEMPLATE** | W11-AGENT-INIT-VERB (needs project type detection) | W11-AGENT-INIT-VERB (template selection) | `CLAUDE.md` (template content) |
| **W11-PYTHON-SDK-API** | W11-CONTEXT-FRUGAL-RETURN, W11-AGENT-TELEMETRY, W11-RETRIEVE-API (stubs), Existing: `dispatch_packet`, `budget_status` | Downstream tooling (but not in this list) | Type stubs (`harness/__init__.pyi`) |
| **W11-CONTEXT-FRUGAL-RETURN** | W11-DISPATCH-CACHE (lazy fetch), Existing: `dispatch_packet` | W11-PYTHON-SDK-API, W11-RETRIEVE-API | `harness/engines/result.py` (core class), `.harness/dispatched/` (content refs) |
| **W11-DISPATCH-CACHE** | W11-AGENT-INIT-VERB (`.harness/` dir), Existing: `atomic_write_json`, `advisory_lock` | W11-CONTEXT-FRUGAL-RETURN, W11-RETRIEVE-API | `.harness/dispatched/` (cache files) |
| **W11-RETRIEVE-API** | W11-CONTEXT-FRUGAL-RETURN, W11-DISPATCH-CACHE, Existing: `dispatch_packet` | W11-PYTHON-SDK-API | `harness/retrieve.py` (new module) |
| **W11-AGENT-TELEMETRY** | W11-DPAPI-CROSS-PLATFORM? (offload_ratio?), Existing: `record_dispatch`, engine analytics | W11-PYTHON-SDK-API (budget_status) | `harness/budget/` (possibly updated schema) |
| **W11-CROSS-PLATFORM-OBSERVER** | Existing: observer logic, platform detection | W11-OBSERVER-WATCHDOG-RECOVERY | Observer configuration files (e.g. `.harness/observer.yml`) |
| **W11-ADAPTER-VALIDATE-JSON** | Existing: adapter validation | W11-L5-OUTPUT-CONTRACT (format dependency) | stdout only (no file conflicts) |
| **W11-HIDE-ADVANCED-VERBS** | Existing: CLI argparse | None (decoupling) | CLI help strings |
| **W11-L5-OUTPUT-CONTRACT** | W11-ADAPTER-VALIDATE-JSON (one use case), Existing: CLI output | None directly | Output formatting code |
| **W11-OBSERVER-WATCHDOG-RECOVERY** | W11-CROSS-PLATFORM-OBSERVER | None | Watchdog state files (`.harness/watchdog/`) |
| **W11-PER-CHECK-LATENCY-OBSERVABILITY** | Existing: check infra | None | Metrics files / log |
| **W11-MUTATION-PATTERN-EXPANSION** | Existing: mutation canary | None | Mutation config |
| **W11-AUDIT-ALL-W10-ROWS** | None (independent) | None | N/A (read-only audit) |

### Key Findings

- **Circular dependencies**: None detected. Strong DAG with W11-AGENT-INIT-VERB as root.
- **Hidden ordering**: W11-DPAPI-CROSS-PLATFORM and W11-CLAUDE-MD-TEMPLATE both assume AGENT-INIT-VERB has run. W11-PYTHON-SDK-API must wait for CONTEXT-FRUGAL-RETURN, RETRIEVE-API, and AGENT-TELEMETRY.
- **Serialization bottlenecks**: `.harness/` directory is written by AGENT-INIT-VERB, DISPATCH-CACHE, OBSERVER, and WATCHDOG. Only AGENT-INIT-VERB should be serialized first; others can be parallelized if directory exists.
- **Parallelization candidates**: W11-ADAPTER-VALIDATE-JSON (no file writes) can run any time. W11-AUDIT-ALL-W10-ROWS, W11-HIDE-ADVANCED-VERBS, W11-MUTATION-PATTERN-EXPANSION are independent of new rows.

## Two Open Questions

1. **W11-AGENT-INIT-VERB should be the first shipped row** — does the operator want to deliver it as a minimal working verb before any SDK or telemetry work begins, or do they prefer a parallel start on DPAPI and templates (which would require init to be stubbed)?

2. **W11-PYTHON-SDK-API type stubs will be invalidated if CONTEXT-FRUGAL-RETURN or RETRIEVE-API change return types.** Should the stubs be written last (after those rows stabilize), or is an explicit “stub-as-contract” approach preferred where stubs are written first as a spec?

## Alignment Check

The current wave ordering (A→B→C) is correct for the dependency tree. However, **W11-ADAPTER-VALIDATE-JSON** (Wave 11-C) could be moved to any time since it has no file conflicts and no dependencies on other new rows — moving it earlier would give quick user-visible improvement. Similarly, the six hygiene rows are all independent and could be interleaved with Wave 11-A/B without blocking. **W11-OBSERVER-WATCHDOG-RECOVERY** should not ship before **W11-CROSS-PLATFORM-OBSERVER**, but both are self-contained after AGENT-INIT-VERB. Merge suggestion: combine W11-PYTHON-SDK-API and W11-AGENT-TELEMETRY into a single “SDK surface” row to reduce cross-file coordination.
