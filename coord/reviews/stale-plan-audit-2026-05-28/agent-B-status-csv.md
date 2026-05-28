# Agent B: STATUS.csv staleness audit (2026-05-28)

## Method

- Source: `coord/STATUS.csv` (537 rows total, columns: ID, Category, Title, Status, Owner, Effort, Updated, Notes)
- Filter: `Status NOT IN ('shipped', 'wontfix')` AND `ID ~ ^(W1[2-9]|W[AB])`
- Per-row protocol applied: (1) grep `src/harness/` for the capability described in Title + Notes (not just the row ID); (2) cross-reference STATUS.csv shipped rows by capability keyword; (3) check the src/harness/ file mentioned in Notes (if any).
- **Total candidates after filter: 8** (small enough to investigate each fully)

Candidates:

| ID | Status | Updated |
|---|---|---|
| W12-B-MAX-TOKENS-DEFAULT-RAISE | todo | 2026-05-25 |
| W13-BACKUP-ENCRYPTION | todo | 2026-05-26 |
| W13-PLUGIN-SANDBOX-PLAN | todo | 2026-05-26 |
| W13-VPS-OBSERVER-NAT-PLAN | todo | 2026-05-26 |
| W13-BEST-OF-N-COST-CAP | todo | 2026-05-26 |
| W14-KIMI-AUTH-RESTORE | todo | 2026-05-25 |
| W14-KIMI-REPLACEMENT-WITH-GLM | todo | 2026-05-25 |
| W14-SWARM-CLAUDE-BACKENDS-PROPOSAL | queued | 2026-05-26 |

## Stale findings (rows that should be marked shipped / wontfix)

### Finding 1: W14-KIMI-REPLACEMENT-WITH-GLM

