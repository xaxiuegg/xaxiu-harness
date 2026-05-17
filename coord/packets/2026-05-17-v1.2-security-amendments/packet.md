# Packet: xaxiu-harness v1.2 Spec Amendment — Security Hardening

## Mission
Produce `D:/Projects/xaxiu-harness/spec/v1.2-security-amendments.md` — a structured amendment document that resolves the 11 HIGH and 14 MED security findings from the spec audit (attached as context-file). Output is drop-in spec text that future implementer packets can reference directly.

## Context
A security audit of v1 (411 lines) + v1.1 (479 lines) identified 33 findings (11 HIGH / 14 MED / 8 LOW). Most are "spec is silent — requires explicit language before implementation"; several are concrete vulnerabilities visible in current spec text (NL→YAML prompt injection, unauthenticated WebSocket, scheduled_tasks command as arbitrary string, uninstall glob, etc.).

Wave 1 deliverables (schema.py, cli.py, engines/base.py) are already audited safe-to-proceed. But Wave 2 (dashboard, NL translator, installer, state layer, status backends) MUST be dispatched against amended specs that close these gaps.

## Required output structure — single markdown doc, target 300-500 lines

### Section 1: Amendment summary table
| Finding ID | Severity | Spec location amended | One-line description |
|---|---|---|---|
(All 25 HIGH+MED listed; LOW separately in Section 4)

### Section 2: Per-finding amendments

For EACH of the 11 HIGH findings AND each of the 14 MED findings, produce an entry of this form:

```
### Amendment for HIGH-N: [Finding title from audit]
**Original spec location:** v1 §X.Y (line ~NNN) and/or v1.1 §A.B (line ~MMM)
**Original text (quoted from spec):** "..."
**Replacement / insertion text:**

[Multi-line block containing the exact spec language to add to v1 or v1.1. Must be drop-in usable — implementer copies into the spec doc as-is. Use the same terse declarative voice as v1/v1.1.]

**Verification check:** [How implementer/CI confirms the implementation matches — typically a grep guard or unit test pattern. Be concrete: `! grep -rn 'yaml\\.load(' src/` not "use safe_load".]
```

### Section 3: Cross-cutting requirements
- **Port reconciliation**: pick ONE port (recommend 7878 per v1.1) and apply consistently. Specify which lines in v1 §3, v1 §5, v1.1 §1, v1.1 §5.2 to change.
- **CI guards**: explicit grep patterns CI must run. Minimum:
  - `! grep -rn 'yaml\.load(' src/ tests/`
  - `! grep -rn 'shell=True' src/`
  - `! grep -rn 'os\.environ\[' src/`
  - `! grep -rn 'host="0\.0\.0\.0"' src/`
  - `! grep -rnE 'execute\(["'"'"']\s*[A-Z]+.*\+' src/` (SQL string concat)
- **Constants file**: a single `src/harness/_constants.py` with `SUPPORTED_BACKENDS`, `API_KEY_ENV_VARS`, `DASHBOARD_PORT`, `DPAPI_FILE_NAME`, `DASHBOARD_TOKEN_FILE` — eliminates duplicate source-of-truth bugs (already noted as X-LOW-1 in deliverable audit).

### Section 4: LOW findings — Wave 2 backlog
List the 8 LOW findings as a backlog table; mark each as `defer-to-v1.3` or `address-in-wave-2-packet-X`. Provide one-sentence rationale.

### Section 5: Implementation order
Recommend the order in which Wave 2 packets should be dispatched, based on dependency chains established by the amendments. Example dependency: DPAPI secret-storage helper (HIGH-8) must land before NL translator (HIGH-6) and before engine concrete dispatch (Wave 2 engine implementation).

Suggested order (refine as needed):
1. `_constants.py` + DPAPI secrets helper
2. Adapter loader (`adapters/loader.py`) with mandatory `yaml.safe_load`
3. State layer (JSON + SQLite with parameterised queries baked in)
4. Engine concrete implementations (httpx calls + key-redacted logging)
5. Auto-fallback + closed-schema jsonl writer
6. Dashboard backend (FastAPI with auth token + loopback bind + CSRF)
7. WebSocket handler (auth + origin check + pydantic message validation)
8. NL→YAML translator (input sanitiser + post-LLM YAML-diff check)
9. Status backends (CSV first, markdown next; jira/linear deferred unless DPAPI extended)
10. Visual config builder (XSS-safe rendering)
11. Windows installer (signed, DPAPI integration, hash-verified bundle)
12. First-run wizard (no secrets in argv or logs)

## Critical constraints
1. **Every HIGH must have a concrete amendment.** No deferrals on HIGHs.
2. **Amendments must be drop-in usable spec text**, not abstract guidance. The implementer should be able to copy your "Replacement text" block into v1 or v1.1 verbatim.
3. Where the audit recommended specific implementation (e.g., DPAPI for HIGH-8, parameterised SQL for HIGH-11, X-Harness-Token for HIGH-2), encode that as MANDATORY spec language — not "consider using".
4. Reference exact line numbers from the audit when quoting original spec.
5. Use the same writing voice as v1/v1.1 (terse, declarative, no padding).
6. Do NOT introduce new design decisions beyond what the audit's "Fix recommendation" prescribes — your job is structured codification, not redesign.

## Reference
- Attached as `--context-file`: `D:/Projects/xaxiu-harness/security/audits/2026-05-17-spec-audit.md` (full audit with all 33 findings + fix recommendations)
- v1 spec at `D:/Projects/xaxiu-harness/spec/v1-architecture.md`
- v1.1 spec at `D:/Projects/xaxiu-harness/spec/v1.1-operator-experience.md`
