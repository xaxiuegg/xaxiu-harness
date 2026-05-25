### D5-cross-cutting-concerns — Strategic Forward Plan

---

## 1. Lens-specific findings

| # | Concern | Verbatim evidence from source pack | Risk level |
|---|---------|-----------------------------------|------------|
| **S1** | **Backup encryption** — shipped `W13-BACKUP-RESTORE` packs `.harness/` which *likely contains API keys* (`.env` is excluded by design, but dispatch cache may contain key-bearing prompts, and `state/` may hold session tokens). | *From horizon-c plan: `"W13-BACKUP-RESTORE snaps .harness/ which likely contains API keys. The plan does not discuss encryption at rest or in transit."`* | **HIGH** — if the laptop is lost or the backup archive is exfiltrated, API keys are plaintext. |
| **S2** | **Secrets in audit-jsonl** — planned `W13-AUDIT-JSONL` will log every dispatch call. If it logs raw prompts or error excerpts that contain API keys, the audit trail becomes a leak vector. | *The bloat audit lists `W13-AUDIT-JSONL` as a row to ship, but no mention of secret redaction in the source pack.* | **MEDIUM** — could be mitigated cheaply by stripping secrets before writing. |
| **S3** | **Plugin code-injection** — Wave 15 plugin architecture as described allows arbitrary Python files in `plugins/lenses/`. For an internal tool with trusted authors the risk is lower, but a collaborator or corrupted clone could introduce malicious code. | *From horizon-c plan: `"Allowing arbitrary Python files in plugins/lenses/ opens a code-injection vector if a collaborator uses a malicious plugin. No sandbox or signature verification mentioned."`* | **LOW** (internal tool) → **MEDIUM** (if collaborators) — needs a decision document, but actual sandboxing is overkill for a single-operator tool. |
| **S4** | **VPS-to-laptop reachability** — Wave 17 plans a VPS observer that pings the laptop. This assumes the laptop has a public IP / VPN, which is often false. | *From horizon-c plan: `"W17-VPS-OBSERVER suggests the VPS pings the laptop. This implies the laptop must be reachable (public IP / VPN) – often not the case. Also pinging from a public VPS to a private laptop may be blocked by NAT/firewalls."`* | **MEDIUM** (if VPS is used) — need to decide before Wave 17. |
| **P1** | **Performance: auto-snapshot blocking** — Shift B (`auto-snapshot backup before coord run`) could block the dispatch if implemented synchronously. | *Bloat audit Part 5 Tier 2 Shift B: `"Auto-snapshot backup before coord run or other high-write ops"` without specifying async.* | **MEDIUM** — if done synchronously, backup of `.harness/dispatched/` (potentially hundreds of MB) could block dispatches for seconds. |
| **P2** | **Performance: cost-cap pre-check latency** — Shift I (`cost-cap pre-check (estimate cost; warn if would exceed budget)`) adds an extra computation before every dispatch. If it requires an API call or file I/O, it could add 100ms+ to each dispatch. | *Bloat audit Part 5 Tier 2 Shift I: `"Cost-cap pre-check (estimate cost; warn if would exceed budget)"` with effort 1-2h.* | **LOW** — estimate can be purely local (prompt length × known cost/ token). Must be verified to add <10ms. |
| **M1** | **Maintainability: debugging auto-defaults** — The "visible, overridable, auditable" trio from the bloat audit is good, but `W13-AUDIT-JSONL` (the audit log) is **not yet shipped**. Auto-defaults shipped before audit will be invisible to future-debugging. | *Bloat audit Part 5: `"Without these, auto-defaults become hidden behavior the operator can't reason about – WORSE than operator burden. 1. Visible: log it. 2. Overridable: explicit flag wins. 3. Auditable: write to the W13-AUDIT-JSONL ledger (when it ships)."`* | **HIGH** — shipping auto-defaults (e.g., auto-pick lens-set from extension) before the audit log is operational creates invisible behavior. |
| **M2** | **Maintainability: future-as-present docs** — `INTERNAL_OPERATOR_RUNBOOK` describes `harness secrets rotate kimi` which **does not exist**. Future Claude sessions will attempt it and fail. | *Bloat audit Part 2: `"Future-as-present in docs – runbook describes harness secrets rotate kimi (doesn't exist)."` And the runbook itself contains Section 2a "After W13-SECRETS-ROTATION ships".* | **HIGH** — immediate hallucination risk; fix is trivial. |
| **C1** | **Compatibility with W11_E2E_SDK_PROOF** — The E2E proof validated the SDK with specific defaults (`context-frugal`, `fallback chain`, `max_tokens`). Adding new auto-defaults (such as auto-pick engine based on file extension) could create a path that was not tested. | *AGENT_QUICKSTART references `coord/coverage/W11_E2E_SDK_PROOF.md` as validated; the proof used explicit engine selection, not auto-pick.* | **MEDIUM** — must re-run the proof after any auto-default change. |

