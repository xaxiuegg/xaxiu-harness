# Quality panel response: kimi-via-claude/default

**latency**: 49.9s   **tokens_in**: 693   **tokens_out**: 2541   **cost**: $0.0692

---

## 1. Decision soundness (3-4 sentences)
A single $0.16 smoke matrix is grossly insufficient evidence for a production routing flip that governs every cost-class dispatch. Five categories across three engines lack the statistical power to surface quality regressions, latency tails, or parsing failures, and the trivial spend implies the prompts were short and unrepresentative of real panel workloads. While the price-sheet change is real, conflating tariff updates with empirical end-to-end validation risks silent degradations at scale.

## 2. Confounders (3-5 bullets, specific)
- **Tool-call XML markup quirk**: MiMo may emit non-standard or escaped XML for tool arguments that the harness parser rejects; the smoke matrix likely did not exercise the full tool-schema surface.
- **Token-Plan credit pool exhaustion**: Promoting MiMo to primary concentrates bulk dispatch onto its credit pool, risking faster exhaustion, rate-limit backoffs, and expensive cross-engine failovers that erase the 71% savings.
- **Latency on realistic workloads**: A $0.16 total spend implies tiny prompts; MiMo’s time-to-first-token and total latency on long-context, multi-turn panel tasks remain uncharacterized.
- **Cache-hit rate assumption gap**: The 98% cache-hit price cut only materializes if MiMo achieves high reuse; the smoke test cannot estimate production cache-hit rates or reveal prompt-layout incompatibilities that disable caching.

## 3. De-risking evidence I'd gather (ranked 2-3 items with effort)
1. **48-hour shadow-traffic bake-off at 10% volume** (Medium effort): Route 10% of live cost-class traffic through MiMo as primary while keeping the incumbent engine as a shadow scorer. Measure task-success rate, parser error rate, end-to-end latency (p50/p95/p99), and realized cost per task to validate behavior under authentic workloads without full fleet exposure.
2. **Expanded tool-aware smoke matrix with cache telemetry** (Low effort): Run 25+ categories emphasizing tool calls, nested XML, and multi-turn context while logging cache-hit flags and downstream parse success. This surfaces the markup quirk and calibrates true cache economics before scaling volume.
3. **Credit-pool bulk-dispatch stress test** (Medium effort): Simulate peak-day dispatch volume against MiMo’s rate limits and token-plan balance to measure pool-exhaustion curves and forced-fallback frequency when MiMo is the sole primary target.