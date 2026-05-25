# Multi-engine review: horizon-c-internal-tool-plan.md

**Generated**: 2026-05-25T01:22Z
**Document**: `D:\xaxiu-harness-standalone\coord\reviews\horizon-c-internal-tool-plan.md`

**Lenses dispatched**:
- `audience-fit` via **mimo** (30s, 3369/1042 tokens, $0.0000) — OK
- `accuracy-and-completeness` via **deepseek** (34s, 3094/3377 tokens, $0.0000) — OK
- `clarity-and-structure` via **kimi** (118s, 3011/4599 tokens, $0.0000) — OK

**Total cost**: $0.0000 (3/3 engines succeeded)

---

## Per-lens reviews

### audience-fit (via mimo)

This internal planning document is well-crafted for a very specific audience: the **operator** (likely a senior developer or technical lead) who is building and maintaining this tool for their own team's daily work.  

**Why it fits that audience:**  
- The tone is direct, pragmatic, and familiar with the tool’s architecture and history (references to prior sessions, commits, known risks).  
- Technical jargon is used appropriately and assumed to be understood (“ABI,” “engine adapters,” “DPAPI,” “JSONL,” etc.).  
- Sequencing is framed around operational resilience, which is a priority for a solo maintainer or small internal team—not around scalability or public appeal.  
- The “what changes vs. original Horizon C” section is especially useful for someone who knows the prior roadmap and needs to justify the shift in priorities.  

**Potential misreads by other audiences:**  
- **Junior developers or new team members** might feel lost without more context on terms like “engine,” “lens-set,” or “dispatch cache.”  
- **Non-technical stakeholders** (e.g., a manager overseeing the tool) might miss the strategic intent behind the operational focus, seeing only a feature list.  
- **Open-source contributors** (if this were public) might be confused by the inward-facing language (“operator,” “the operator’s laptop”) and lack of community-oriented considerations.  

**What works well:**  
- The **risks table** brilliantly re-evaluates concerns from a public product vs. internal tool lens—something the primary audience will appreciate.  
- The **sequencing** is logical: stability and observability first, then scalability, then multi-user.  
- The **“what success looks like”** section grounds everything in practical, daily-use scenarios.  

**Suggestions to broaden readability (if needed):**  
1. Add a brief “Audience & Assumptions” section upfront, stating: *This plan assumes the reader is familiar with the harness’s architecture and prior roadmap.*  
2. Consider a glossary or footnote for niche terms if the document might be shared with non-technical stakeholders.  
3. If the team grows, a summary for newcomers could help them grasp the “why” behind operational priorities.  

Overall, this is a strong, audience-aware planning doc—it speaks the language of its intended user while staying actionable and risk-aware.

### accuracy-and-completeness (via deepseek)

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

### clarity-and-structure (via kimi)

Here is a clarity-and-structure review, targeting the friction between **first-time readers** (who don’t know what “the harness” is or what an “observer” does) and **experienced readers** (who already know the original Horizon C framing and need the delta, not the justification).

---

### **Edit 1: Add a 2-sentence “Product Context” blurb immediately after the reframing quote**
**Problem:** The document dives into DROP/KEEP/ADD before stating what the software *is* or *does*. A first-time reader must infer from scattered clues (“`harness review <doc>`”, “engine adapters”) that this is a local CLI tool for dispatching documents to multiple LLMs.  
**Fix:** Insert a short neutral context line directly under the reframing quote:  
> *“The harness” is a local CLI that dispatches documents/code to multiple LLM engines (Kimi, DeepSeek, Anthropic, etc.) for structured review, then synthesizes the results. This plan reframes the previous public-product roadmap into a durability-first internal tool.*

---

### **Edit 2: Move “What success looks like in 6 months” up to immediately follow the ADD section (before Wave 13)**
**Problem:** Readers hit ~40 rows of dense workstream tables with no north star. The target state is buried at 80% scroll depth. First-time readers don’t know which details are load-bearing and which are nice-to-have.  
**Fix:** Relocate the entire “What success looks like” section right after the ADD bullets. Retitle it **“Target State / Definition of Done”**. This lets readers evaluate every subsequent wave against a concrete goal.

---

