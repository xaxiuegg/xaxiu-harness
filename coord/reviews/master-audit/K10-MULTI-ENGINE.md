<!-- name=K10-MULTI-ENGINE latency_ms=162802 error='' -->

## Score

1. **Correctness — 2**: `--engine-fill` is operator-configurable rather than locked to `aggressive`, so the “keep Kimi slots full” policy is optional, not enforced; `deepseek:5` persisted past threshold without auto-quarantine.
2. **Robustness — 3**: Dead-engine detection, quarantine schema, and heal commands exist, yet remediation still surfaces as a manual preflight warning instead of an autonomous circuit-break.
3. **Operator-usability — 3**: Non-technical operators can run `engines-heal` and `preflight --fix`, but receive no visibility into Kimi subscription slot utilization vs. queue depth.
4. **Test discipline — 2**: No cited tests assert cooldown backpressure or Kimi backfill behavior; W8 skipped engine-area mutation sweep after the schema fix.
5. **Risk — 3**: Subscription waste (idle Kimi) and repeated dead-engine hits (DeepSeek ×5) create concurrent cost and reliability exposure.

**Top blocker**: Harden `engine-fill` to default/aggressive and add a `kimi_slot_waste` preflight probe so queued work never sits while subscription capacity is idle.

**Verdict**: SHIP-WITH-FIXES — primitives are landed, but policy enforcement is manual and dead-engine auto-remediation stops one step short of full autonomy.
