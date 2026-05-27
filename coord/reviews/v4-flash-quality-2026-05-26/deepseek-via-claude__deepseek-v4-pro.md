# Quality panel response: deepseek-via-claude/deepseek-v4-pro

**latency**: 37.6s   **tokens_in**: 835   **tokens_out**: 893   **cost**: $0.0850

---

## 1. Decision soundness

One smoke matrix of 5×3 on $0.16 total cost is not sufficient evidence for a routing flip that changes every cost-class dispatch. A smoke matrix validates that engines don't crash—it does not measure task-level correctness, parsing consistency, or behavioral regressions across a meaningful distribution of real workloads. The price cut makes MiMo attractive, but attractiveness is not reliability. Flipping routing without workload-representative correctness data confuses "the engine is cheaper now" with "the engine is safe to make primary." The decision is directionally reasonable given the dramatic price drop, but the evidence bar is too low for the blast radius.

## 2. Confounders

- **Tool-call XML markup quirk.** MiMo models are known to emit non-standard XML wrappers (e.g., `<function_call>` or bespoke tag structures) that differ from Claude-native or OpenAI-native formats. The harness's tool-call parser may silently truncate, misparse, or reject these—producing "success" responses with empty/malformed tool invocations that pass a smoke check but fail real panel tasks.

- **Token-Plan credit pool exhaustion under bulk dispatch.** If MiMo becomes the cost-class primary, bulk dispatch (swarm, batch panel runs) will route significant volume to it. Token-Plan credit pools often have per-model rate limits or aggregate caps. A routing flip without load-testing the credit path could cause cascading 429/402 failures mid-panel, silently dropping tasks that the harness retry logic may not recover gracefully.

- **Latency profile mismatch between smoke prompts and realistic panels.** Smoke matrix prompts are typically short (single-turn, low-token). Real panel workloads involve multi-turn conversations with accumulated context windows, tool-call chains, and large intermediate outputs. MiMo's time-to-first-token and tokens-per-second at 32k+ context may degrade non-linearly, causing timeout failures that don't appear in smoke runs.

- **Output format drift on structured extraction tasks.** Panels that depend on JSON-mode, schema-constrained outputs, or specific delimiter patterns (e.g., `ANSWER:` tags) may break if MiMo's instruction-following differs from the prior primary engine. A smoke matrix doesn't validate schema compliance across the output distribution.

- **Interaction with the routing recommender's own scoring logic.** The recommender likely blends cost, latency, and quality signals. If the quality signal is stale or zero-weighted because no quality evals have run, the recommender may be making a purely cost-driven decision—effectively treating MiMo as strictly dominant when it isn't.

## 3. De-risking evidence I'd gather

1. **Targeted quality eval on 50–100 real panel conversations (effort: medium).** Replay a sample of actual panel traces (not synthetic smoke prompts) through MiMo and the current primary, diff the outputs, and flag parsing failures, schema violations, and tool-call malformations. Run this for the 3–5 most-used task classes. This directly measures the confounders above and costs maybe $2–5 in API spend.

2. **Credit-pool load test at projected dispatch volume (effort: low).** Fire 100–200 concurrent MiMo requests through the actual Token-Plan credit path used in production, monitor for 429/402 rates, and confirm retry behavior. This is a 10-minute script that catches the exhaustion confounder before it hits real panels.

3. **Latency profiling at realistic context sizes (effort: low).** Run 20–30 prompts at 16k, 32k, and 64k context lengths (simulating panel mid-conversation state) through MiMo, measure p50/p95/p99 latency, and compare against the harness's timeout thresholds. Smoke prompts at 1k context are not informative here.