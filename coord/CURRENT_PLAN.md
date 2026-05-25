# Current strategic plan — xaxiu-harness

**Source**: 15-engine strategic panel (Round 2 final verdict, 2026-05-25)
**Full verdict**: [coord/reviews/strategic-planning-panel15-final-verdict/FINAL_VERDICT.md](reviews/strategic-planning-panel15-final-verdict/FINAL_VERDICT.md)
**Synthesized from**: 13/18 substantive engine voices (Round 1: 11/15; Round 2: 2/3 — MiMo unable to complete strategic-language synthesis)
**Combined confidence**: ~0.87
**Last updated**: 2026-05-25
**Last commit on update**: pending (W13-HARNESS-PLAN-VERB)

> **For agents**: this file is the active "what are we trying to ship right now" document. `coord/STATUS.csv` is the per-row task tracker; this file is the strategic narrative that explains why those rows exist. When the rows here disagree with `harness today`, trust `harness today` for current state and update this file.

---

## North star

**Horizon C internal tool, NOT commercial product** (operator directive 2026-05-25).
Solo internal use. Optimize for visible/overridable/auditable behavior.
Drop everything multi-user / plugin-marketplace / VPS-hosted / best-of-N-cost-multiplier.

---

## Where we are right now (as of 2026-05-25)

**Tag**: `v1.0.0-rc.1` (working toward `v1.0.0` final)
**Tests**: 2360 passed, 6 skipped (slow-marked install-verify), 0 failed
**Budget**: well under $5/session cap

### Shipped this week (Week 1 of the panel plan)

| Day | Row | Status | Commit |
|---|---|---|---|
| Mon | FUTURE-prefix sweep + CI gate | shipped | `734ad5b` |
| Mon | W13-INSTALL-VERIFY (universal #1 panel pick) | shipped | `014390d` |
| Tue | W13-AUDIT-JSONL + secret redaction (universal #2 panel pick) | shipped | `cbd6ae3` |
| Wed-Thu | `harness.review()` SDK + `harness.capabilities()` SDK + Tier 1 Shifts A+F (auto-lens-set + safe-floor max_tokens) | shipped | `81411a4` |
| Thu (bonus) | Doc-refresh + `tests/test_docs_mention_all_sdk_fns.py` (symmetric CI gate) + `harness plan show` verb | shipped | `4317fe8` |
| Fri | `W13-MORNING-BRIEF-CONTEXT-BUG` test fix + broaden `.harness/` + stop-hook gitignore | shipped | this commit |

---

## What's next

### Immediate (today / tomorrow)

1. **Friday re-run panel** — fire the same 3-engine (Kimi + DeepSeek + MiMo) panel against the v1.0.0-rc.1 state, now with a fully green 2360/2360 suite.
   - If ≥80% APPROVE → tag `v1.0.0` final.
   - If <80% → fix specific blockers called out by the panel, then re-run.

### Week 2 — Operations Hardening (~6-8h)

| Row | Effort | Why |
|---|---|---|
| W13-BACKUP-SECRETS-REDACT + W13-BACKUP-INTEGRITY (SHA256 verify) | M (3-4h) | DeepSeek panel finding: backup tar may contain API keys; restore must verify integrity |
| CI doc-doc-sync gate | S (1h) | Catch drift between AGENT_QUICKSTART + INTERNAL_OPERATOR_RUNBOOK + README |
| W13-DISK-PRUNE + W13-LOCK-DEPS | S+S (~4h) | Disk hygiene + dep-pin reproducibility |
| Auto-default guardrail CI framework | M (4-5h) | Every new auto-default must ship with a "what would happen if this were wrong" test |

### Week 3 — Polish + Nice-to-haves (~4-6h, optional)

| Row | Effort | Source |
|---|---|---|
| Schema versioning (when first data-structure change happens) | S | M3 + DeepSeek amendment 3 |
| `harness commands --did-you-mean` | S (~2h) | DeepSeek amendment 4 |
| Hallucination test harness | S (~2h) | DeepSeek amendment 6 |
| Tier 2 shifts (auto-retry, cost-cap pre-check, L5-inline in DispatchResult) — pick 1-2 | S each | DeepSeek amendment 5 |

### Deferred backlog (NOT this month)

- **W14-LOCAL-LLAMA-FALLBACK** — keep as outage insurance row; ship only if/when cloud-engine outage actually happens (DeepSeek amendment 1)
- Everything in the prior DROP list — W15 plugin architecture, W14-BEST-OF-N, W14-MISTRAL, W16 multi-user, W17 VPS-hosted-observer, W13-PLUGIN-SANDBOX-PLAN, W13-BACKUP-ENCRYPTION-FULL

---

## Confirmed anti-patterns (don't do these)

1. Don't ship auto-defaults before `W13-AUDIT-JSONL` lands. → ✅ already done; we have the ledger.
2. Don't add new CLI verbs without explicit ROI. → Defer to `harness capabilities` introspection where possible.
3. Don't auto-close observer flags (auto-escalate instead).
4. Don't merge `dispatch` + `review` (different intents, different return types).
5. Don't build plugin architecture for a solo internal tool.
6. Don't trust untested install paths. → ✅ W13-INSTALL-VERIFY now gates every PR.
7. Don't ship features that hide what the harness is doing — the visible/overridable/auditable trio is mandatory.

---

## Single most important action (live)

**Run Friday's re-panel. If ≥80% APPROVE, tag `v1.0.0` final.**

After v1.0.0 ships, the Week 2 hardening rows become the new "next" — but until v1.0.0 is tagged, the immediate question is binary: are we ready, or do we need to fix something the panel surfaces?

---

## How to update this file

This file is hand-maintained. Edit it directly when:

- A panel runs and produces a new forward plan (replace the "What's next" section)
- A row in the plan ships (move it from "What's next" to "Shipped this week" or delete if older than a week)
- A new strategic constraint is added (e.g., new operator directive)

`coord/STATUS.csv` is the per-row tracker; this file is the strategic narrative. Keep them consistent — if a row is in STATUS.csv as `shipped` but this file still shows it as todo, this file is stale.

For programmatic access, use `harness plan show` (renders this file to stdout) or `harness plan show --format json` (parsed sections).
