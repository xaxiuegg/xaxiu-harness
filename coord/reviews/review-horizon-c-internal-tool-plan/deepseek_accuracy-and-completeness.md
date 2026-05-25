Here’s a fact‑check, completeness review, and flagging of dubious assertions in the plan document.

---

## 1. Assertions about current state of the tool

| Assertion | Dubious? | Rationale |
|-----------|----------|-----------|
| *“Today: Kimi + DeepSeek + MiMo + Anthropic + Gemini (last two not in active rotation).”* | ⚠️ **Unverifiable without codebase access** | The plan claims a specific set of engines and their status. Even if based on a real session, we cannot confirm the actual implementation. |
| *“Gemini … currently stub”* | ⚠️ **Same unverifiability** | Plausible, but it’s an assertion about existing code. |
| *“harness.dispatch call appends to `~/.harness/audit.jsonl`”* | ⚠️ **Not yet implemented** (part of W13-AUDIT-JSONL) | The plan says this is a future work item; calling it “every dispatch call” is hypothetical. |

**Verdict**: All claims about the tool’s current capabilities should be marked as **unverified assumptions** – they rely on the document’s internal consistency, not on actual source code.

---

## 2. Effort estimates and sequencing

| Assertion | Dubious? | Rationale |
|-----------|----------|-----------|
| *“Wave 13 — Operations Foundation (~30‑40h)”* | ⚠️ **Opinion, not fact** | Estimates are highly subjective; actual time depends on code complexity, test infrastructure, and operator skill. |
| *“W13-BACKUP-RESTORE … M, 4‑5h”* | ⚠️ **Unvalidated** | No justification given. Could be 10x if corner cases (concurrent writes, encryption) are handled properly. |
| *“Total estimated effort: 200‑400h … 12‑25 weeks part‑time”* | ⚠️ **Rough guess, not a promise** | The plan itself states “depending on which waves apply”. The lower bound (200h) is likely optimistic if any wave hits complications. |
| *“Wave 15 — Plugin Architecture (~40‑60h)”* | ⚠️ **Very aggressive** | Freezing an ABI, refactoring 5 engines into a plugin pattern, plus testing, often takes 50‑100h. |

**Verdict**: All effort estimates are **speculative** and should be treated as rough planning guidelines, not commitments. Missing caveat: **developer‑unfamiliarity with the existing codebase** can multiply these times by 2‑3x.

---

## 3. Command examples – are they correct and runnable?

| Example in plan | Correct? Runable? |
|----------------|-------------------|
| `harness backup` | ❌ **Not a real command** (part of W13‑BACKUP‑RESTORE – not implemented) |
| `harness restore <archive>` | ❌ Same as above |
| `harness secrets rotate kimi` | ❌ **Not implemented** (W13‑SECRETS‑ROTATION) |
| `harness review --lens-set <name>` | ❌ Relies on W15‑LENS‑PLUGIN |
| `harness user create <name>` | ❌ Relies on W16‑USER‑CREATE |
| `bin/deploy-harness.sh <vps>` | ❌ Not implemented |
| `bin/rollback-harness.sh <vps>` | ❌ Not implemented |

**Verdict**: **None of the commands listed are currently runnable** – they are all targets for future waves. The document does not claim they exist now, but the phrasing (e.g., “harness.dispatch call appends to …”) might mislead a reader into thinking the audit feature already works. **This should be flagged as a communication risk.**

---

## 4. Missing critical caveats / failure modes

### 4.1. Technical risks not addressed in the plan
- **API cost explosion**: “Best‑of‑N” (W14) dispatches to multiple engines concurrently – could multiply costs by N per query, with no mention of cost caps.
- **CI drift gate with real API calls**: W13‑CI‑DRIFT‑GATE suggests weekly real calls to all engines. This **introduces ongoing cost, rate‑limit risk, and flaky CI** (engines may be temporarily down). A stub test would be safer.
- **Backup encryption & secrets**: W13‑BACKUP‑RESTORE snaps `.harness/` which likely contains API keys. The plan does not discuss encryption at rest or in transit.
- **Plugin security**: Allowing arbitrary Python files in `plugins/lenses/` opens a code‑injection vector if a collaborator uses a malicious plugin. No sandbox or signature verification mentioned.
- **VPS observer pinging the operator’s laptop**: W17‑VPS‑OBSERVER suggests the VPS pings the laptop. This implies the laptop must be reachable (public IP / VPN) – often not the case. Also, pinging from a public VPS to a private laptop may be blocked by NAT/firewalls.
- **Secrets rotation procedure**: W13‑SECRETS‑ROTATION says “updates .env + DPAPI”. DPAPI is Windows‑specific; the plan assumes the operator runs on Windows. If the harness runs on Linux/macOS, this feature is irrelevant or misleading.
- **No mention of versioning for plugin API**: The ABI freeze (W15) can break if the main codebase changes later. Plugin docs must specify compatibility guarantees.
- **Per‑user budget caps on a shared VPS**: W16 assumes the operator trusts the VPS security. If the VPS is compromised, all audit data and API keys are exposed.

