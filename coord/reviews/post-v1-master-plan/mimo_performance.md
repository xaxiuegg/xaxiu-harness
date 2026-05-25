# Performance Lens: Post-v1.0.0 Master Plan

## Stance summary

The dispatch path is burning tokens and latency on engines with catastrophic failure rates—anthropic at 100% failure (139/139 events), deepseek at ~19% (209/1116), mimo at ~29% (27/92). The harness currently treats all configured engines equally regardless of recent health. The most critical missing piece in v1.0.0 is **health-aware dispatch routing**—we're paying round-trip latency and token costs for engines we have strong statistical evidence will fail. The audit trail (W13-AUDIT-JSONL) must be preserved, but the dispatch path needs to become cost-aware.

## Top 3 rows to ship next (ranked)

### 1. **W14-DISPATCH-HEALTH-SCORING**
**Title**: Implement engine health scoring from engine_performance_log.jsonl for dispatch prioritization
**Estimated effort**: M (4-5h)
**Why this row**: Currently dispatches hit engines blindly—anthropic's 100% failure rate means every dispatch to it wastes a round-trip. Health scoring transforms the 922+ failure events already logged into actionable routing intelligence. This directly reduces cost ($0 wasted on guaranteed failures) and latency (skip the round-trip).
**Acceptance criteria**:
- `dispatch()` accepts optional `health_aware=True` parameter (default True)
- Engine selection weights based on rolling 24h success rate from state/engine_performance_log.jsonl
- Engines with <50% recent success rate automatically deprioritized to fallback position
- Engine with 100% failure rate (anthropic) excluded from primary dispatch unless explicitly forced
- New `harness engines --scores` CLI verb shows per-engine health score and decision rationale
- All changes audit-logged per W13-AUDIT-JSONL pattern

### 2. **W14-DISPATCH-TIER-POLICY**
**Title**: Configurable dispatch tiers (primary/secondary/fallback) with automatic demotion
**Estimated effort**: M (3-4h)
**Why this row**: Even with health scoring, we need policy control. Currently engines are statically configured. This row implements tier-based dispatch: healthy engines in Tier 1, degraded in Tier 2, failing in Tier 3. Automatic demotion happens when failure rate exceeds threshold (configurable, default 30%). This prevents the MiMo parallel-dispatch race from cascading.
**Acceptance criteria**:
- `config.yaml` supports `dispatch_tiers: {primary: [...], secondary: [...], fallback: [...]}` (new optional section)
- Auto-demotion triggered when engine failure rate >30% over last 100 dispatches
- Manual override via `harness engines promote <name>` / `harness engines demote <name>` (audit-logged)
- Tier changes logged to state/engine_tier_changes.jsonl with reason (auto/manual)
- `harness engines --tiers` shows current tier assignments and auto-demotion status
- Parallel dispatch (ThreadPoolExecutor) respects tier ordering: try primary tier first, secondary only if primary fails

### 3. **W14-PARALLEL-RETRY-TUNING**
**Title**: Fix parallel-dispatch race condition and implement configurable retry policy
**Estimated effort**: S (2-3h)
**Why this row**: v1.0.0 known issue: MiMo hits RemoteProtocolError on parallel dispatch but succeeds on serial retry. Current retry is per-engine inside transport layer, doesn't cover the parallel-dispatch race. This wastes latency (first parallel attempt fails, then serial retry succeeds—2x latency).
**Acceptance criteria**:
- Parallel dispatch catches RemoteProtocolError and retries with exponential backoff (configurable, default 3 retries, 1s/2s/4s)
- `dispatch()` accepts `retry_policy: {max_retries: 3, backoff_base: 1.0, backoff_multiplier: 2.0}` (override per-call)
- `config.yaml` supports `retry_policy:` section (global defaults)
- Retry attempts logged to state/retry_attempts.jsonl with engine, error, attempt#, latency
- `harness engines --reliability` CLI verb shows per-engine retry success rate (how often retry succeeds after initial failure)
- No regression in serial-dispatch path (existing tests must pass)

## Rows you'd DROP from CURRENT_PLAN.md's Week 2/Week 3 sections

### Week 2:
- **CI doc-doc-sync gate** (S, 1h) — Doesn't affect dispatch cost, latency, or reliability. Documentation drift is a quality issue, not a performance issue. Defer to Week 3+.
- **Auto-default guardrail CI framework** (M, 4-5h) — Important for safety but doesn't address the burning performance issue. Auto-defaults are infrequent; dispatch inefficiency is per-call. Defer until health-aware dispatch is live.

### Week 3:
- **Schema versioning** (S) — No performance impact until schema actually changes. Premature optimization.
- **`harness commands --did-you-mean`** (S, 2h) — UX improvement, not performance. Zero impact on cost/latency/reliability.
- **Hallucination test harness** (S, 2h) — Quality concern, not performance. Doesn't reduce token waste or dispatch latency.

## Single most important action this week

**Ship W14-DISPATCH-HEALTH-SCORING** — Stop wasting tokens on engines with proven 100% failure rates (anthropic) and deprioritize engines with >20% failure rates (deepseek, mimo) until they recover.

## Confidence in your own recommendation

**0.7** — High confidence that health-aware dispatch will reduce cost/latency, but I need exact token-cost-per-failed-dispatch to quantify the savings. If anthropic dispatches cost $0.01 each, we're wasting $1.39/week on guaranteed failures; if $0.10, it's $13.90/week. More data makes me more confident.

## What this lens systematically MISSES

This lens ignores **auditability and safety guarantees**—the CI doc-doc-sync gate and auto-default guardrail prevent documentation drift and unsafe defaults, which matter for long-term maintainability even if they don't affect dispatch performance.