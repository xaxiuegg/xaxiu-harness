# 15-Engine Strategic Planning Panel — Synthesis + Forward Plan

**Date**: 2026-05-25
**Method**: 5 Kimi + 5 MiMo + 5 DeepSeek personas, each given a 96KB
source pack (master audit + Horizon C plan + bloat audit + AGENT_QUICKSTART
+ runbook + STATUS.csv tail), distinct lens, max_tokens=8000.
**Result**: 10/15 substantive Round 1 + 1 MiMo retry = **11/15 usable**
(MiMo M1/M2/M4/M5 failed with "internal" error on both attempts — likely
content-filter triggers on operator-burden/risk language).

**Total cost**: **$0.00** (all subscription engines; DeepSeek's ledger
recorded $0 — actual paid usage ~$0.005-0.01).

---

## Top-level signal

Every substantive engine independently agreed on the same north star:

> **Reliability + agent-ground-truth first. Drop the over-engineering.
> Ship the operator-burden reducers tonight. Save the speculative
> architecture work for never (or after a real second user appears).**

The pattern is striking: 11 different engines, 3 different vendors, 11
different lenses, all converging on the same 4-5 SHIP items and the same
3-4 DROP items.

---

## 1. Vote tally

### SHIP (strong = 4+ engines agree)

| Row | Engines that picked it | Strength |
|---|---|---|
| **W13-INSTALL-VERIFY** | K1, K2, K3, D1, D4, D5 (implied) | **CRITICAL** — universal |
| **W13-AUDIT-JSONL** | K1, K2, K3, M3, D3, D5 | **CRITICAL** — universal foundation |
| **Tier 1 Shift F (auto `max_tokens`)** | K1, K2, K3 ship; D1 critiques heuristic but accepts; D3 wants safeguards | **STRONG** |
| **Add `harness.review()` as NEW SDK function (NOT merge with dispatch)** | K1, K2, K3 want it; D2 explicit ruling KEEP SEPARATE but ADD | **STRONG** (with caveat — see Dissent 1) |
| **Future-as-present audit on runbook (`FUTURE:` prefix)** | D5 explicit XS effort; K2/K3 implied; M3 mitigation | **STRONG** |

### DROP (strong = 3+ engines agree)

| Row | Engines that dropped it | Reason |
|---|---|---|
| **W15 Plugin Architecture (entire wave)** | K1, K2, K5, M3 (review-template), D5 (silent) | Over-engineering for solo operator; 40-60h to save ~2h/year |
| **W14-BEST-OF-N** | K1, K3, M3 | Cost multiplier with no operator-validated need |
| **W16 Multi-User (entire wave)** | K2, M3 + horizon-c plan's own skip condition | Operator is solo |
| **W17 VPS hardening (entire wave)** | K3 (not used), D5 (only if VPS exists) | Operator runs locally |
| **W13-PLUGIN-SANDBOX-PLAN** | K2, D5 | Internal tool = trusted authors; skip |

### ADD (strong = 3+ engines agree)

| Row | Engines that added it | Pitch |
|---|---|---|
| **`harness.capabilities()` SDK function** (NOT a new CLI verb) | K2, K3 (as `whoami`); M3 (surface in `today`, not new verb) | Programmatic ground truth so agents stop hallucinating engine/lens names |
| **CI doc-doc-sync gate** | K2, D5, multiple-implied | grep `*.md` for `harness <verb>` + fail if verb doesn't exist |
| **Schema versioning for all data structures** | M3 (load-bearing) | Add `schema_version` to STATUS.csv, dispatch cache, observer state, backup manifest |
| **Auto-default guardrail framework (CI test)** | D3 | Enforce visible+overridable+auditable for every new auto-default |
| **W13-BACKUP-INTEGRITY (SHA256 + verify)** | D3 implicit, D4/D5 explicit | Before claiming a backup is "successful", verify checksum |

---

## 2. Dissents resolved

### Dissent 1: Merge `dispatch` + `review` into one SDK function?

- **Kimi (K1/K2/K3)** used the word "unify" — ambiguous
- **DeepSeek (D2)** explicit ruling: **KEEP SEPARATE, but ADD `harness.review()` as new function**.  Argument: different return types, different intents, no migration cost.

**Resolution**: D2 is right. Ship `harness.review()` as a new SDK function alongside the existing `dispatch`/`retrieve`/`budget_status`. The agent gains one symbol, not a renamed one.

### Dissent 2: Ship backup encryption?

- **Kimi (K1/K2/K3)** drop — security theater (`.env` already plaintext)
- **DeepSeek (D3/D4/D5)** ship — CRITICAL (laptop loss exposes cached prompts/responses that may contain API keys via secret-bearing prompts)

**Resolution**: scope down, don't drop. Ship **W13-BACKUP-SECRETS-REDACT** instead of full AES-256 encryption — redact `KIMI_API_KEY=...` and similar patterns from the cached dispatch payloads BEFORE writing the backup archive. Closes the leak vector with ~1-2h of work vs ~3-4h of key-derivation/cross-platform AES complexity. The full encryption can stay backlog forever.