### 4.2. Human / organizational risks
- **Operator burnout**: Mentioned as “higher”, but no mitigation beyond runbook. No mention of delegation, automation, or acceptable failure thresholds.
- **“Key‑person dependency”**: The plan acknowledges this but only suggests runbook + lock deps. Real mitigation would require reproducible environment (Docker, Nix) and tested restore scripts – not just a markdown file.
- **Assumption that the operator will actually implement all waves**: No discussion of what happens if the operator loses interest or time after Wave 13. The plan implies the waves are independent, but many depend on earlier work.

### 4.3. Business / external risks
- **Engine API deprecation or pricing change**: The plan addresses drift via CI, but not sudden shutdown (e.g., DeepSeek discontinues free tier). The local llama fallback helps, but the plan assumes that will be built.
- **Legal/compliance**: Using multiple LLM APIs for client work may require data handling agreements (e.g., GDPR, HIPAA). The plan does not mention any compliance checks.
- **Operator’s client work may require confidentiality**: The audit JSONL logs all dispatch data – could accidentally leak sensitive content. No mention of audit data retention policy or anonymization.

---

## 5. Dubious or inconsistent claims

| Claim | Issue |
|-------|-------|
| *“Original Horizon C … Estimated 600‑1000h.”* | No reference to how that estimate was derived. Likely pulled from previous conversations. Flag as **unsubstantiated baseline**. |
| *“2026‑05‑25 operator directive”* | Date is in the future (as of 2025). Possibly a typo or placeholder. **Should be flagged** – either irrelevant or an error. |
| *“W13‑OPERATOR‑RUNBOOK … S, 3h”* | Writing a comprehensive runbook for “laptop died / key rotated / engine down / restore‑from‑backup” can easily take 6‑10h (including testing the steps). Underestimating. |
| *“W13‑INSTALL‑VERIFY … E2E test that `git clone + pip install -e . + harness review <doc>` works on a clean Windows shell … M, 3‑4h”* | Setting up a clean Windows shell (VM or container) and writing a full E2E test often takes 1‑2 days. This effort is **grossly understated** if done properly. |
| *“W14‑ENGINE‑HEALTH‑FORECAST … predict engine failure from latency trends + cooldown history … M, 4‑5h”* | Predictive health forecasting is a non‑trivial machine learning / anomaly detection feature. 4‑5h is **utterly unrealistic** even for a simple heuristic. |
| *“W16‑TEAM‑DASHBOARD … dashboard view … M, 5‑6h”* | A useful dashboard with user attribution, masking, and cost breakdown typically takes 20‑40h (including frontend, backend, and UX). |

**Verdict**: Many effort estimates are **implausibly low**, suggesting the plan is optimistic and doesn’t account for testing, documentation, debugging, and iteration.

---

## 6. Completeness gaps

### 6.1. Missing wave items that the plan acknowledges but doesn’t schedule
- **Testing each wave** – only W15‑CONTRIB‑TESTS is mentioned; no unit/integration test plans for backup, secrets rotation, plugin ABI, etc.
- **Documentation for non‑operator collaborators** – W15‑PLUGIN‑DOCS is for adding engines, but no user guide for team members (W16).
- **Monitoring / alerting** – observer is mentioned for VPS, but not for budget overruns, engine failure, or backup failures.

### 6.2. Implicit dependencies not listed
- W13‑BACKUP‑RESTORE may depend on a stable ledger format (could be broken by later waves).
- W15‑PLUGIN‑ARCHITECTURE requires a clear interface for engines – if the current engine code has tight coupling, refactoring will take far longer than 12‑15h.
- W16‑PER‑USER‑LEDGER depends on having a multi‑user user store (W16‑USER‑CREATE) – logical, but the plan doesn’t say that.

### 6.3. No rollback plan for the plan itself
- If the operator starts Wave 13 and gets sidetracked, the plan provides no guidance on how to stop or pivot. A realistic internal tool plan should include a **stop‑loss condition** (e.g., “if after 50h the backup system isn’t working, reassess”).

---

## 7. Overall assessment

- **Accuracy**: The factual assertions about the tool’s current state cannot be verified. Effort estimates are **unrealistically low** in several cases. The plan is a reasonable starting sketch but should not be taken as a reliable budget or schedule.
- **Completeness**: The plan covers many important operational areas (backup, secrets, disk pruning, engine variety) but **misses critical security, cost control, and testing considerations**.
- **Runnable examples**: None of the command examples exist yet; they are aspirational.
- **Critical caveats**: The plan does not adequately address cost blow‑up from multi‑engine dispatch, encryption of backups, platform‑specific secrets handling, or the risk of the operator not finishing the waves.

**Flags for every dubious assertion** have been marked in the tables above. The most egregious ones are:
- W14‑ENGINE‑HEALTH‑FORECAST at 4‑5h.
- W16‑TEAM‑DASHBOARD at 5‑6h.
- W13‑INSTALL‑VERIFY at 3‑4h.
- The assumption that all waves will be implemented as described.

**Recommendation**: Before following this plan, the operator should:
1. **Validate current tool state** (document which engines actually work).
2. **Timebox each wave with a hard budget** (e.g., Wave 13 gets no more than 50h).
3. **Add explicit security and cost guardrails** for multi‑engine dispatch and backup storage.
4. **Reduce scope** – prioritize only the items that protect against the most likely catastrophic failure (backup, secrets rotation, disk pruning). Defer engine health forecasting and team dashboard indefinitely.