---

## 2. Recommended SHIP list (top 4 rows to do FIRST)

Given the operator's limited time (1-3h evening + 5h weekend), I recommend shipping these four items **in this order**. They close the most critical cross-cutting gaps and enable safe future work.

| Row | Why this must ship FIRST |
|-----|--------------------------|
| **W13-BACKUP-ENCRYPTION** (S, 3-4h) | Without encryption, the shipped backup is a plaintext archive containing likely API keys. This is the **single most dangerous open security hole**. Ship it before relying on backup for recovery. |
| **W13-AUDIT-JSONL with secret sanitization** (S, 2h + 1h for sanitization logic) | The audit log is the **foundation for maintainability** (tracing auto-defaults, debugging errors). Must include secret redaction (strip `KIMI_API_KEY=...` and similar patterns from any logged content). Without it, every audit entry is a potential leak. |
| **Future-as-present fix on INTERNAL_OPERATOR_RUNBOOK** (XS, 30min) | Prefix `FUTURE:` on `harness secrets rotate`, `harness engines quarantine`, and any other command not yet implemented. Prevents wasted cycles and operator confusion. Effort is negligible; payoff immediate. |
| **Cost-cap pre-check (Shift I)** (S, 1-2h) | Prevents accidental budget overrun (especially important when Best-of-N or high-`max_tokens` dispatches are used). Implement as a local static estimate (prompt length × known $/token) with <10ms overhead. Ship before W14 Best-of-N work. |

**Rationale for ordering**: Encryption first closes a security hole, audit log enables maintainability, doc fix prevents hallucinations, cost-cap protects budget. These four are bounded to ~8h total—achievable over the weekend.

---

## 3. Recommended DROP list (top 3 rows to NOT do)

| Row | Why it should be dropped (or indefinitely deferred) |
|-----|------------------------------------------------------|
| **W13-PLUGIN-SANDBOX-PLAN** | An internal tool with a single operator (and possibly trusted collaborators) does not need a formal sandbox. The risk of malicious plugins is dwarfed by the cost of implementing and maintaining a sandbox. Instead, document *"only load plugins from trusted sources"* in the plugin guide. **Drop the decision row; add a one-liner to Wave 15 docs.** |
| **W13-VPS-OBSERVER-NAT-PLAN** | VPS hardening is Wave 17 (at least 6 months out). Deciding on polling vs. webhook now is premature – the operator has no VPS deployment yet. **Defer** until Wave 17 is actually scheduled. The current `W13-VPS-OBSERVER-NAT-PLAN` row consumes mindshare now for a decision that won't be executed for months. |
| **W14-BEST-OF-N-COST-CAP** | The cost-cap pre-check (Shift I, recommended above) already provides a generic budget guard. The Best-of-N specific multiplier logic is duplicative until Best-of-N itself is built. **Drop** the separate row; fold a one-line note into the Shift I implementation that warns when a dispatch would consume >10% of remaining budget. |

---

## 4. Recommended ADD list (top 2 NEW rows)

| Row | Pitch | Effort | Why |
|-----|-------|--------|-----|
| **W13-AUDIT-SECRET-SANITIZE** | Add a secret-stripping step to the audit JSONL writer that removes any line matching `(KIMI\|DEEPSEEK\|MIMO\|ANTHROPIC\|GEMINI)_API_KEY=...` from logged prompts and error excerpts. Add a test that verifies a key is not written to the log. | **XS (1h)** | Without this, the audit JSONL becomes a liability; with it, it's safe to use for debugging. |
| **W13-CONFIG-SHOW-VERB** | Implement `harness config show` that prints all current effective defaults (env vars, auto-defaults, override flags, budget cap, etc.) in a single readable table. | **S (1h)** | Solves the "I can't figure out why this auto-default kicked in" problem. Ships before any auto-defaults go live. Pairs with the audit log to cover the maintainability gap. |

---

## 5. Single most important recommendation

**Ship `W13-BACKUP-ENCRYPTION` and `W13-AUDIT-JSONL` (with secret sanitization) this weekend—the backup without encryption and the audit log without redaction are time bombs for the internal tool's reliability and security, and both are cheap to fix before the operator depends on either.**