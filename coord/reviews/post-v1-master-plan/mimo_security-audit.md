### Stance summary

The v1.0.0 audit ledger (`audit.jsonl`) is a reactive log of dispatched calls—it tells you what you asked engines to do, not what engines did to you. The Kimi termination event proves we lack a *proactive, tamper-evident* record of engine-side access control state. When a vendor terminates access or a key leaks, our audit trail should contain the proof of the event, not just our outbound requests. The single highest-leverage property to strengthen is **log immutability and completeness**—the audit trail must be cryptographically verifiable and capture engine-side health events, not just ours.

### Top 3 rows to ship next (ranked)

1.  **Row ID**: `W14-AUDIT-CHAIN-HMAC`
    **Title**: HMAC-chain the audit.jsonl ledger for tamper evidence
    **Estimated effort**: M (3-4h)
    **Why this row, by YOUR lens**: A forensic audit trail is worthless if entries can be silently deleted or altered after the fact. The current `audit.jsonl` has no integrity mechanism. An HMAC chain (each row's hash depends on the previous) provides cryptographic proof of completeness and ordering. This is the foundation for all other security claims—if a subpoena hits or we need to prove a vendor terminated access *after* a certain date, we need an unforgeable timeline.
    **Acceptance criteria**:
    - Each new row appended to `audit.jsonl` includes a `hmac` field computed from the previous row's HMAC and the current row's data (excluding the hmac field itself).
    - A `harness audit verify` command replays the chain from the first row and reports the first row where the HMAC fails.
    - A `harness audit anchor` command exports the current chain head (row count + final HMAC) to a signed file for external storage.
    - All existing audit-writing paths (`dispatch()`, `probe_engine_live()`) use the new chaining logic.
    - 10+ tests cover correct chaining, verification failure on row insertion/deletion/modification, and anchor export.

2.  **Row ID**: `W14-PROBE-LOG-APPEND`
    **Title**: Append live engine-health probes to the main audit ledger
    **Estimated effort**: S (1-2h)
    **Why this row, by YOUR lens**: The `W13-ENGINE-FAILURE-VISIBILITY` probe writes to a separate file (`state/engine_health_probes.jsonl`), creating an audit blind spot. The Kimi termination *is* an auditable event—it should be in the primary ledger, chained. Splitting logs by event type forces anyone doing an investigation to correlate two timelines. All machine-state-change events belong in the single, immutable audit trail.
    **Acceptance criteria**:
    - `probe_engine_live()` and `probe_all_engines_live()` write their results to the main `~/.harness/audit.jsonl` file, not a separate file.
    - The log entry has a clear `event_type` (e.g., `engine_health_probe`) so queries can filter.
    - The entry includes the redacted error body from transport.py (e.g., `HTTP 403: {"error":...}`).
    - The existing `state/engine_health_probes.jsonl` file becomes a deprecated symlink or is removed.
    - `harness engines failures` now queries the main audit ledger via event_type filter.

3.  **Row ID**: `W14-BACKUP-PREFLIGHT-SCAN`
    **Title**: Pre-backup scan for high-entropy strings and API key patterns
    **Estimated effort**: S (1-2h)
    **Why this row, by YOUR lens**: `W13-BACKUP-SECRETS-REDACT` redacts *after* the fact. A pre-scan that *fails the backup* if high-entropy strings (likely API keys) or known key prefixes (`sk-`, `tp-`, `AIza`) are found in tracked files is a stronger control. It prevents the leak from ever entering the backup tarball, rather than trying to scrub it later. This is the principle of catching violations at the source.
    **Acceptance criteria**:
    - A new function `secrets_scan_directory(path)` uses regex and entropy checks on text files.
    - `harness backup create` calls this scan on the working directory. If secrets are found, it aborts with a list of suspicious files (file paths, line numbers, redacted secret snippets).
    - A `--force` flag allows bypassing the scan after a warning.
    - CI runs the scan on the repo to ensure our own codebase is clean.
    - Tests cover detection of keys, high-entropy strings, and safe bypass.

### Rows you'd DROP from CURRENT_PLAN.md's Week 2/Week 3 sections

- **Row**: Schema versioning (Week 3)
  **Why drop**: This is a feature-lifecycle concern, not a security or auditability concern. It does not reduce blast radius or improve forensic capability. Ship it only when a breaking change is actually imminent.

- **Row**: `harness commands --did-you-mean` (Week 3)
  **Why drop**: Usability polish with zero security or audit impact. Consumes development time that should be spent on log integrity and secret-leak prevention.

### Single most important action this week

Implement HMAC-chaining on `audit.jsonl` (`W14-AUDIT-CHAIN-HMAC`) before shipping any other work—the entire security posture depends on an immutable, verifiable log.

### Confidence in your own recommendation (0.0-1.0)

**0.95**. The Kimi termination is a concrete, recent incident that directly validates the need for a tamper-evident, complete audit trail. The only thing that would lower my confidence is if a simpler, equally robust method for log integrity were already built into the filesystem or a dependency we're using, but standard approaches (like simple append-only files) do not provide cryptographic proof.

### What this lens systematically MISSES

This lens is blind to **operator experience and velocity**—it would approve complex cryptographic logging systems that might make a solo operator's daily workflow cumbersome or confusing. The "visible/overridable" part of the operator's directive could be sacrificed by an overly paranoid audit design.