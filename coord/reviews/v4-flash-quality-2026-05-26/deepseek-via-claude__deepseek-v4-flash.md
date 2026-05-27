# Quality panel response: deepseek-via-claude/deepseek-v4-flash

**latency**: 19.6s   **tokens_in**: 835   **tokens_out**: 944   **cost**: $0.0553

---

## 1. Decision soundness (3-4 sentences)

The decision is **not sound** given the evidence provided. A single $0.16 smoke matrix run of 5×3 toy cells is orders of magnitude too small to characterize routing behavior across the diversity of real panel workloads (conversation depth, tool complexity, multi-turn state). Permanent routing changes that affect every "cost-class" dispatch should require statistical confidence from repeated runs with representative traffic distributions. The price cut justifies *investigating* a flip, not *committing* one.

## 2. Confounders

- **MiMo tool-call XML markup quirk**: MiMo-II uses a different tool-call serialization (explicit XML tags vs. JSON-in-markdown). If downstream parsers or token counters assume a specific format, MiMo's improved *raw* cost-per-token may be offset by inflated token counts from parsing retries or re-prompting — the smoke matrix almost certainly didn't test parser failure rates.
- **Token-Plan credit pool exhaustion under bulk dispatch**: MiMo's real latency-per-output-token may be higher than Claude-3.5-Haiku on sustained batches. If the credit pool (used for per-turn budgeting) drains faster than expected, bulk dispatches will hit fallback logic mid-conversation, creating a cascade of degraded responses that a single-run smoke matrix cannot capture.
- **Prompt size mismatch**: The $0.16 run almost certainly used the canonical "tiny" evaluation prompts. Real panel conversations often have 4k–12k context windows with multi-step reasoning. Cache-hit ratios ($0.20 → $0.0036, a 98% drop) are the biggest cost lever, but realistic cache-hit rates depend on conversation structure — a 5-item smoke matrix tells you nothing about whether MiMo's cache patterns will hold under diverse session lengths.
- **Model stability**: One run captures zero variance. MiMo's behavior (latency, refusal rates, formatting consistency) may degrade under load or with certain prompt structures that weren't in the 5-category test.

## 3. De-risking evidence I'd gather

1. **Cost-per-correct-task over 1,000+ stratified dispatches (medium effort)**: Replay 1,000 historical panel sessions spanning all task categories, measuring *both* raw token cost and end-to-end outcome correctness for MiMo vs. the current primary engine. The key metric is cost-per-passing-response, not just cost-per-token. This catches parser failures, retries, and cache-hit realism.

2. **A/B shadow run in production on a 5% traffic slice (high effort)**: Route 5% of cost-class traffic to MiMo for 48 hours, measuring p50/p95 latency, credit-pool exhaustion rates, fallback frequency, and user-facing error rates alongside cost. This is the only way to capture bulk-dispatch dynamics and real cache-hit ratios.

3. **Adversarial prompt suite covering edge cases (low effort)**: Construct a targeted 50–100 prompt set exercising known failure modes — extremely long tool chains, multi-turn follow-ups, contradictory instructions — and run 5× Monte Carlo repetitions. If MiMo shows no regressions on any edge case, the risk of silent degradation drops significantly.