- **STATUS says** (verbatim Title): *"Drop Kimi from default pool + add GLM-5.1 (Zhipu) as new engine adapter"*. Status=`todo`, Updated 2026-05-25, Effort ~5h. Notes (excerpt): "src/harness/engines/glm.py NEW (or extend concrete.py): GLMConcrete(StreamingTransport) adapter ... Models: glm-4.5-flash (cheap) / glm-5.1-coding (default)."
- **Reality**: This row was explicitly **renamed** to `W14-KIMI-REPLACEMENT-WITH-QWEN` by the strategic re-evaluation row `W14-ENGINE-COST-USAGE-MATRIX` (shipped 2026-05-25). Verbatim from that row's Notes: *"row W14-KIMI-REPLACEMENT-WITH-GLM RENAMED to W14-KIMI-REPLACEMENT-WITH-QWEN"*. The Qwen adapter then shipped 2026-05-28 as `W14-KIMI-REPLACEMENT-WITH-QWEN-SCAFFOLD` (status=shipped, ~1h, Tier 1D). GLM does not need a separate adapter — the slot was already taken by Qwen and the strategic rationale (open-weight, low-cost, OpenAI-compat) was satisfied. A `claude-glm` wrapper exists for the alternate Anthropic-API path: `src/harness/engines/wrapper_scripts.py:77-83` (claude-glm wrapper definition) and `src/harness/engines/wrapper_scripts.py:102` (glm-via-cc endpoint at https://api.z.ai/api/anthropic).
- **Evidence**:
  - `coord/STATUS.csv` rows `W14-ENGINE-COST-USAGE-MATRIX` (2026-05-25, shipped) and `W14-KIMI-REPLACEMENT-WITH-QWEN-SCAFFOLD` (2026-05-28, shipped).
  - `src/harness/engines/wrapper_scripts.py:77-90` (claude-glm + claude-qwen wrappers).
  - `src/harness/engines/concrete.py:1` (QwenConcrete adapter class shipped per the SCAFFOLD row's Notes — "src/harness/engines/concrete.py QwenConcrete(Engine) class").
- **Verdict**: SHIPPED-UNDER-DIFFERENT-NAME (the Kimi-replacement role is filled by Qwen; GLM remains an optional alternate via Pattern B wrapper).
- **Suggested action**: Set ID `W14-KIMI-REPLACEMENT-WITH-GLM` Status=`wontfix` with Notes appended: *"Superseded 2026-05-25 by W14-ENGINE-COST-USAGE-MATRIX which renamed this row to W14-KIMI-REPLACEMENT-WITH-QWEN. Qwen scaffold shipped 2026-05-28 as W14-KIMI-REPLACEMENT-WITH-QWEN-SCAFFOLD. GLM remains available as alternate via claude-glm Pattern B wrapper."*

### Finding 2: W14-KIMI-AUTH-RESTORE

- **STATUS says** (verbatim Title): *"Kimi Code account TERMINATED — operator action required to restore or rotate"*. Status=`todo`, Owner=`Operator`, Effort=`operator-dependent`, Updated 2026-05-25. Notes (excerpt): "Action options for operator: (a) Email support@moonshot.cn ... (b) Get a new Kimi Code account ... (c) Migrate to Kimi Platform ... (d) Drop Kimi from the engine pool..."
- **Reality**: The Kimi account has been **restored** (Moonshot rolled back the punitive permaban into a friendlier UA-gate redirect). Confirmed via shipped row `W14-KIMI-VIA-CLAUDE` (2026-05-26, shipped, ~1.5h): *"WHAT CHANGED: 2026-05-25 punitive 'Access terminated...' permaban message has been ROLLED BACK by Moonshot ... account is NOT permanently banned ... Pattern B via Claude Code legitimate UA now passes the gate."* Live smoke at 2026-05-26 returned HTTP 200 from api.kimi.com/coding/v1/messages. A second shipped row `W14-SWARM-RE-VALIDATION` (2026-05-26, shipped) independently confirmed *"swarm/kimi-api: OK in 21.6s/3.6s API ... CONFIRMED working POST-RESTORATION - the allowlist reversal really did lift our block."* Also reflected in code comment at `src/harness/engines/wrapper_scripts.py:59-63`: *"W14-KIMI-VIA-CLAUDE 2026-05-26: account restored after the 2026-05-25 termination was rolled back into a friendlier UA-gate redirect."*
- **Evidence**:
  - `coord/STATUS.csv` row `W14-KIMI-VIA-CLAUDE` (shipped 2026-05-26) — explicit "Pattern B path live" verdict.
  - `coord/STATUS.csv` row `W14-SWARM-RE-VALIDATION` (shipped 2026-05-26) — second engine confirmation.
  - `src/harness/engines/wrapper_scripts.py:59-67` — code comment + claude-kimi wrapper still routes through `api.kimi.com/coding`.
  - `src/harness/engines/concrete.py:80-100` (per W14-KIMI-VIA-CLAUDE Notes referencing the area).
- **Verdict**: SHIPPED-UNDER-DIFFERENT-NAME (no operator action was needed; provider walked back the ban; Pattern B unlocked the legitimate path).
- **Suggested action**: Set ID `W14-KIMI-AUTH-RESTORE` Status=`shipped` (or `wontfix` if preferred since no L5 action was actually required), Updated=`2026-05-26`, Notes appended: *"Resolved 2026-05-26: Moonshot rolled back the punitive permaban; W14-KIMI-VIA-CLAUDE shipped Pattern B adapter with restored account. Direct httpx Kimi engine still gate-denied for truthful xaxiu-harness/1.0 UA (correct TOS posture); kimi-via-claude / claude-kimi wrapper is the live path."*

### Finding 3: W13-PLUGIN-SANDBOX-PLAN

- **STATUS says** (verbatim Title): *"Plan plugin loading safety to address DeepSeek code-injection risk"*. Status=`todo`, Updated 2026-05-26, Effort ~2-3h. Notes (excerpt): "For Wave 15 (plugin architecture): decide between (a) signed plugins only, (b) sandboxed execution via separate process ... (d) accept the risk and document it (since internal-tool = trusted authors). Decision row, not an implementation row."
- **Reality**: The underlying *plugin architecture itself* was explicitly **dropped** by the strategic re-scoping. The shipped row `W13-STRATEGIC-PANEL-15` (2026-05-25) says verbatim: *"DROP 250-400h of plugin/multi-user/VPS/best-of-N work (over-engineered for solo internal tool)."* Also confirmed by the shipped W14-STRATEGIC-EVALUATION row's Path-A/B/C analysis — for an internal solo-operator tool, the plugin architecture is over-engineering. Codebase confirmation: `Grep plugin|lens.*load|sandbox` in `src/harness/` returns exactly **one** file (`claude_code_subprocess.py`, which references "plugins" in the `--bare` flag context, not a plugin-loading subsystem). No `plugins/lenses/` directory exists in the tree. A decision row for a feature that has been dropped from scope cannot be `todo`.
- **Evidence**:
  - `coord/STATUS.csv` row `W13-STRATEGIC-PANEL-15` (shipped 2026-05-25) — verbatim drop quote.
  - `coord/STATUS.csv` row `W14-STRATEGIC-EVALUATION` (shipped 2026-05-25) — solo-internal-tool reframing.
  - No `src/harness/plugins/`, no `src/harness/lenses/`, no plugin loader in source.
- **Verdict**: FULLY-SUPERSEDED-NOT-UPDATED (no work to do; the parent feature was dropped).
- **Suggested action**: Set ID `W13-PLUGIN-SANDBOX-PLAN` Status=`wontfix`, Notes appended: *"Superseded 2026-05-25 by W13-STRATEGIC-PANEL-15 which explicitly dropped the plugin architecture as 'over-engineered for solo internal tool' (250-400h of plugin/multi-user/VPS/best-of-N work cut). Re-open only if the parent plugin architecture is revived."*

### Finding 4: W13-VPS-OBSERVER-NAT-PLAN

- **STATUS says** (verbatim Title): *"VPS observer pinging laptop assumes reachability - plan for NAT/firewall reality"*. Status=`todo`, Updated 2026-05-26, Effort ~1-2h. Notes (excerpt): "For W17-VPS-OBSERVER ... (a) laptop polls VPS instead of reverse, (b) VPS posts to a webhook ... (c) Tailscale/WireGuard ... Decision row for Wave 17."
- **Reality**: Same drop as Finding 3. `W13-STRATEGIC-PANEL-15` dropped *"VPS/best-of-N work"* explicitly. The parent W17-VPS-OBSERVER feature has been cut from scope (no W17 rows under any status in STATUS.csv). Grep `VPS|webhook|tailscale|nat|firewall|observer.*remote` in `src/harness/` matches only the existing local Observer primitive (which already runs via Task Scheduler), not any VPS/remote-observer implementation. No VPS code exists; no VPS plan should sit as `todo`.
- **Evidence**:
  - `coord/STATUS.csv` row `W13-STRATEGIC-PANEL-15` (shipped 2026-05-25) — explicit "VPS work" drop.
  - No W17 row in STATUS.csv at any status.
  - `src/harness/observer/` is the local-only Task-Scheduler-armed observer — no remote/VPS code path.
- **Verdict**: FULLY-SUPERSEDED-NOT-UPDATED.
- **Suggested action**: Set ID `W13-VPS-OBSERVER-NAT-PLAN` Status=`wontfix`, Notes appended: *"Superseded 2026-05-25 by W13-STRATEGIC-PANEL-15 dropping VPS work as over-engineered for solo internal tool. Re-open only if W17-VPS-OBSERVER is revived."*

### Finding 5: W13-BEST-OF-N-COST-CAP

- **STATUS says** (verbatim Title): *"Best-of-N dispatch cost multiplier needs explicit guardrails"*. Status=`todo`, Updated 2026-05-26, Effort ~1-2h. Notes (excerpt): "For W14-BEST-OF-N: enforce that paid-engine multiplication respects the $5/session cap pre-flight ... Subscription engines (Kimi/MiMo) are fine."
- **Reality**: The parent W14-BEST-OF-N feature was explicitly **dropped** by `W13-STRATEGIC-PANEL-15`'s drop list (*"plugin/multi-user/VPS/best-of-N work"*). Grep `best.of.n|best_of_n|BEST.OF.N|BestOfN` in `src/harness/` returns zero matches — no best-of-N feature was ever shipped. AND a separate complete budget-cap infrastructure DID ship (W14-BUDGET-METER-PER-ENGINE Tier 1B) which provides per-engine caps + 80% alert + dispatch-time enforcement (`src/harness/budget.py`, `src/harness/observer/budget_watch.py`). For the dropped Best-of-N use case, the generic per-engine cap from W14-BUDGET-METER-PER-ENGINE already covers any future re-introduction.
- **Evidence**:
  - `coord/STATUS.csv` row `W13-STRATEGIC-PANEL-15` (shipped 2026-05-25) — best-of-N explicitly dropped.
  - Grep `best.of.n` in `src/harness/` returns **zero matches** — no implementation exists to guard.
  - `src/harness/budget.py`, `src/harness/observer/budget_watch.py` — generic budget cap already shipped via W14-BUDGET-METER-PER-ENGINE (2026-05-28).
- **Verdict**: FULLY-SUPERSEDED-NOT-UPDATED.
- **Suggested action**: Set ID `W13-BEST-OF-N-COST-CAP` Status=`wontfix`, Notes appended: *"Superseded 2026-05-25 by W13-STRATEGIC-PANEL-15 dropping best-of-N work. Generic per-engine cap shipped 2026-05-28 as W14-BUDGET-METER-PER-ENGINE covers any future re-introduction."*

### Finding 6: W12-B-MAX-TOKENS-DEFAULT-RAISE (PARTIAL)

- **STATUS says** (verbatim Title): *"Raise max_tokens defaults across dispatch helpers + normalize engine param naming"*. Status=`todo`, Updated 2026-05-25, Effort ~2h. Notes scope: *"(1) raise default in harness.engines.concrete dispatch helpers from current 1500-2000 to 8000 ... (2) normalize the param name across Kimi/DeepSeek/MiMo ... (3) audit dispatch scripts (scripts/audit_w_action_panel20.py, scripts/operator_review_panel20.py, scripts/review_aquinas_brief.py) and raise their explicit caps from 1500-2000 to 4000-6000 ... (4) add a --quick CLI/SDK flag that drops to 1000 for cheap one-shots."*
- **Reality**: Parts (1), (2), (4) ARE SHIPPED across multiple subsequent rows.
  - Part (1) raise defaults: `src/harness/engines/concrete.py:402` Kimi default=200_000 (W5-W, shipped 2026-05-23); `concrete.py:700` MiMo default=131_072 (W5-W, shipped); `concrete.py:255` DeepSeek default=32_768 (WIRE-MAX-TOKENS, shipped 2026-05-22 per W1_5-ENGINE-FIXES). All well above the 8K target.
  - Part (2) normalization: addressed by W5-W operator directive + W7-KIMI-MAX-TOKENS-FLOOR (clamp small caller values up to 8K floor, shipped 2026-05-23). All three engines now honor `extra_args["max_tokens"]` uniformly via the StreamingTransport / per-engine `_build_payload`.
  - Part (3) NOT done. The three scripts still have stale caps: `scripts/review_aquinas_brief.py: max_tokens=2000`, `scripts/audit_w_action_panel20.py: max_tokens=1500`, `scripts/operator_review_panel20.py: max_tokens=1800`. Confirmed by grep.
  - Part (4) `--quick` flag: shipped 2026-05-25 by `W13-SDK-REVIEW-AND-CAPABILITIES` row: *"harness.review(...quick=False...) -> ReviewResult ... auto_max_tokens(quick=) with SAFE_MAX_TOKENS_FLOOR=4000 / QUICK_MAX_TOKENS=1000. CLI: harness review gets --quick flag."* This matches the spec exactly.
- **Evidence**:
  - `src/harness/engines/concrete.py:255` (DeepSeek 32768), `:402` (Kimi 200_000), `:700` (MiMo 131_072).
  - `coord/STATUS.csv` rows `W1_5-ENGINE-FIXES` (shipped 2026-05-22), `W5-W` (shipped 2026-05-23), `W7-KIMI-MAX-TOKENS-FLOOR` (shipped 2026-05-23), `W13-SDK-REVIEW-AND-CAPABILITIES` (shipped 2026-05-25, ships `--quick` flag).
  - `scripts/review_aquinas_brief.py: max_tokens=2000` — confirmed still stale.
  - `scripts/audit_w_action_panel20.py: max_tokens=1500` — confirmed still stale.
  - `scripts/operator_review_panel20.py: max_tokens=1800` — confirmed still stale.
- **Verdict**: PARTIAL — 3 of 4 sub-items fully shipped under different row IDs; only the script-cap raise (item 3) remains.
- **Suggested action**: Set ID `W12-B-MAX-TOKENS-DEFAULT-RAISE` Status=`partial` (or split into two: mark the original `todo` as shipped via W1_5-ENGINE-FIXES + W5-W + W7-KIMI-MAX-TOKENS-FLOOR + W13-SDK-REVIEW-AND-CAPABILITIES; spawn a new tiny row `W14-MAX-TOKENS-SCRIPT-SWEEP` ~15min to bump the 3 scripts to 4000-6000). Effort drops from ~2h to ~15min.

## Fresh findings (rows correctly marked unfinished)

- **W13-BACKUP-ENCRYPTION** — Truly not started. Confirmed: `grep encrypt|AES|fernet` in `src/harness/backup.py` returns zero matches. The encryption-related files in `src/harness/` (`cli.py`, `secrets/dpapi.py`, `audit_chain.py`, `setup_wizard.py`, `secrets/__init__.py`) are for DPAPI key storage + HMAC audit chain, none of which touches the backup tar.gz path. Notes spec (AES-256 of tar.gz body, DPAPI-derived key, cleartext manifest) is unimplemented. Genuine remaining greenfield work. Effort ~3-4h plausible.

- **W14-SWARM-CLAUDE-BACKENDS-PROPOSAL** — Correctly `queued`. Owner is explicitly `Cross-project (xaxiu-swarm session)`; this xaxiu-harness session must NOT cross-edit into the sibling repo per `feedback_multi_session_scoping` memory. The row exists as an architectural proposal awaiting a separate xaxiu-swarm session. No xaxiu-harness work to do. Status `queued` is the correct semantic.

## Anomalies (rows where the evidence is ambiguous)

- None. All 8 candidates resolved cleanly into shipped-under-different-name, fully-superseded, partial, or genuinely-not-started buckets.

## Summary table

| ID | STATUS says | Reality | Action |
|---|---|---|---|
| W12-B-MAX-TOKENS-DEFAULT-RAISE | todo / ~2h | 3 of 4 sub-items shipped via W1_5-ENGINE-FIXES + W5-W + W7-KIMI-MAX-TOKENS-FLOOR + W13-SDK-REVIEW-AND-CAPABILITIES; only script-cap raise remains (3 files, ~15min) | Change to `partial`; either trim Notes to scope-3-only OR spawn `W14-MAX-TOKENS-SCRIPT-SWEEP` |
| W13-BACKUP-ENCRYPTION | todo / ~3-4h | Truly not started; backup.py has no encryption code | Keep as `todo` — correctly fresh |
| W13-PLUGIN-SANDBOX-PLAN | todo / ~2-3h | Parent plugin feature DROPPED by W13-STRATEGIC-PANEL-15 | Change to `wontfix` with link to W13-STRATEGIC-PANEL-15 |
| W13-VPS-OBSERVER-NAT-PLAN | todo / ~1-2h | Parent W17-VPS-OBSERVER feature DROPPED by W13-STRATEGIC-PANEL-15 | Change to `wontfix` |
| W13-BEST-OF-N-COST-CAP | todo / ~1-2h | Parent W14-BEST-OF-N feature DROPPED; generic per-engine cap shipped via W14-BUDGET-METER-PER-ENGINE | Change to `wontfix` |
| W14-KIMI-AUTH-RESTORE | todo / operator-dependent | Account restored 2026-05-26 (provider walked ban back); Pattern B path live via W14-KIMI-VIA-CLAUDE | Change to `shipped` (or `wontfix`), Updated=2026-05-26 |
| W14-KIMI-REPLACEMENT-WITH-GLM | todo / ~5h | RENAMED to W14-KIMI-REPLACEMENT-WITH-QWEN per W14-ENGINE-COST-USAGE-MATRIX; Qwen shipped 2026-05-28 | Change to `wontfix` (superseded) |
| W14-SWARM-CLAUDE-BACKENDS-PROPOSAL | queued / ~3-4h | Cross-project; xaxiu-swarm session work | Keep as `queued` — correctly cross-scope |

## Headline numbers

- **Candidates audited**: 8
- **Truly stale (should change status)**: 6 of 8 = **75%**
  - SHIPPED-UNDER-DIFFERENT-NAME: 2 (W14-KIMI-AUTH-RESTORE, W14-KIMI-REPLACEMENT-WITH-GLM)
  - FULLY-SUPERSEDED (scope-dropped): 3 (W13-PLUGIN-SANDBOX-PLAN, W13-VPS-OBSERVER-NAT-PLAN, W13-BEST-OF-N-COST-CAP)
  - PARTIAL: 1 (W12-B-MAX-TOKENS-DEFAULT-RAISE)
- **Correctly tracked**: 2 of 8 = **25%** (W13-BACKUP-ENCRYPTION, W14-SWARM-CLAUDE-BACKENDS-PROPOSAL)

The 75% staleness rate matches the ~50% staleness rate that today's earlier CURRENT_PLAN.md audit caught (memory entry `feedback_grep_before_declare_greenfield_2026_05_28`) — STATUS.csv has the same drift pattern, slightly worse because closeout rows like W13-STRATEGIC-PANEL-15 dropped entire feature scopes without updating downstream child rows.
