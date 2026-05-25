### 1. Lens-specific findings

**Finding 1: The CLI has become operator-tax, not operator-value.**  
The bloat audit states the operator-side must track "30+ CLI verbs + their flags" and warns "Bloat risk: MEDIUM and growing." The runbook then documents emergency procedures requiring `harness preflight --fix --dry-run`, `harness observer watchdog-status`, and `harness observer restart`. First principles: a non-technical operator with 1-3h evening slots does not have the working memory for a 30-verb surface. The 1-year UX should be three operator commands — `review`, `today`, `fix` — and everything else should be autonomous or hidden.

**Finding 2: The SDK is the real product, yet `review` is still not in it.**  
The AGENT_QUICKSTART defines the SDK surface as "3 public functions (`dispatch`, `retrieve`, `budget_status`)", but the operator's most common workflow is `harness review <file>`. Tier 1 Shift G explicitly asks: "do I use dispatch or review?" First principles: the agent has one job — offload work. Forcing it to learn two APIs for one action is a design failure. The 1-year UX is `harness.review(file)` inside the same 3-function surface.

**Finding 3: Wave 15 plugin architecture is negative-ROI for a solo internal tool.**  
The Horizon C plan scopes Wave 15 at "~40-60h total" to achieve the goal that "adding a new engine takes < 2 hours instead of the current ~1 day." If the operator adds two engines per year, the payback period is 10-15 years. First principles: hardcode the engines. A single operator does not need an ABI, a plugin guide, or contrib tests.

**Finding 4: The max_tokens truncation bug proves agents cannot be trusted with output sizing.**  
STATUS.csv row `W12-B-MAX-TOKENS-DEFAULT-RAISE` records the real incident: "2/3 engines (DeepSeek + MiMo) cut off mid-section at max_tokens=2000 while Kimi ignored the cap entirely." Tier 1 Shift F (auto-pick max_tokens) remains unshipped. First principles: the tool must prevent information loss automatically; asking the agent to guess token budgets is a design failure that already destroyed real review output.

**Finding 5: The ouroboros pattern reveals the actual core loop is review+dispatch, not observer management.**  
The master audit notes: "The harness used itself for its own planning AND its own bug-finding... This is the ouroboros pattern: tool used to improve itself." The operator's real day-to-day is running `harness review` on client documents and reading syntheses. The 1-year plan should optimize that loop, not the cron/Task Scheduler/watchdog internals.

**Finding 6: Backup encryption is security theater given the actual threat model.**  
The Horizon C plan records the DeepSeek flag: "W13-BACKUP-RESTORE snaps .harness/ which likely contains API keys." Yet the bloat audit asks the honest question: "genuine security need or paranoia for an internal tool where .env is already on disk in cleartext?" On a solo-operator laptop, OS-level disk encryption already covers physical theft. Spending 3-4h on harness-level AES-256 is misallocated risk reduction.

**Finding 7: The unverified install path is the single point of failure for the entire 1-year vision.**  
The master audit states: "The single hardest unknown: whether `pip install -e .` actually works end-to-end on a clean machine. We've never tested this — every command we ran used `PYTHONPATH=src python -m harness`." If the agent cannot install the harness autonomously, every SDK feature, every review workflow, and every Wave 13+ operation is unreachable. The install path is load-bearing.

---

### 2. Recommended SHIP list (your top 3-5 rows to do FIRST)

1. **W13-INSTALL-VERIFY** — The master audit calls this "the single hardest unknown"; the AGENT_QUICKSTART promises `pip install -e .` works, but if it fails on a fresh Windows shell the agent-first promise dies before the agent can run a single dispatch.
2. **Tier 1 Shift G (unify `harness.review()` as SDK function)** — Removes the "do I use dispatch or review?" friction; the agent learns ONE API and the operator gets document reviews without burning context window on CLI flags.
3. **Tier 1 Shift F (auto-pick `max_tokens` from prompt length)** — Prevents the real truncation loss already observed in the Aquinas review; agents should not be asked to guess token ceilings.
4. **W13-AUDIT-JSONL** — DeepSeek-flagged foundational row; without an append-only audit ledger, the operator cannot treat the dispatch ledger as "source of truth for what work was done this month" one year out.
5. **W14-GEMINI-WIRE** — Reduces single-vendor dependency (a Kimi/Moonshot outage should not kill the tool); Gemini is already stubbed, so this is the cheapest additional production fallback.

---

### 3. Recommended DROP list (your top 2-4 rows to NOT do)

1. **W15-PLUGIN-ARCHITECTURE (all of Wave 15)** — 40-60h to optimize a task the solo operator performs maybe once per year. Hardcode the 5 engines; the ROI on an ABI is negative until a second developer joins.
2. **W14-BEST-OF-N** — Concurrent multi-engine dispatch multiplies cost and complexity for an internal tool where the operator can simply re-run a review if output is poor. The master audit's cost discipline ("$0.20 spent across 12 commits") is a feature; best-of-N undermines it.
3. **W16-