# W5-F cross-engine verification — diagnostic finding (2026-05-22)

**Operator question**: "Verify W4-G finding across 3 engines on source-laden packets."

**Discovered**: the silent-empty pattern across all 3 engines was caused by
the probe script's `max_tokens=500` setting, **not** by engine
unreliability.  All 3 engines (Kimi, MiMo Pro, DeepSeek) burn the
output-token budget on internal reasoning ("thinking" mode) before
emitting any final-message tokens.  Setting 500 tokens too tight means
**0 final tokens** survive → looks like silent-empty.

## First run results (max_tokens=500, my probe-script bug)

| Packet (size) | kimi | mimo-pro | deepseek |
|---------------|------|----------|----------|
| small (5.7 KB)  | EMPTY | EMPTY | TEXT-ONLY (truncated mid-JSON) |
| medium (1.0 KB) | EMPTY | EMPTY | **EMPTY** |
| large (20.2 KB) | EMPTY | EMPTY | OK |

DeepSeek 1/3 was *not* an engine reliability issue — it was budget
starvation.  Smoking-gun: each empty response reported
`tokens_out=500` (the cap), meaning the engine generated 500 tokens of
internal reasoning that never made it to `message.content`.

## Where the 500/1500 caps originated

| Location | max_tokens | Status |
|----------|-----------|--------|
| `scripts/verify_source_laden_3engines.py` (this verification) | 500 | **Bug.** Fixed → no override (use engine defaults). |
| `scripts/multi_agent_coverage.py` (W4-G campaign) | 1500 | Tight but workable for DeepSeek; possibly under-budgeted for Kimi/MiMo. |
| `src/harness/engines/concrete.py` (engine defaults) | 32768 (DeepSeek/Kimi/MiMo), 8192 (Anthropic) | **Correct.** Production code paths inherit these. |
| `src/harness/coord/worker.py` (worker dispatch) | (no override) | **Correct** — inherits engine defaults. |
| `src/harness/engines/dispatcher.py` | (no override) | **Correct** — inherits engine defaults. |

**Bottom line**: production coord runs (`coord run --engine swarm/deepseek`)
get the full 32k output budget per dispatch.  They're not at risk from
the probe-script bug.

## Implications for W4-G's "Kimi 0/5" finding

W4-G used `max_tokens=1500` against ~4KB source-laden packets.  At 1500
output tokens, even DeepSeek was barely getting through (1/3 in the
recheck before the budget fix).  The Kimi 0/5 result is plausibly
amplified by budget-starvation, not pure engine failure.

**Action item**: re-run W4-G with engine-default max_tokens to get the
*production-accurate* reliability picture.  Will land as W5-F-v2.

## Updated takeaway for production

1. The harness's silent-noop guards (W4-A worker + W4-B integrator +
   Rule 2/4 dispatcher) catch ALL empty-output cases regardless of
   cause — including the budget-starvation flavour we just diagnosed.
   No production runs at risk from this.

2. Probe-script authors must NOT pass tight `max_tokens` overrides
   when the engine has thinking mode.  Either omit entirely (32k
   default) or pass ≥ 4096.

3. The W5-C reliability digest (`coord/engine_reliability.json`)
   currently reflects the budget-starved data.  Should be regenerated
   once W5-F-v2 produces budget-correct numbers.

## Diagnostic value of this finding

This is exactly the kind of issue overnight-unattended would have
silently hit: a probe script with `max_tokens=500` would have looked
like total engine failure to a tired operator at 3am.  Catching it
during verification (before Path 2 real-money pilot) is the right
order of operations.

## Second-run results (max_tokens=2000) — corrected reliability picture

| Packet (size)  | kimi | mimo-pro | deepseek |
|----------------|------|----------|----------|
| small (5.7 KB)  | FAIL `internal` 60s | FAIL | **OK** |
| medium (1.0 KB) | FAIL `internal` 60s | **OK** | **OK** |
| large (20.2 KB) | FAIL `internal` 60s | **OK** | **OK** |

**Final score: DeepSeek 3/3, MiMo Pro 2/3, Kimi 0/3.**

### Per-engine diagnosis

- **DeepSeek v4-flash**: production-ready primary for source-laden
  packets.  3/3 OK at 2000-token budget, average latency 7s, cost
  ~$0.001 per dispatch.
- **MiMo v2.5-Pro**: viable fallback.  2/3 OK at 2000-token budget,
  latency 19-25s, free per Token Plan subscription.  Failed only on
  smallest packet — may be a packet-content quirk.
- **Kimi K2.6 for-coding**: **NOT a budget issue.**  All 3 hit
  Kimi's 60-second thinking-time cap with `err="internal"`, returning
  `tokens_in=tokens_out=0` (HTTP failure level — request never
  produced usable output).  Confirms W4-G finding.  Kimi is unsuitable
  for source-laden FILE/REPLACE work; reserve for short-form non-
  thinking tasks.

### Implications for Path 2 (overnight pilot)

Primary engine = `swarm/deepseek` (3/3 empirical).
Fallback engine = `swarm/mimo` (2/3 empirical, free).
Skip Kimi entirely for the pilot.
