# Cross-engine audit of 2026-05-26 work — synthesis

**Date**: 2026-05-26
**Subject**: 6 commits shipped in one day, 2026-05-26 — keys UI render fix, visual-verify convention, security hardening, multi-key Tier 1 + Tier 2, cross-engine routing audit
**Method**: same audit packet dispatched to all 3 Pattern B engines in parallel, plus retries for the two that timed out on first pass

## Dispatch metadata

| Engine | Result | Latency | Cost | Notes |
|---|---|---|---|---|
| `kimi-via-claude` | ✅ substantive | 124s | $0.089 | Delivered full structured audit |
| `deepseek-via-claude` | ✅ substantive | 36s (retry) | $0.089 | First pass timed out at 180s; succeeded at 480s ceiling in 36s |
| `mimo-via-claude` | ❌ off-task | 435s | $0.350 | Hit $0.20 budget cap on first try (17k input tokens via Claude Code's internal loop); second try with $0.50 cap returned 92 tokens of "tests confirmed green" — failed to follow the audit instructions |

**Total panel cost**: ~$0.74.  Two engines provided substantive critique; MiMo's behavior is itself a finding (below).

## The MiMo failure as a finding

MiMo-via-claude on this strategic-audit prompt:
1. Generated 17,600 input tokens to deliver 1,385 output tokens (12.7:1 input:output ratio).  Claude Code's internal agent loop is consuming the budget rather than running a single inference.
2. Second attempt returned 92 tokens of off-task text ("Test suite confirmed green").  This is not bare-mode behavior — the model is being given tool access (or thinks it has been) and is running tests instead of writing the audit.
3. At $0.35 / 92 useful tokens, this is **38× more expensive per useful token than DeepSeek** ($0.089 / 2291).

This single audit invalidates one of yesterday's smoke-matrix conclusions ("MiMo is most cost-efficient at $0.015 per request").  That was true for 100-200 token prompts.  For audit-class prompts with structured output, MiMo-via-claude is the most expensive engine by an order of magnitude.

**Action implied**: route audit-class workloads AWAY from MiMo until this is investigated.  Either MiMo's Claude Code subprocess is not respecting `--print --bare` correctly, or the endpoint enables tool-calling regardless of CLI flags.

## Convergent findings (both Kimi + DeepSeek)

Both substantive audits independently flagged the same concerns:

### 1. JSONL health ledger lacks atomic write, locking, and compaction

- **Kimi** (P1 risk): "JSONL append without atomic write or file locking on Windows means `coord/key_health.jsonl` will corrupt if the FastAPI server crashes mid-write or if concurrent requests hit the health tracker."
- **DeepSeek** (P1 risk): "key_health.jsonl grows unbounded. Every probe appends one line. ... pruning requires manual truncation a non-technical user can't do confidently."

Three sub-concerns:
- **No locking** — concurrent `record_outcome()` calls can interleave on Windows
- **No compaction** — operator running `probe-all` daily accumulates entries forever
- **JSONL is unreadable to non-technical operator** — opaque debugging surface

### 2. Concurrent writes to `key_policy.json` race

- **Kimi** (P4 risk): "Policy and health files live outside the tracked repo (`.harness/` vs `coord/`); a fresh clone or machine switch silently resets quarantines and strategy."
- **DeepSeek** (P5 risk): "Two simultaneous `harness keys policy set` invocations (e.g., from script + CLI) will race and one will silently overwrite the other. No file locking."

### 3. Recommender shipped on too thin a data sample

- **Kimi** (P3 next-move): "Quality regression test for v4-flash on actual audit panels.  Before flash becomes the blanket default, run a representative Pattern B audit through both `pro` and `flash`, score outputs with a cheap judge."
- **DeepSeek** (pushback): "Routing recommender shipped too early.  18 tests + new CLI verb, but underlying decision tree is based on *one* 3-run smoke matrix ($0.23).  That's not empirical — it's anecdotal."

**Convergence**: the v4-flash default is unvalidated for audit-quality work.  Today's audit itself supports this — DeepSeek v4-flash delivered substantive output in 36s and 2291 tokens.  But the smoke matrix tested short prompts; today's audit was the first test of v4-flash on a real audit-class prompt.

### 4. Missing operator-friendly affordance

- **Kimi** (P1 next-move): "'Ping key' button + $/1K token cost label in the Keys UI.  The operator shouldn't need the CLI to demystify a red badge."
- **DeepSeek** (P2 next-move): "Build a global keys health dashboard widget.  The operator's actual question is 'can I dispatch right now?'  Add a single row at the top of the Keys page showing green if every provider has ≥1 healthy key, yellow if degraded, red if any provider has zero healthy keys."

Both point at the same gap: the per-slot health badges are correct, but the operator needs a higher-level "am I ready to dispatch?" answer.

## Divergent / unique findings

### DeepSeek alone

- **Velocity concern**: 2 major subsystems in 1 day with zero soak time.  Multi-key data layer AND behavior layer landed before either was stress-tested in real dispatch.
- **Multi-key failover untested at integration level**: no test configures 2 keys, marks first unhealthy, dispatches, and asserts second key was used.
- **Security patches untested in browser**: 27 regression tests pass in isolation, but Origin-check + CSP + env-path resolution all changed in one commit; a live Playwright save-and-verify-permissions test is missing.
- **Recommender is CLI-only**: non-technical operator will type `harness engines recommend code-review` once and forget; needs to surface in dashboard.

### Kimi alone

- **Tier 2 over-engineered for solo operator**: "JSONL ledger with 24-hour quarantines and decay logic is enterprise SRE patterns ported to a personal Click CLI app."  Recommends in-memory flag + manual reset button instead.
- **Four config layers now exist**: `.env` keys + `key_policy.json` + `key_health.jsonl` + YAML task specs.  Cognitive load for a non-technical operator.
- **Security headers will break edge-case `file://` usage**: CSP + Origin check may force the operator to disable them, re-opening the holes.

## Where we are

After 6 commits and 86 new tests, the harness has:

- A no-code keys UI with multi-key pools per provider (✅ visually-verified)
- Per-key health tracking with auto-quarantine (✅ unit-tested; ❌ integration-tested)
- Failover policy per provider (rotation / priority / failover-only) (✅ unit-tested)
- Empirical routing recommendations available from CLI (⚠️ based on anecdotal data per DeepSeek)
- Hardened security across keys flow (✅ 27 regression tests; ⚠️ no browser smoke per DeepSeek)
- Visual-verify discipline documented and applied (✅)

## Where we should proceed — ranked recommendation

Both audits converge on three priorities.  Ranking them by leverage:

### Priority 1 — Harden the persistence layer (~2-3h)

Combines both engines' #1/#2 concerns into one commit:

1. Add file locking via `portalocker` or `fcntl`/`msvcrt`-shim to `record_outcome()` and `set_strategy()`
2. Add `harness keys health prune --keep-per-alias N` CLI verb (default keep last 50 per alias)
3. Make `harness keys probe-all` auto-prune as a side effect
4. Move `key_policy.json` from `.harness/` (per-machine) to `coord/` (committable) so cross-machine setups stay consistent — OR document why per-machine is correct and surface the location via the CLI
5. Atomic write throughout (tmp + replace, not append-only for JSONL or rewrite-in-place for JSON)

This eliminates the corruption surface that both engines independently flagged.

### Priority 2 — Add a global health dashboard widget + integration failover test (~3-4h)

Combines DeepSeek's #2 (global widget) + #3 (integration test):

1. Single status row at top of Keys page: "Ready to dispatch" (green if all providers have ≥1 healthy key), "Degraded" (yellow if any provider is degraded but still has a healthy key), "Blocked" (red if any provider has zero healthy keys).
2. Optional dispatch-gating: when status is red, the UI surfaces a banner with which provider is blocked.
3. New Playwright test: configure two DeepSeek keys (first deliberately invalid), dispatch a real Pattern B request, assert response generated + first key shows `auth-failed` badge + second key was used.

This closes the "wired up but untested end-to-end" gap.

### Priority 3 — Validate the v4-flash default + recommender data ($0.50, ~1h)

Run a representative Pattern B audit through:
- DeepSeek v4-flash (current default)
- DeepSeek v4-pro (explicit override)
- Kimi-via-claude (already used; ~$0.09)

Have Claude in-session score the three outputs on 4 axes (correctness, depth, calibration, concision) for the SAME audit prompt this panel used.  If v4-flash matches v4-pro within 1 axis, keep the default.  If v4-pro is materially better, change the default for `audit` task class only (keep v4-flash for `default` / `latency` / `cost`).

This addresses the "anecdotal data" pushback without burning huge cost.

## Deferred (queued, not immediate)

- **MiMo-via-claude budget bloat investigation** — 7-12× input-token inflation suggests Claude Code is running an agent loop where bare-mode is expected.  Worth ~1h.  Until resolved, route audit-class work away from MiMo.
- **Tool-use through `--print --bare`** — original queued gap, not yet closed.  ~1h.
- **Linux/macOS validation** — wrappers untested off-Windows.  ~1h.
- **Tier 2 simplification (per Kimi)** — replace JSONL ledger with atomic JSON if the prune work above doesn't satisfy the concerns.  Defer.

## Costing this audit

- Dispatch cost: $0.74 across 4 dispatches (3 engines + 1 MiMo retry)
- 2 substantive engine perspectives + 1 failure-mode finding
- Identified 3 priority moves backed by independent cross-engine consensus
- Time-to-result: ~10 min real time
