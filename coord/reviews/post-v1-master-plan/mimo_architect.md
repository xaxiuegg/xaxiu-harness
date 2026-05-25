### Stance summary (3-5 sentences)

v1.0.0 shipped with strong surface-level observability (audit trail, engine health probes) but left all internal data contracts implicit—`STATUS.csv` format, engine health probe JSONL schema, and audit log entries are free-form text without versioning. This will create silent breakage on the first structural change. The single most load-bearing abstraction to protect is the data interchange format between CLI and human-maintained coordination files; it's currently fragile string parsing where it should be a validated schema.

### Top 3 rows to ship next (ranked)

**1. W14-SCHEMA-VERSIONING**
- **Title**: Add versioned schema headers to all state files (`STATUS.csv`, `engine_health_probes.jsonl`, `audit.jsonl`) with validation on read/write
- **Estimated effort**: M (4-5h)
- **Why this row, by YOUR lens**: The three core state files (`coord/STATUS.csv`, `state/engine_health_probes.jsonl`, `~/.harness/audit.jsonl`) are the coordination backbone. Their formats are currently implicit string parsing—if any column order, header name, or JSON structure changes, all downstream consumers break silently. This is the single highest-risk abstraction debt. Versioning now prevents cascade failures when you inevitably evolve these formats.
- **Acceptance criteria**:
  - All three files have a mandatory `schema_version` header/first-field
  - `STATUS.csv` header row includes `schema_version:v1` plus column definitions
  - JSONL files validate `schema_version` on read; unknown versions raise `SchemaVersionError` with upgrade instructions
  - `harness doctor --check-schemas` verifies all state files match expected versions
  - 15+ tests covering version validation, missing version, and future-version rejection

**2. W14-ENGINE-HEALTH-PROMOTE**
- **Title**: Make engine health the single source of truth for dispatch routing decisions
- **Estimated effort**: S (2-3h)
- **Why this row, by YOUR lens**: The current dispatch path (`cli_helpers.py`) and engine health visibility (`W13-ENGINE-FAILURE-VISIBILITY`) are two separate data flows that should be one. Health probe results already live in `state/engine_health_probes.jsonl`, but dispatch doesn't read them—it re-probes via `SUPPORTED_BACKENDS` every time. Promoting health data to the routing decision point collapses two abstractions into one and removes the duplicate probe logic.
- **Acceptance criteria**:
  - `probe_engine_live()` populates a `last_known_status` field in `state/engine_registry.json` (new file)
  - `dispatch()` checks `engine_registry.json` before probing; only re-probes if last check > 5min old
  - `harness engines --health` reads registry first, falls back to live probe if registry missing
  - No duplicate probe logic between `cli_helpers.py` and `transport.py`
  - 10+ tests covering registry cache behavior, stale-cache fallback, and concurrent probe safety

**3. W15-BACKUP-SECRETS-REDACT**
- **Title**: Redact secrets from backup tarballs during `harness backup create`
- **Estimated effort**: M (3-4h)
- **Why this row, by YOUR lens**: This is a structural safety property, not a feature. The backup tarball is a serialized representation of the entire coordination state. If it contains API keys (from env snapshots, logs, or state files), restoring it on another machine leaks credentials. Redaction must happen at serialization time (backup), not deserialization time (restore). The existing 7-pattern redaction from W13-AUDIT-JSONL should be the single redaction library used everywhere.
- **Acceptance criteria**:
  - `harness backup create` runs all state files through the existing `redact_for_audit()` 7-pattern filter before tarball inclusion
  - Backup metadata includes `redacted: true` flag and `patterns_applied: [...]` list
  - `harness backup restore` validates redaction flag exists before unpacking
  - 8+ tests covering each of the 7 patterns + a "no redaction applied" failure case

### Rows you'd DROP from CURRENT_PLAN.md's Week 2/Week 3 sections

**1. Auto-default guardrail CI framework (Week 2)**
- **Why drop**: This is a testing methodology concern, not a structural one. The existing `W13-AUDIT-JSONL` already provides the audit trail for auto-defaults. Adding a CI framework before solidifying the data contracts it would depend on is premature. Ship this after schema versioning is in place.

**2. Hallucination test harness (Week 3)**
- **Why drop**: This is a feature-level testing tool, not structural debt. The harness's core coordination files and engine health data flows are more urgent to solidify. Defer until after W14-ENGINE-HEALTH-PROMOTE.

### Single most important action this week

Freeze the `STATUS.csv` schema with a `schema_version:v1` header and add validation to all read/write paths—this prevents the first structural change from becoming a silent cascade failure.

### Confidence in your own recommendation (0.7)

Schema versioning is unambiguously load-bearing, but the exact scope (which files, which patterns) needs validation against actual usage patterns I haven't observed directly.

### What this lens systematically MISSES

I'm optimizing for structural durability over operator-facing velocity—other lenses should verify these refactors don't block the Kimi auth recovery or the backup integrity work that DeepSeek flagged as immediate.