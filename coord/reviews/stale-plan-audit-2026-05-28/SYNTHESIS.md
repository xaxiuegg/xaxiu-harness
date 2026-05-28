# Repo-wide stale-plan audit — synthesis (2026-05-28)

**Method**: 4 parallel sub-agents, each applying the
`feedback_grep_before_declare_greenfield_2026_05_28` protocol to a
different repo slice.

**Headline**: drift is symmetric across all four slices — CURRENT_PLAN.md
(earlier today) at ~50%, STATUS.csv at **75%**, docs at ~12 distinct
items, specs at 4 items. Root cause confirmed: closeout / strategic
rows drop entire feature scopes (e.g., the plugin-architecture drop in
`W13-STRATEGIC-PANEL-15`) without updating the downstream child rows
that referenced those scopes.

Plus a new mechanism agent C identified: **the user's global snippet at
`C:\Users\xaxiu\.claude\CLAUDE.md` re-stamps on every
`install-agent-instructions --force`**, so any drift in
`src/harness/cli.py`'s install templates re-introduces itself on the
next install. Fixing the source (cli.py) > fixing the destination
(global snippet).

## Findings by severity

### Tier 1 — misdirects fresh agents (fix IMMEDIATELY)

| Finding | Source | Why critical |
|---|---|---|
| `CLAUDE.md` (project) line 111 points at `~/.claude/projects/D--Projects/memory/` | Agent A finding 4 | **Loads the WRONG project's memory.** This is a leftover from the 2026-05-22 D:/Projects → D:/xaxiu-harness-standalone migration. Any agent following this instruction loads warehouse memory instead of harness memory. |
| Global snippet `C:\Users\xaxiu\.claude\CLAUDE.md` says "9-check doctor" | Agent C finding 1 | Doctor has 7 checks (P2 audit collapsed 3 into 1 on 2026-05-27). Re-stamps from `src/harness/cli.py:458, 649, 655`. Misleads every fresh session. |
| Global snippet references `docs/HARNESS_VISUAL_MANUAL.md` | Agent C finding 2 | File doesn't exist (consolidated into OPERATOR_GUIDE.md on 2026-05-27). Re-stamps from `src/harness/cli.py:662-663`. |

### Tier 2 — wrong counts / lists / states (high doc-noise, no functional break)

| Finding | Source | Fix scope |
|---|---|---|
| `CLAUDE.md` "v0.5" header → actually v0.6.8 | Agent A finding 1 | One-line edit |
| `CLAUDE.md` "43 entries" memory count → actually 57 | Agent A finding 3 | One-line edit |
| `CLAUDE.md` engine-routing section uses pre-Pattern-B vocabulary | Agent A finding 2 | One-paragraph update pointing at `harness engines compatibility-matrix` |
| `CLAUDE.md` lists "5 concrete" engines, missing MiMo + Qwen | Agent A bonus | One-line edit |
| `CLAUDE.md:68` "12 subcommands" → actually 13 | Agent C finding 4 | One-line edit |
| `README.md` 22-verb CLI comment → actually 62 verbs | Agent C finding 5 | One-line edit + sub-list fixes |
| `docs/OPERATOR_GUIDE.md:757-758` advertises non-existent `harness engines reliability` / `cooldowns` subcommands | Agent C finding 2 | Use top-level hyphenated form |
| `docs/OPERATOR_GUIDE.md:843` treats shipped `harness backup restore` as future | Agent C finding 6 | One-paragraph update |
| Doctor-check count drift across README / OPERATOR_GUIDE / HANDOFF (each says different number) | Agent C finding 3 | Three docs to align with cli.py source |

### Tier 3 — STATUS.csv state errors (6 rows)

| Row | Current STATUS | Reality | Action |
|---|---|---|---|
| `W14-KIMI-REPLACEMENT-WITH-GLM` | todo | Renamed → Qwen by `W14-ENGINE-COST-USAGE-MATRIX` 2026-05-25; scaffold shipped 2026-05-28 | Set status=wontfix with note pointing at `W14-KIMI-REPLACEMENT-WITH-QWEN-SCAFFOLD` |
| `W14-KIMI-AUTH-RESTORE` | todo | Moonshot walked back the ban 2026-05-26; Pattern B path live via `W14-KIMI-VIA-CLAUDE` | Set status=shipped |
| `W13-PLUGIN-SANDBOX-PLAN` | todo | Parent plugin architecture explicitly DROPPED by `W13-STRATEGIC-PANEL-15` ("DROP 250-400h of plugin/multi-user/VPS/best-of-N work") | Set status=wontfix |
| `W13-VPS-OBSERVER-NAT-PLAN` | todo | Parent W17-VPS-OBSERVER DROPPED; no W17 rows exist | Set status=wontfix |
| `W13-BEST-OF-N-COST-CAP` | todo | Parent W14-BEST-OF-N DROPPED; generic cap via `W14-BUDGET-METER-PER-ENGINE` | Set status=wontfix |
| `W12-B-MAX-TOKENS-DEFAULT-RAISE` | todo | 3 of 4 sub-items shipped (W15-ENGINE-FIXES + W5-W + W7-KIMI-MAX-TOKENS-FLOOR + W13-SDK-REVIEW-AND-CAPABILITIES); only 3 script caps remain | Set status=partial with scoped remainder |

### Tier 4 — spec / test / memory drift (low priority)

| Finding | Source | Action |
|---|---|---|
| `spec/v1-architecture.md:6` + `spec/v1.1-operator-experience.md:3` stale paths `D:/Projects/xaxiu-harness/` | Agent D | Replace with `D:/xaxiu-harness-standalone/` |
| `spec/autonomous-loops.md` lists 9 `harness loop` subcommands; only 5 shipped (`init/start/status/stop/tick`) | Agent D | Trim spec or surface as implementation gap |
| `spec/status-tracker.md` stale "33-row STATUS.csv" literal | Agent D | Remove the literal count |
| `tests/test_observer_autoarm_all.py:53,78` stale skips for `db_scheduler` not yet shipped | Agent D | Unskip (module exists + imports clean) |
| Memory entry `reference_xaxiu_harness_error_taxonomy.md` says "Implementation pending Wave A.5" | Agent A finding 5 | Update entry — fully shipped (12 concrete subclasses in `src/harness/errors.py`) |
| Memory entry `reference_observer_system.md` names warehouse path `dev-panel-runs/ag-qty-bug-v101/observer/` | Agent A bonus | Update to harness's `coord/observer/` |

## Order of operations

1. **Tier 1** (the snippet root + the misdirected memory path) — these
   actively harm new agents. Fix first.
2. **Tier 3** (STATUS.csv state updates) — six rows. Mechanically simple.
3. **Tier 2** (doc counts + lists) — batch fix across CLAUDE.md, README,
   OPERATOR_GUIDE.
4. **Tier 4** (specs, tests, memory) — lowest priority but still in scope.

After all fixes land, re-run the consistency test + full suite to confirm
green. Then commit + push as `W14-REPO-WIDE-STALENESS-AUDIT`.

## Per-agent reports

- [agent-A-plan-docs.md](agent-A-plan-docs.md) — CURRENT_PLAN.md + CLAUDE.md + memory
- [agent-B-status-csv.md](agent-B-status-csv.md) — STATUS.csv non-shipped rows
- [agent-C-verbs-docs.md](agent-C-verbs-docs.md) — CLI verbs vs docs
- [agent-D-tests-todos-specs.md](agent-D-tests-todos-specs.md) — tests / TODOs / specs
