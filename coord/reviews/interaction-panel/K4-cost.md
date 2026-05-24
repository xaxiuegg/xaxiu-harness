<!-- name=K4-cost latency_ms=32741 error='' -->

1. W8-AUDIT-ROUTER row / `audit/router.py`: build a tiered failover so MiMo remains default for audit, panel, and planner, but DeepSeek—already integrated at $0.35 via the W7-B1 StreamingTransport ABC—auto-assumes the role on MiMo 429 or quota-exceeded. This hedges the MiMo monoculture without rewriting the operator directive: if MiMo tightens, the harness degrades to the cheap engine rather than halting.

2. WORKING: The composite panel-closeout with conditional backlog locks (W6 → W7 mutation gating) preserved honest STOPs, prevented spec-shaping, and lifted kill rates from 0.0–1.0 to ≥3.0. Keep that route. NOT WORKING: STATUS.csv mtime hook noise burned ~6 acknowledge-touch token cycles in W7, and the Kimi `reasoning_content`/`max_tokens` footgun wasted budget on empty returns. Replace mtime checks with an append-only operation journal and enforce a Kimi max-tokens floor above reasoning budget.

3. Theme: "Cost-resilient cognitive distribution." Decouple audit, panel, and planner from any single engine via a cost-router; eliminate hook-noise token leaks; establish engine tiers (DeepSeek bulk, Kimi deep-reasoning, MiMo planner-override) so a quota tightening becomes a budget routing event, not a wave-blocking failure.
