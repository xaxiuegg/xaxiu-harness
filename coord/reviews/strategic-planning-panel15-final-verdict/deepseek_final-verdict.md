# Comprehensive Review — DeepSeek (Round 2)

**Role**: Full-spectrum engine, all lenses applied.  
**Objective**: Render independent verdict on prior synthesis; flag dissents.

---

## Section 1: SHIP list verdict

| Prior SHIP | My Verdict | Reason |
|---|---|---|
| **W13-INSTALL-VERIFY** | **AGREE** | Universal #1 pick. Closes the single highest‑risk unknown: "will the harness even run on a clean shell?" |
| **W13-AUDIT-JSONL** | **AGREE** | Foundational for every auto‑default, debugging, and forensic review. Must include secret redaction from day one. |
| **Tier 1 Shift F (auto max_tokens with safe floor)** | **AMEND** | Accept the heuristic only with the resolved safe‑floor (≥4000 tokens unless `--quick`). Cautiously agree, but keep the floor explicit and overrideable. |
| **`harness.review()` as new SDK function (NOT merge)** | **AGREE** | D2’s ruling is correct: different return types, different intents. Keep separate. |
| **`harness.capabilities()` SDK function + surface in `today`** | **AGREE** | The "both layers" solution (SDK fn + `today` output) closes the hallucination vector without adding a new CLI verb. Best compromise. |

---

## Section 2: DROP list verdict

| Prior DROP | My Verdict | Reason |
|---|---|---|
| **W15 Plugin Architecture (entire wave)** | **AGREE** | Payback 10–15 years for a solo operator. Hardcode the 5 engines. |
| **W14-BEST-OF-N** | **AGREE** | Cost multiplier with no validated need. A single review with explicit override is cheaper and simpler. |
| **W16 Multi-User (entire wave)** | **AGREE** | Operator is solo. Skip unless a team materialises. |
| **W17 VPS hardening (entire wave)** | **AGREE** | Operator runs locally. Build only if VPS use starts. |
| **W13-PLUGIN-SANDBOX-PLAN** | **AGREE** | Trusted authors; document the risk in a short note, drop the planning row. |
| **W13-BACKUP-ENCRYPTION (full AES)** | **AGREE** | Replaced by secrets‑redact. Full encryption is overkill for an internal tool where `.env` is already plaintext on disk. |
| **W14-MISTRAL + W14-LOCAL-LLAMA** | **DISAGREE — keep LOCAL-LLAMA as deferred backlog** | The 5-engine pool is *currently* enough, but a local offline fallback (llama.cpp) protects against all cloud API outages. Not urgent — keep as a low‑priority backlog item, not a drop. Cost: ~8h to implement once; can save days of downtime. |

