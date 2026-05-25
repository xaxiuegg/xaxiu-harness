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