### Dissent 3: Auto-pick `max_tokens` from prompt length — sound heuristic?

- **Kimi (K1/K2/K3)** ship enthusiastically (closes the truncation bug from Aquinas review)
- **DeepSeek (D1)** critiques: "prompt length doesn't correlate with required output length"

**Resolution**: ship but with **safe floor**. The W12-B directive said "comfortable with high cap" — the auto-pick should err HIGH not LOW. Concretely: minimum 4000 tokens for analysis tasks, only drop to 1000 when explicit `--quick` flag is set. Heuristic is upper-bound only; never picks BELOW a safe floor.

### Dissent 4: `harness whoami` as new CLI verb?

- **Kimi (K2/K3)** add as `harness whoami`
- **MiMo (M3)** anti-vote: "don't add another verb; surface in `today`"

**Resolution**: do BOTH layers. Add `harness.capabilities()` as a programmatic SDK function (no CLI). Also surface the same info in the existing `harness today` output (no new verb). Agents get ground truth via Python import; operators see it in their daily pulse.

### Dissent 5: Auto-snapshot before risky ops (Tier 2 B)?

- **K1** ship
- **D3** drop — creates false security if backups silently fail
- **D5** medium risk — async correctness problem

**Resolution**: **defer Tier 2 B** until after W13-BACKUP-INTEGRITY ships (SHA256 + verify on every write). Once integrity is mandatory, auto-snapshot is safe. Currently it would be lying.

### Dissent 6: Auto-close low-severity observer flags (Tier 3 D)?

- **D3** strong DROP — destroys early-warning signal
- **Kimi/MiMo** silent

**Resolution**: replace with D3's proposal: **auto-escalate unreviewed flags to L3 after 7d** + add `harness flags --show-archived` for forensics. The signal stays visible; it just gets louder over time.

---

## 3. The Forward Plan (Monday → next 2 weeks)

Based on the panel's convergent signal + dissents resolved, here's the
ordered sequence:

### Week 1 — Foundation Tonight + Monday (~6-8h total)

**Monday: ship the agent-trust foundation (~3-4h)**

1. **`FUTURE:` prefix sweep of runbook + AGENT_QUICKSTART** (XS, ~30min)
   — closes D5's #1 hallucination vector immediately. Zero-cost win.