**One change to the DROP list**: move **W14-LOCAL-LLAMA** from DROP to **BACKLOG** (do not ship now, but don't delete). The prior synthesis’s reasoning — “5 engines already enough” — is valid *today*, but engine API drift or vendor shutdown could change that quickly. A local fallback is the single most resilient move.

---

## Section 3: ADD list verdict

| Prior ADD | My Verdict | Reason |
|---|---|---|
| **`harness.capabilities()` SDK function** | **AGREE** | Already in SHIP. Programmatic ground truth prevents hallucinated engine/lens names. |
| **CI doc-doc-sync gate** | **AGREE** | Catches future‑as‑present at PR time. Small effort, high payoff. |
| **Schema versioning for all data structures** | **AGREE** | High leverage – prevents silent data corruption when formats change. Effort is low (add field to each JSON/CSV writer). |
| **Auto-default guardrail framework (CI test)** | **AGREE** | Essential to prevent silent defaults. Enforces visible/overridable/auditable trio. |
| **W13-BACKUP-INTEGRITY (SHA256 + verify)** | **AGREE** | Without it, auto-snapshot (Dissent 5) is dangerous. Ships verification before claiming success. |

**Additional ADD suggestion**: **`harness commands --did-you-mean`** for CLI flag/verb typos (from bloat audit). Very low effort (~2h), reduces operator frustration and future Claude hallucination of non‑existent verbs. Could be implemented as a simple fuzzy‑match on known verbs and common flags.

---

## Section 4: Dissent rulings (no fence‑sitting)

1. **Merge `dispatch` + `review`?** → **KEEP SEPARATE**. Different intents, different return shapes. Add `harness.review()` as a new function. (Side: D2)

2. **Backup encryption?** → **SECRETS‑REDACT ONLY**. Full AES is overkill; skip entirely is too risky (keys can appear in cached prompts). Redact API‑key‑like patterns before writing archive. (Side: resolution in prior synthesis)

3. **Auto-pick `max_tokens` from prompt length?** → **SHIP WITH SAFE FLOOR (≥4000 unless `--quick`)**. Heuristic should err high, not low. The floor prevents truncation on analysis tasks. (Side: resolved compromise)

4. **`harness whoami` as new CLI verb?** → **NO NEW VERB**. SDK function + surface in `today`. Adding another verb is cognitive cost for minimal gain. (Side: MiMo)

5. **Auto-snapshot before risky ops?** → **DEFER until W13-BACKUP-INTEGRITY ships**. Auto-snapshot without integrity verification is lying. Once integrity is mandatory, it becomes safe. (Side: D3/D5)

6. **Auto-close low‑severity flags after 7d?** → **REPLACE WITH AUTO‑ESCALATE**. Auto‑close destroys early‑warning signal. Escalate unreviewed flags to L3 after 7d, keep archived for forensics. (Side: D3)

---

## Section 5: Add or remove any items from prior synthesis

### What the prior synthesis might have missed

1. **The local‑LLAMA fallback should not be fully dropped.** I flagged this in Section 2. The 5-engine pool is good, but it’s all cloud‑dependent. One vendor outage or rate‑limit spike could halt all work. A local fallback (even if rarely used) is insurance. **Recommendation**: move from DROP to low‑priority backlog (after Week 2 operations hardening).

2. **The “operator→SDK shift” beyond Tier 1 is under‑addressed.** The prior synthesis shipped auto‑max_tokens and auto‑lens‑set, but the bloat audit lists other high‑value shifts for Week 2–3: auto‑retry with fallback (Tier 2 E), cost‑cap pre‑check (Tier 2 I), L5 events inline (Tier 2 J). These should be **documented as future candidates**, not dropped. I’d add a note in the forward plan: “After Week 2, consider Tier 2 shifts E, I, J – each ~2h, each removes a real operator cognitive burden.”

3. **Hallucination test harness (from bloat audit Q6) was not elevated.** The prior synthesis does not include building a test that fires common misuse patterns and verifies helpful error messages. This is a small, cheap win (~2h) that would pay dividends every time a future Claude hallucinates an engine name. **Recommendation**: add to Week 3 as a “nice to have” – not critical, but high leverage for the cost.

### Row that should be kept from DROP despite my disagreement

The prior synthesis dropped **W14-MISTRAL** (cost, no proven need). I agree with dropping Mistral for now – new paid API with little differentiation from existing engines. Local‑LLAMA is different because it’s free and offline.

### Item in SHIP that I’d reconsider

**Tier 1 Shift A (auto‑pick lens‑set from file extension)** was in the bloat audit’s “Ship tonight” list but **not explicitly in the prior synthesis’s SHIP list**. The prior synthesis only had auto‑max_tokens (Shift F) and auto‑lens‑set implied in the `harness.review()` auto‑defaults. I’d **explicitly add auto‑lens‑set from file extension** as part of the `harness.review()` SDK landing. It’s tiny (30min), reduces operator burden immediately, and doesn’t hurt.

---

## Section 6: Single most important action

**Ship `W13-INSTALL-VERIFY` and `W13-AUDIT-JSONL` in the same commit tomorrow – they are independent, take under 5h combined, close the two biggest unknowns (will the harness install? what is it doing?), and unlock everything else.**

- INSTALL-VERIFY is the universal #1 panel pick; it’s the foundation of trust in the entire toolchain.
- AUDIT‑JSONL is the prerequisite for every auto‑default; without it, all future default behavior is invisible and therefore dangerous.

Together they turn “I hope this works” into “I can prove this works.”

---

## Section 7: Confidence + dissent flagging

**Overall confidence in the prior synthesis’s forward plan**: **0.85**  
Strong convergence from 11 engines. The resolved dissents are sensible. The sequencing is logical.

**Which claim do I least trust?**  
> “5 engines already provide enough redundancy – drop local‑LLAMA entirely.”  
This is true *today*, but it ignores the risk of simultaneous API outages or the operator needing to work offline (e.g., on a plane, during a vendor network issue). A free offline fallback is cheap insurance. The prior synthesis’s cost‑benefit analysis for W14-LOCAL-LLAMA assumed “maybe 8h to implement” – a one‑time cost that would pay for itself after a single outage that blocks all cloud engines for a day. I suspect the panel underestimated the likelihood of needing an offline mode.

**Where would I bet the prior synthesis is wrong?**  
The relative urgency of **schema versioning**. While I agree it’s important, the prior synthesis elevated it to a high‑priority ADD. In practice, the harness’s data structures are small and change rarely. The real risk is more about adding new fields (which can be added with backward‑compatible defaults) than about format migrations. I’d prioritize it lower than the CI doc‑sync gate and the backup integrity work. **I’d rank schema versioning as Week 3, not Week 1–2.**

---

## Final one‑sentence summary

**Ship the two foundations (install‑verify + audit‑jsonl) tomorrow, add the `harness.review()` SDK with auto‑defaults on Wednesday, drop 250h of plugin/multi‑user/VPS bloat but keep local‑LLAMA as a backlogged resilience option, and enforce CI gates to prevent future lies in docs – then tag v1.0.0 with confidence.**