### **Edit 3: Insert a “Terminology” callout between the ADD section and Wave 13**
**Problem:** Jargon accumulates fast: “observer state”, “dispatch ledger”, “lens-set”, “engine adapter”, “coord/observer/”, “DPAPI”. First-time readers are expected to know the system architecture before they reach Wave 13.  
**Fix:** Add a compact definition block:  
> **Terminology (for this plan)**  
> - **Engine** — An LLM API endpoint (Kimi, DeepSeek, Gemini, etc.).  
> - **Engine adapter** — The glue code that translates harness requests to a specific engine’s API.  
> - **Dispatch ledger** — The cost/usage log of every request sent.  
> - **Observer** — The background health-monitoring component.  
> - **Lens-set** — A configurable review rulepack (e.g., “security lens”, “style lens”).  
> - **VPS** — The optional cloud server where the harness may be deployed.

---

### **Edit 4: Prune the Risks table by deleting the four “GONE” rows**
**Problem:** The “Risks that change” table re-lists items already covered in the DROP section (Discord moderation, open-source vs commercial, marketplace gates, outside contributor governance). Experienced readers already absorbed this; the table invites skim fatigue.  
**Fix:** Replace the four “GONE” rows with a single lead-in sentence above the table:  
> *All distribution-related risks (marketplace, moderation, commercial decision, governance) are eliminated by the internal-tool framing and are omitted below.*  
Then keep only the three genuinely re-rated/new rows: **Operator burnout**, **Key-person dependency**, **Engine API drift**.

---

### **Edit 5: Add explicit skip-condition badges to the Recommended Sequence**
**Problem:** Waves 16 and 17 are conditional, but the numbered list presents them as sequential peers. A first-time reader sees “200-400h” and assumes everything is mandatory.  
**Fix:** Append conditional tags directly to the sequence list:  
> 4. **Wave 17** (VPS hardening) — **[Skip if no VPS deployment]**  
> 5. **Wave 16** (multi-user) — **[Skip if operator is solo]**

---

### **Edit 6: Convert “What I’d start with TONIGHT” from prose into a numbered checklist with a separated rationale callout**
**Problem:** The highest-leverage immediate actions are buried in a paragraph sandwich. Experienced readers want the actions; first-time readers want the reasoning. The current format serves neither efficiently.  
**Fix:** Restructure as:  
> **Tonight’s commit targets**  
> 1. `W13-OPERATOR-RUNBOOK` → `docs/INTERNAL_OPERATOR_RUNBOOK.md` (~3h)  
> 2. `W13-BACKUP-RESTORE` → `harness backup` + `harness restore` CLI, with round-trip test (~4-5h)  
> 3. `W13-AUDIT-JSONL` → append-only audit log (~2h)  
> 4. `W13-DISK-PRUNE` → size-aware cache pruning (~2h)  
>  
> > **Rationale:** The runbook captures this session’s context before it evaporates; backup closes existential data-loss risk. Both are bounded and demonstrably ship.

---

### **Edit 7: Collapse Wave 13’s “Why this wave first” paragraph to a single italicized sequencing principle**
**Problem:** The paragraph re-explains that existential risks (data loss, drift, rot) should come first. This is already obvious from the ADD section and the wave’s own goal statement. Experienced readers don’t need the persuasion; first-time readers got the point from the table.  
**Fix:** Replace the paragraph with one italicized line directly under the Wave 13 header:  
> *Wave 13 ships first because it closes existential risks (data loss, key rotation, engine drift, dependency rot). Once it lands, the tool can survive a month of neglect.*

---

### **Summary of impact**
| Audience | Pain addressed |
|---|---|
| **First-time reader** | Now knows what the tool is (Edit 1), sees the goal before the grind (Edit 2), has a jargon key (Edit 3), and understands what is mandatory vs. optional (Edit 5). |
| **Experienced reader** | Stops re-reading DROP items in the risks table (Edit 4), can scan tonight’s actions instantly (Edit 6), and isn’t re-sold on Wave 13’s priority (Edit 7). |

---

## Cross-engine notes

Read each lens above for the engine-specific findings.  Look for **convergent findings** (flagged by 2+ lenses) — those carry the strongest signal.  **Divergent findings** (flagged by only one lens) are often the most novel but should be verified against the document independently.
