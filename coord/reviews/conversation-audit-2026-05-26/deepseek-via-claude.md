# Audit response: deepseek-via-claude

**latency**: 36.1s   **tokens_in**: 3724   **tokens_out**: 2291   **cost**: $0.0893

---

## 1. Audit verdict (2-4 sentences)

Directionally correct â€” multi-key pools, empirical routing, and visual-verify discipline all address real gaps. But the velocity is concerning: two major subsystems (key health + routing recommender) shipped in a single day with zero soak time, and both introduce persistence formats (JSONL ledger, JSON policy file) that are invisible to the operator until they break. The keys UI shipped with per-slot health badges and labels â€” conspicuously missing is a **global health dashboard** or **notification when all keys for a provider are unhealthy**, which is the failure mode that actually matters.

## 2. Risks I see (3-5 bullets)

- **key_health.jsonl grows unbounded.** Every probe append one line. On daily `probe-all` cadence, ~365 lines/year â€” fine. But if the operator runs `probe-all` programmatically in a cron loop or via a CI-style trigger, this file will accumulate thousands of entries with no compaction, and pruning requires manual truncation a non-technical user can't do confidently.
- **Security patches are untested in the browser.** 27 regression tests pass in isolation, but Origin-check + CSP + env-path resolution all changed in one commit. A live Playwright test that starts the dashboard, POSTs a save, and verifies the .env file landed in the correct location with correct permissions is missing. Unit tests mock too much.
- **Routing recommender is a CLI verb, not a UI affordance.** The operator is non-technical. `harness engines recommend code-review` is a command they must remember, type correctly, and interpret. Without a dashboard widget that surfaces the recommendation alongside engine latency/cost data, this feature will be used once and forgotten.
- **Multi-key failover is untested at the integration level.** Each key gets a health badge. But there is no test that configures 3 keys, marks the first two unhealthy, dispatches a request, and asserts the third key was used. The resolver logic is unit-tested; the wiring through the actual dispatch path is not.
- **Concurrent writes to key_policy.json.** The Tier2 design stores per-provider strategy in a single JSON file. Two simultaneous `harness keys policy set` invocations (e.g., from script + CLI) will race and one will silently overwrite the other. No file locking.

## 3. Next 2-3 moves I'd prioritize (ranked, with effort estimate)

1. **Add JSONL log rotation + a `keys health prune` CLI verb** (medium, ~2h). Compact `key_health.jsonl` by keeping only the last N entries per alias. Without this, the health ledger is a leaky abstraction that will silently consume disk and confuse the operator when old failures resurface after decay. Make `probe-all` auto-trim as a side effect so the operator never thinks about it.

2. **Build a global keys health dashboard widget** (medium, ~4h). The per-slot badges are nice; the operator's actual question is "can I dispatch right now?" Add a single row at the top of the Keys page showing green if every provider has â‰¥1 healthy key, yellow if at least one provider is degraded, red if any provider has zero healthy keys. Link this to the actual dispatch path so a red provider is blocked at the UI level before the operator submits a job.

3. **Add an integration-level failover test** (small, ~1.5h). Write a Playwright or subprocess test that: (a) configures two keys for DeepSeek with the first having a deliberately wrong API key, (b) dispatches a Pattern B request, (c) asserts the response was generated (proving failover worked), and (d) verifies the health badge for the first key shows "auth-failed". This is the single highest-value test missing from today's work.

## 4. One thing I'd push back on

**The routing recommender shipped too early.** It adds 18 tests and a new CLI verb, but the underlying "decision tree" in `engine-routing-empirical.md` is based on *one* 3-run smoke matrix ($0.23). That's not empirical â€” it's anecdotal. A recommender that hardcodes "DeepSeek v4-flash for code review" based on a single 15/15 pass risks baking in a false sense of optimality. The higher-leverage investment would have been to build a cost/latency/success-rate ledger (analogous to key_health.jsonl) that records *every* dispatch outcome and lets the operator query real statistics. Then the recommender derives from actual data. Today's version is premature optimization dressed as a feature.