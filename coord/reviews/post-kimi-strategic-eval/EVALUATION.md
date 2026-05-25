# Post-Kimi strategic evaluation: is the harness worth continuing?

**Date**: 2026-05-25
**Trigger**: Operator question after Kimi termination + provider-allowlist survey: *"the harness would only be valuable if we have subscriptions ai plans. evaluate the harness and its purpose yet, identify the price alternatives."*

**Format**: Honest assessment, not advocacy. The operator has invested ~13 waves into this project. The right answer might be "keep building", "narrow scope", or "wind down." This doc shows the numbers, then names the trade-offs.

---

## The data — what the harness is actually doing

Pulled from `state/engine_performance_log.jsonl` (2745 dispatch events, 30-day window):

| Category | Events | Notes |
|---|---|---|
| **CI / test fixtures** | 1,033 | 94% of all dispatches. Projects: `valid-project` (881), `harness-planner` (67), `wave9` (46), `harness-worker` (39). These run every PR. |
| **Real production** | 83 | The actual operator workload. Project: `observer` (71 automated background audits) + `default` (12 ad-hoc, mostly today's panels). |
| **Active production days** | 4 of last 30 | Most days the operator isn't dispatching anything to a real engine. |

**Per-day production load on active days**: ~20 dispatches.
**Per-month production load**: ~83 dispatches × ~30k tokens average = ~2.5M tokens/month.
**Bytes of code maintained for this**: 28,807 LOC of Python in `src/harness/` + 2,419 tests.

That's roughly **350 LOC + 30 tests per real-production dispatch per month**. The operator built a lot of infrastructure for a small actual workload.

---

## The original hypothesis (now falsified)

The harness was built around three assumed advantages:

| Assumption | Reality |
|---|---|
| **(1) Subscription arbitrage**: flat-rate Kimi/MiMo/Claude subscriptions are cheaper than PAYG for heavy use | Kimi terminated us 2026-05-25 (TOS violation — UA spoofing). Anthropic banned third-party tools on OAuth Feb 2026. Xiaomi MiMo Token Plan is advisory-lax for now but matches Kimi's pre-termination posture. **Even if all subscriptions worked**, the operator's actual usage (~2.5M tokens/mo) is not heavy enough to justify $30-100/mo flat — PAYG at this volume costs cents to dollars. |
| **(2) Multi-engine cross-validation**: same prompt to multiple engines catches blind spots one engine alone misses | **Genuinely real and unique**. Today's release-gate panel + master-plan panel both demonstrated this — DeepSeek + MiMo independently arrived at APPROVE and surfaced different concerns. No mainstream tool (Claude Code, Cursor, Aider) does parallel multi-engine panels with synthesis. |
| **(3) Forensic-grade audit + observability** | Real but rarely-needed. The audit ledger was hit 309 times in 30 days but 100% of those were `mock` engine fixture events. The ledger has not yet been used for an actual incident response. |

**Bottom line**: assumption (1) is dead. Assumption (2) survives but represents a niche, not a general use case. Assumption (3) is theoretical insurance that hasn't paid off yet.

---

## PAYG vs subscription math at actual operator usage

Monthly cost across realistic usage scenarios (at May 2026 prices):

| Provider / model | $/M tokens (in/out avg) | 500K tokens | 2.5M tokens (actual) | 10M tokens |
|---|---|---|---|---|
| **DeepSeek V4 Flash** (PAYG) | ~$0.21 | $0.11 | **$0.53** | $2.10 |
| **Gemini Flash** (PAYG) | ~$0.19 | $0.10 | $0.48 | $1.90 |
| **GLM-5.1 PAYG** | ~$1.30 | $0.65 | $3.25 | $13.00 |
| **MiMo PAYG** (sk- keys) | ~$1.50 | $0.75 | $3.75 | $15.00 |
| **Anthropic Haiku** | ~$0.75 | $0.38 | $1.88 | $7.50 |
| **Anthropic Sonnet** | ~$9.00 | $4.50 | $22.50 | $90.00 |
| **OpenAI GPT-5.2** | ~$10.00 | $5.00 | $25.00 | $100.00 |
| **Anthropic Opus** | ~$45.00 | $22.50 | $112.50 | $450.00 |
| **Claude Pro subscription** | flat | $20 | $20 | $20 (rate-limited) |
| **Claude Max subscription** | flat | $100-200 | $100-200 | $100-200 |
| **Kimi Token Plan** (DEAD) | flat | $30-100 | $30-100 | $30-100 |
| **Cursor / Continue.dev subscription** | flat | $20-40 | $20-40 | $20-40 |

**At the operator's actual ~2.5M tokens/month**:

- DeepSeek-PAYG-only operating cost: **~$0.50/month**
- Even all-Sonnet PAYG: **~$22/month** (cheaper than Claude Pro)
- All-Opus PAYG: $112/month (cheaper than Claude Max)
- Kimi Token Plan was $30-100/mo for a workload that costs $0.50/mo via DeepSeek PAYG

**The harness was solving a problem the operator didn't have.** Even at 10× current usage, PAYG on cheap Chinese models stays under $20/mo. Subscriptions only win above ~10M tokens of premium-model usage per month, which is closer to professional-developer territory than solo-internal-tool territory.

---

## What part of the harness has genuine, unique value?

Walking the 28k LOC by subsystem:

| Subsystem | LOC | Genuine value | Verdict |
|---|---|---|---|
| **Multi-engine panel scripts** (`scripts/v1_release_gate_panel.py`, `post_v1_master_plan_panel.py`, `strategic_final_verdict_panel.py`) | ~500 | **Yes — unique**. Same-prompt parallel dispatch + verdict synthesis isn't replicated in Claude Code / Cursor / Aider. | **Keep + invest** |
| **Engine adapters** (`engines/*.py`) | ~3,000 | Partial. Each adapter is a thin OpenAI-compat wrapper — could be 50 LOC each if not for streaming + retry + UA gating + body excerpts. | **Keep + simplify**. Most engines are interchangeable OpenAI-compat; one shared adapter would cover 80%. |
| **Audit JSONL** (`audit_jsonl.py`) | ~400 | Yes — but only the panel scripts actually use it for real-engine traffic. The dispatch SDK path captures it for `harness.dispatch()` callers, but operator rarely uses that. | **Keep, slim** |
| **Engine-failure visibility** (`cli_helpers.py` probes + `engines failures` CLI, just shipped W13) | ~500 | Yes — caught the Kimi termination today. | **Keep** |
| **Coord layer** (`coord/coordinator.py`, `worker.py`, `worktree.py`, etc.) | ~3,500 | Real for warehouse-style multi-agent work, but barely used in this project itself (0 real dispatches via coord in 30 days). | **Keep for warehouse, otherwise inert** |
| **CLI** (`cli.py`) | **5,287** (single file!) | 50+ verbs. Per `harness engines failures` data, only ~5 are actually used in real production sessions. | **Cut hard**. The dev-loop, observer, dashboard, proxy, agent, advanced, daily verbs are all dead weight given actual usage. |
| **Dashboard** (`dashboard/*.py`, FastAPI + WebSocket) | ~1,500 | The dashboard has not been opened in any way the audit log can confirm. Theoretical operator-UX win. | **Drop** unless operator says "I want this". |
| **Observer** (`observer/*.py`) | ~1,200 | Generates the 71 automated audit packets that dominate the real-production traffic. Useful but the value is "background QA" not "harness UX". | **Keep, but evaluate vs simpler cron**. |
| **Dev-loop** (`loops/*.py`, `coord/dev_loop/*`) | ~2,000 | Designed for autonomous overnight runs. The operator runs Claude Code interactively now, so this is mostly dormant. | **Drop or archive** |
| **Adapter schema + NL→YAML** (`adapters/*.py`) | ~1,000 | A configurability subsystem for routing rules. The operator uses one config; doesn't need YAML schema validation. | **Drop or fold into a simple JSON file** |
| **Proxy** (`proxy/*.py`) | ~1,200 | Stateful 4-key proxy + circuit breaker. Built for high-volume, never used for real production. | **Drop** |
| **State / SQLite / DPAPI / lock files** | ~2,500 | Real but most of it serves subsystems that are themselves on the cut list. | **Slim** |
| **Tests** | 2,419 | Comprehensive coverage of the whole surface. Most of these are testing features that wouldn't survive a scope cut. | **Halve** post-cut |

**Honest summary**: the harness's unique value is **~5,000 LOC** (panels + engine adapters + audit + engine-failure-visibility). The other ~23,000 LOC is infrastructure for features the operator doesn't actually use.

---

## Three honest paths

### Path A — KEEP and INVEST: narrow the harness to its panel niche

Cut everything that isn't load-bearing for the multi-engine panel pattern. Result:

- ~5,000 LOC harness, ~500 tests
- Verbs: `dispatch`, `engines`, `audit`, `today`, `plan show`, `capabilities`, `panel` (new)
- Drop: dashboard, dev-loop, observer (or evict to cron), proxy, coord/worker (move to warehouse repo), adapter schema, autonomous-loop modes

**Effort to ship**: 2-3 weeks of cleanup work (delete code, archive subsystems, update docs).

**Why this might be worth it**: the panel pattern IS unique and the operator clearly uses it (today's release-gate + master-plan + provider-survey). If panels become a regular workflow, a clean ~5k LOC tool is well worth maintaining.

**Why this might NOT be worth it**: 2-3 weeks of cleanup is the cost. And the operator might do exactly 2 more panels and then stop.

### Path B — WIND DOWN: use Claude Code + DeepSeek PAYG, retire most of the harness

Realistic stack the operator could move to today, by use case:

| Use case | Replacement | Monthly cost |
|---|---|---|
| Daily interactive coding | **Claude Code** with Claude Pro ($20/mo) or Claude API PAYG | $20 sub OR ~$5-20 PAYG |
| Quick batch dispatch | Direct `httpx.post` to `api.deepseek.com` (1 file, ~30 LOC) | $0.50 PAYG |
| Multi-engine panel (occasional) | Keep the ~200-LOC panel scripts as standalone, ditch the rest | $0 |
| Background audits (observer) | Cron job + shell script + DeepSeek PAYG | $0.50 PAYG |
| Multi-agent coord (warehouse work) | The `coord/` subsystem moves to the warehouse repo as a separate lib | $0 (already exists) |
| Engine health visibility | Just check the provider's dashboard when something fails | $0 |

**Total monthly cost**: ~$20-30/month (mostly the Claude Code subscription).

**Effort to ship**: ~1 week. Archive the harness, extract the panel scripts + coord lib, write a short "what to use instead" guide.

**Why this might be the right move**: the harness's core competitive frame (subscription arbitrage) is dead, the operator's actual usage doesn't justify the complexity, and Claude Code + Cursor + Aider have all matured to cover the daily-coding use case well.

**Why this might be wrong**: the operator has invested ~13 waves into this. The sunk-cost is real (not financially, but as understanding of the problem space). Path B is "deletes most of the work."

### Path C — PAUSE INVESTMENT, keep what exists

Ship no further W14+ work for now. v1.0.0 is tagged, tests pass, no maintenance burden. The harness sits at v1.0.0 in working condition.

For the next 4-8 weeks, the operator uses:
- **Claude Code subscription** for daily coding (or whatever editor they prefer)
- **DeepSeek API PAYG** for any one-off batch dispatch (`harness.dispatch` still works, or just curl)
- **Existing harness panel scripts** when they actually need a multi-engine panel
- **No new features**

At the 4-8 week mark, review usage:

- **Did the harness's unique features get used?** If yes → Path A (invest in narrowing it).
- **Did the operator just default to Claude Code and never reach for the harness?** If no → Path B (wind down).
- **Was it useful but not heavily?** → Path C continues. Eventually move to A or B.

**Effort**: ~0 hours. This is the do-nothing-deliberately option.

**Why this is the rational default**: the operator just spent 13 waves shipping v1.0.0, then discovered the foundational hypothesis was off. The right response to "your model is wrong" is usually not "rush to fix it" — it's "collect data on what the model should be next." Path C buys that observation period for free.

---

## My honest recommendation

**Path C (pause investment, observe usage) followed by Path A or B at 4-8 weeks.**

Reasoning:

1. The Path A/B decision depends on data we don't yet have — *will the operator actually use multi-engine panels regularly, or was today's a one-off?* Right now we'd be guessing.

2. v1.0.0 is shipped, tested, and zero-maintenance until something breaks. There's no time pressure to make the strategic call this week.

3. The Week 2 master-plan rows (W14-AUDIT-CHAIN-HMAC, W14-DISPATCH-HEALTH-AWARE-FALLBACK, W14-BACKUP-MANAGER, W14-KEY-ROTATION-PLAYBOOK, W14-PARALLEL-DISPATCH-RETRY-FIX, W14-KIMI-REPLACEMENT-WITH-GLM) were predicated on the harness being load-bearing. If we're not sure the harness is load-bearing, these rows are premature. **Hold Week 2 pending the strategic decision.**

4. The one Week 2 piece that's worth shipping NOW is **engine-failure-visibility hardening** (already shipped today). That's foundational regardless of whether the harness continues — it tells the operator when ANY engine they use (harness-mediated or direct) is in trouble.

5. The operator already has the data they need to make this call eventually. The audit log + engine performance log are tracking usage. In 4-8 weeks, the data will say "I run panels X times per month" or "I never ran a panel after the v1.0.0 hype died down." The data picks Path A or B for you.

### Specific actions for this week

1. **Mark Week 2 master-plan rows as PAUSED (not dropped, not active)**: edit `coord/CURRENT_PLAN.md` to add a "Strategic pause" section noting that W14 work is held pending the usage-based decision in 4-8 weeks.

2. **No further engine adapters until the decision lands**: defer W14-KIMI-REPLACEMENT-WITH-GLM. If the operator decides Path B, this row is moot. If Path A, we'll have better signal on whether GLM is even needed.

3. **Keep the harness installed and runnable**. v1.0.0 stays operational. No archival yet.

4. **Add a simple use-tracking dashboard**: 5-line script that counts real-production dispatches per week and emits a tiny report. This is the data we need for the Path-A-vs-B decision. (Could literally be a one-line cron `python -m harness engines failures --since-hours 168 > weekly-usage.log`.)

5. **Switch the operator's daily workflow to Claude Code (or whatever they prefer)** for everyday work. Use the harness only when its unique features (panels, multi-engine sync, audit forensics) actually matter.

### What this DOESN'T mean

- Not retiring the harness today
- Not deleting any code
- Not abandoning v1.0.0 — it stays as a working release
- Not saying the 13 waves were wasted — the harness's panel pattern is genuinely novel and the operator now understands the problem space much better than at wave 1

This is a "stop digging" recommendation, not a "throw away the shovel" one.

---

## Cost projection at each path

Assuming the operator's usage stays at ~2.5M tokens/month:

| Path | Monthly cost (engines) | Monthly cost (subscriptions) | Total |
|---|---|---|---|
| **A — Narrow harness + DeepSeek PAYG** | $0.50 | $0 (or $20 Claude Pro for daily IDE) | **$0.50-20** |
| **B — Claude Code + ad-hoc scripts** | $0.50 | $20-200 Claude Pro/Max | **$20-200** |
| **C — Status quo + observe** | $0.50 | $0 (or $20 Claude Pro for daily) | **$0.50-20** |

The "subscription arbitrage" frame was always a phantom. **At the operator's actual usage, the cheapest paths cost less than $1/month.** Anything more expensive than that is buying convenience (Claude IDE integration, panel polish), not raw token throughput.

---

## What I'd push back on

If the operator says "I want to keep building the harness — let's do W14 work this week" — I'd ask one question: **what specific use case in the next 30 days requires features that v1.0.0 doesn't already have?**

If there's a concrete answer (e.g., "I need the HMAC audit chain because I'm going to be reviewed by [external party]"), ship that one row. If the answer is "I want to be ready for future needs" — Path C is the better answer. v1.0.0 is ready for unknown future needs; W14 polish is not.

---

## Sources

- `state/engine_performance_log.jsonl` (this repo, 30-day window)
- `~/.harness/audit.jsonl` (this repo, all 309 events are mock)
- `coord/reviews/provider-allowlist-comparison/COMPARISON.md` (the previous research that triggered this evaluation)
- `coord/reviews/kimi-termination-investigation/FINDINGS.md` (the trigger event)
- Pricing data from the May 2026 provider survey (cited in COMPARISON.md)
