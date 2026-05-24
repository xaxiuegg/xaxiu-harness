<!-- persona=U5-cost-visibility status=OK (22566ms) -->

# U5-cost-visibility

## 1. Top 3 changes (ranked by leverage)

**① `harness today --costs` as default daily cost digest.** The morning command should include a one-line cost summary: "Yesterday: $4.17 across 3 engines (DeepSeek $0.40 subscription-equivalent, Kimi $2.10 tokens, Claude $1.67 tokens). Budget remaining: 73%." No ledger grepping. If the operator runs one command a day, they should see money spent. This surfaces cost in the one place they already look.

**② Live cost badge on `dashboard-serve`.** Add a persistent top-bar widget: running total for current session/day/month, color-coded (green <50% budget, yellow 50-80%, red >80%). Clicking expands into per-engine breakdown. Non-technical operators scan dashboards visually — make cost impossible to miss, not something buried in a CSV column they'd have to scroll to find.

**③ Subscription vs. per-token model explainer via `harness budget --eli5`.** A subcommand that prints: "DeepSeek: you pay $X/month regardless of usage — this is your 'unlimited' engine. Kimi: you pay per token — each dispatch costs ~$0.003. Claude: same as Kimi, ~$0.02 per dispatch." No jargon. No API-key talk. Just "flat-rate vs. metered" with concrete per-dispatch numbers the operator can hold in their head.

## 2. Wave 11 candidate

**`W11-COST-SENTINEL`**: An automated daily cost alert that fires when (a) any single dispatch exceeds 5× its engine's median cost, (b) daily spend crosses a configurable threshold, or (c) an engine switches from subscription to rate-limited mode (implying the subscription lapsed and costs are now metered). Acceptance criterion: a non-technical operator receives a plain-language Windows toast notification ("Kimi spend today hit $8 — your daily limit is $10. Review with `harness budget today`.") without ever opening a log file.

## 3. Feature to kill/hide

**`harness budget` raw CSV output.** The current ledger format (with ticket IDs, mutation hashes, token counts per 1K) should be behind `--format csv` or `--advanced`. The default `harness budget` should show only the ELI5 summary. Operators who need the spreadsheet export can ask their engineer to add the flag.

## 4. Minimum viable first-run path (≤5 steps)

1. `cd D:\xaxiu-harness-standalone`
2. `harness install` — wizard runs, picks engines, seeds DPAPI keys, prints "✅ 2 engines configured: DeepSeek (flat-rate), Kimi (per-token). Estimated daily cost: $3-5."
3. `harness preflight --fix` — handles git_clean, dead engines, prints green.
4. `harness today` — shows "Nothing shipped yet. Harness is idle. Run `harness loop start` to begin autonomous operation."
5. `harness loop start` — "Harness is running. Daily cost summary at 9am. Dashboard: http://localhost:8080."

## 5. Trust seam

**"Show me yesterday's bill."** The one trust signal that matters: a single command (`harness budget yesterday`) that prints a receipt-style summary — total, per-engine, per-dispatch average — that matches what the operator would see on their actual API billing page. If the numbers align with reality, they trust the harness. If they diverge, everything else is suspect. Build the surface to always reconcile with the upstream provider's actual charges, and make the reconciliation visible ("Kimi dashboard shows $4.12; harness ledger shows $4.12 ✓").
