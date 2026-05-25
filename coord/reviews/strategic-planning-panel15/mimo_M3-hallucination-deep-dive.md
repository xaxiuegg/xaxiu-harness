### 1. Lens-specific findings

1.  **SDK Signature Drift as Silent Hallucination Vector**: The audit assumes SDK surface stability, but the Wave 15 plugin architecture (`W15-ENGINE-ABI`) will *change the ABI*. An agent relying on `harness.dispatch`'s current signature could silently fail or produce garbage after an update if the harness's own internal callers aren't updated in lockstep. This is a vector for "correct syntax, wrong behavior" hallucinations.

2.  **Config-Key Drift Between YAML Schemas**: The documents reference multiple config touchpoints (`.env`, engine settings, observer thresholds). There's no mention of a single source of truth for config keys. An agent or operator could invent a config key from memory (e.g., `max_retries` vs `retry_limit`) that exists in one schema but not another, leading to silent failure.

3.  **Engine-Model Coupling Hallucination**: The engine names (`kimi`, `deepseek`) are fixed, but the underlying models change (e.g., `deepseek-v4`). The bloat audit flags the *engine name* typo risk, but not the risk of an agent or operator conflating an engine with a specific model version and expecting model-specific behavior the adapter doesn't expose.

4.  **STATUS.csv Schema Migration Risk**: The audit mentions archiving rows but not schema evolution. If a new column (e.g., `user_id` from Wave 16) is added, the agent's parsing code could hallucinate that the column already exists for older rows, causing crashes or data corruption in reporting scripts.

5.  **Dispatch Cache Binary Format Coupling**: The `W13-DISK-PRUNE` and `W13-BACKUP-RESTORE` work will touch the `.harness/dispatched/` cache. If the serialization format (e.g., pickle version, JSON schema) changes between harness versions, a cache from v1 could cause hallucinated data or crashes when read by v2 after an update or restore.

6.  **Observer State Migration Hallucination**: The `W13-BACKUP-RESTORE` plan must handle observer state (flags, history). If the observer's internal state schema changes, restoring an old backup could load inconsistent state, causing the observer to make incorrect predictions or flag non-issues based on outdated patterns.

### 2. Recommended SHIP list (top 3-5 rows to do FIRST)

1.  **W13-AUDIT-JSONL** (S, 2h): **Why**: This is the foundational forensic tool. It creates the single source of truth for every dispatch, enabling diagnosis of all other vectors (signature drift, config drift, cache issues) by providing a ground-truth log of what was *actually* sent and received.

2.  **W13-BACKUP-RESTORE** (M, 4-5h): **Why**: This is the existential risk mitigation for the operator. However, it must be designed with **schema versioning** baked in from the start to avoid becoming its own hallucination vector (finding #4, #5, #6). Ship it as the "careful, version-aware backup."

3.  **W13-OPERATOR-RUNBOOK** (S, 3h): **Why**: Directly mitigates the "future-as-present" vector (#1 in audit) by providing a clear, present-tense manual. Should include a "Known Hallucinations" section listing the six audit vectors as explicit anti-patterns for the operator to check.

4.  **Mitigation ADD: SDK Schema Freeze Test** (effort S, 2h): **Why**: Before any ABI change (`W15-ENGINE-ABI`), add a CI test that fires a canonical dispatch and compares the output schema hash. This catches silent signature drift (finding #1) before it hits production.

### 3. Recommended DROP list (top 2-4 rows to NOT do)

1.  **W14-BEST-OF-N** (M, 4-5h): **Why**: This is a complexity multiplier for a solo internal tool operator. It increases cost, latency, and introduces a new "synthesis" layer that is ripe for hallucination. The goal is resilience via fallback, not speculative voting. Drop it now; revisit only if multi-engine consensus is a validated need after a year of use.

2.  **W15-REVIEW-TEMPLATE-PLUGIN** (M, 5-6h): **Why**: Over-engineering for an internal tool. The operator can already customize templates by editing Markdown files. A plugin system adds abstraction without solving a current pain point, creating a new config surface that can drift (finding #2).

3.  **W16-TEAM-DASHBOARD** (M, 5-6h): **Why**: Premature optimization. The operator works solo or with a tiny team. A dashboard is a feature for a product with 10+ users. The audit trail (`AUDIT-JSONL`) and per-user ledger (if needed) provide the same data in a more directly queryable format.

4.  **`harness whoami` (as a new verb)**: **Why**: It adds a verb to the CLI bloat. The same information can be surfaced by enhancing `harness today` or `harness preflight` with a "Current Capabilities" summary. Don't add a new verb for info that should be ambient.

### 4. Recommended ADD list (top 1-3 NEW rows worth adding)

1.  **W13-CONFIG-KEY-REGISTRY** (effort S, 2h): **Pitch**: A single `config_keys.toml` or section in the runbook that is the source of truth for all configuration key names (env vars, YAML keys). The CI doc-sync test (`Doc-doc-sync test` in audit) is updated to grep for these keys, catching invented or misspelled config keys. This directly mitigates finding #2.

2.  **W14-ENGINE-MODEL-MANIFEST** (effort S, 1h): **Pitch**: A `manifest.yaml` in the harness that maps each engine adapter to its current, underlying model identifier(s). `harness whoami` (or `harness today`) reads this. Prevents confusion between engine name and model version (finding #3). Effort is minimal—just a file and a display hook.

3.  **W15-SCHEMA-MIGRATION-TEST** (effort S, 2h): **Pitch**: A test harness for STATUS.csv and dispatch cache that loads sample data from the previous version, runs a migration, and validates the output against the new schema. Catches breaking changes in data formats (findings #4, #5) before they corrupt live data.

### 5. Single most important recommendation

**Instrument EVERY data structure (STATUS.csv, dispatch cache, observer state) with a schema version field from day one, and test migrations against the previous version in CI.** This turns future schema drift from a silent, hallucination-prone catastrophe into a controlled, testable upgrade process.