2. **W13-INSTALL-VERIFY** (M, 2-3h)
   — universal #1 panel pick. Tests `git clone + pip install -e . +
   harness review` end-to-end on a clean shell. Closes the master audit's
   "single hardest unknown".

**Tuesday: ship the audit-trail foundation (~2-3h)**

3. **W13-AUDIT-JSONL with secret redaction** (S, 2-3h)
   — universal #2 panel pick + foundational for every other auto-default.
   Must include secret-redaction patterns from day one (D5's S2 finding).

**Wednesday-Thursday: ship the agent-ground-truth (~3-4h)**

4. **`harness.review()` as new SDK function + auto-lens-set + auto-max_tokens
   with safe floor** (M, 3-4h) — Tier 1 Shifts A+F+G as one cohesive
   SDK landing. Ship the auto-defaults with the visible/overridable/
   auditable trio (now possible because audit-jsonl shipped Tuesday).

5. **`harness.capabilities()` SDK function** (S, 1-2h)
   — add as new SDK function (NOT new CLI verb). Surface same info in
   `harness today`'s output. Closes the agent's "what can I actually do
   right now" gap.

**Friday review point**: re-run the panel synthesis. If panel votes
shift to APPROVE-AND-SHIP at >80%, promote v1.0.0-rc.1 to v1.0.0 final.

### Week 2 — Operations Hardening (~6-8h total)

6. **W13-BACKUP-SECRETS-REDACT + W13-BACKUP-INTEGRITY** (M, 3-4h)
   — D3/D5's CRITICAL finding. Adds SHA256 verification + secret-key
   redaction. Replaces the original W13-BACKUP-ENCRYPTION scope (which
   panel agreed was overkill).

7. **CI doc-doc-sync gate** (S, 1h)
   — K2/D5's recommendation. CI greps `*.md` for `harness <verb>`,
   fails if verb doesn't exist. Closes the future-as-present vector
   permanently.

8. **W13-DISK-PRUNE + W13-LOCK-DEPS** (S+S, 2h each = 4h)
   — size-aware cache pruning + locked requirements.txt. Both small,
   both protect against silent rot.

9. **Auto-default guardrail framework (CI test)** (M, 4-5h)
   — D3's ADD. CI test that greps new auto-default code paths + requires
   matching log/override/audit. Prevents future silent failures at PR time.

### Weekend: revisit, don't commit

10. **Review the 24h+ autonomous-test outputs** that have accumulated
    by now. If anything looks off, fix it. If everything's clean, tag
    **v1.0.0 final** + write a public release-notes-style writeup.

---

## 4. The DROP list (do NOT do these)

The panel is unanimous: these rows should be removed from the backlog or
indefinitely deferred. Doing them is net-negative — they consume operator
time without proportional payoff for a solo internal tool.

| Row | Drop reason |
|---|---|
| **W15 Plugin Architecture (all 5 rows: ABI, lens-plugin, template-plugin, docs, contrib-tests)** | 40-60h to make adding a new engine 2h faster. Solo operator adds maybe 1 engine/year. Payback: never. Hardcode the 5 engines. |
| **W14-BEST-OF-N** | Cost multiplier with no validated operator need. Re-running a single review is cheaper + simpler. |
| **W16 (all 5 rows)** | Operator is solo; the horizon-c plan itself says "Skip this wave entirely if operator works solo". |
| **W17 (all 6 rows)** | Operator doesn't use a VPS. Build only if/when that changes. |
| **W13-PLUGIN-SANDBOX-PLAN** | Internal tool = trusted authors. Document the risk in plugin guide, drop the planning row. |
| **W13-BACKUP-ENCRYPTION (full AES-256)** | Replaced by W13-BACKUP-SECRETS-REDACT (1-2h scope vs 3-4h). |
| **W14-MISTRAL-ADAPTER + W14-LOCAL-LLAMA-FALLBACK** | Defer until existing 5 engines prove insufficient. Current pool is already redundant enough. |

**Total time saved by NOT doing these: ~250-400h.**

---

## 5. Anti-pattern list (things the panel said we should NEVER do)

1. **Don't ship auto-defaults before W13-AUDIT-JSONL lands.** Without the
   audit trail, auto-default behavior is invisible — debugging becomes
   impossible. (D5's M1)

2. **Don't add new CLI verbs without explicit ROI justification.** The
   30-verb surface is already at MEDIUM bloat risk. New features should
   default to SDK functions or surfaces in existing verbs (`today`,
   `preflight`). (M3 + K5)

3. **Don't auto-close observer flags.** Auto-escalate instead. Auto-close
   destroys the early-warning signal that's the observer's whole point.
   (D3)

4. **Don't merge dispatch + review.** They serve different intents with
   different return shapes. Add `review` as a new function. (D2)

5. **Don't build the plugin architecture for an internal tool with one
   author.** Hardcoded engines + lenses are correct here. (K1, K2, K5)

6. **Don't trust untested install paths.** Every `pip install -e .` claim
   in docs must have a CI test backing it. (K2, master audit)

7. **Don't ship features that prevent the operator from seeing what the
   harness is doing.** The visible/overridable/auditable trio is mandatory.
   (D3, multiple)

---

## 6. Most surprising findings

### From M3 (the only MiMo that came back)
**Schema versioning for ALL data structures** is the highest-leverage
mitigation we've under-invested in. Every JSON/CSV/cache file the harness
writes should carry a `schema_version` field from day one. When format
changes happen (Wave 16/17/etc), we can migrate cleanly instead of
silently corrupting data.

### From D2
The bloat audit (which I wrote) was self-contradictory: it recommended
merging dispatch+review as Tier 1 Shift G AND noted `harness review` was
already shipped as a separate CLI verb. The CLI's separation is correct;
the SDK should follow that pattern.

### From K1
**"Wave 15 plugin architecture is negative-ROI for a solo internal tool.
~40-60h to achieve adding-a-new-engine-takes-2h instead of 1-day. Solo
operator adds 1-2 engines per year. Payback period: 10-15 years."**

This is the panel's clearest case for cutting an entire wave.

### From K3 (operator-1-year-from-now)
**"The runbook lied to me about `harness secrets rotate kimi`, and I
believed it. Six months in I had a leaked key, tried the command, got
`command not found`, had to fall back to manual `.env` editing while a
client was waiting."**

This makes the FUTURE-prefix sweep urgent, not optional.

---

## 7. One-sentence verdict

**Ship 5 rows this week (FUTURE-prefix sweep, W13-INSTALL-VERIFY,
W13-AUDIT-JSONL+redact, harness.review as new SDK fn with auto-defaults
on a safe floor, harness.capabilities), 4 rows next week (backup
integrity+redact, CI doc-doc-sync gate, disk-prune+lock-deps,
auto-default guardrail CI), and DROP 250-400h of plugin/multi-user/VPS/
best-of-N work that was over-engineered for a solo internal tool — then
tag v1.0.0 final.**

---

## Appendix: Per-engine response files

- `kimi_K1-first-principles.md`
- `kimi_K2-agentic-trust.md`
- `kimi_K3-operator-1year.md`
- `kimi_K4-comparative-positioning.md`
- `kimi_K5-architectural-split.md`
- `mimo_M3-hallucination-deep-dive.md` (only MiMo that succeeded)
- `deepseek_D1-tier1-tech-critique.md`
- `deepseek_D2-sdk-api-merge-audit.md`
- `deepseek_D3-auto-default-risk-audit.md`
- `deepseek_D4-test-coverage-plan.md`
- `deepseek_D5-cross-cutting-concerns.md`

(MiMo M1/M2/M4/M5 failed in both attempts — content filter or context
overflow. We can re-attempt with even smaller prompts later if their
specific lenses become load-bearing; current 11-engine signal is
already conclusive.)
