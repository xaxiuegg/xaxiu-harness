# Agent C: CLI verb + doc drift audit (2026-05-28)

## Ground truth captured

### Live CLI verbs (62 total top-level verbs)

```
adapter, advanced, agent, agent-instructions, ask, ask-history, ask-show,
audit, backup, budget, burst, capabilities, coord, cost-today, daily,
dashboard-serve, dispatch, doctor, engines, engines-cooldowns, engines-heal,
engines-reliability, env, env-rotate, env-wizard, heartbeat, init, install,
install-agent-instructions, introspect, keys, l5-banner-demo, lint-spec,
lock, loop, loops, memory, morning-brief, observer, orchestrator,
panic-dump, plan, preflight, preflight-latency, priority, profile, proxy,
queue, replay, retro, review, self-update, session, setup, spec-init,
spec-register, spec-verify, start, state, status, swarm-verify, today
```

### Live SDK exports (`harness.__all__`)

```
DispatchResult, HarnessSDKError, ResultCorruptedError, ResultNotFoundError,
RetrieveScope, ReturnMode, ReviewResult, __version__, budget_status,
capabilities, dispatch, retrieve, review
```

### Live `harness coord` subcommands (13 total)

```
cancel, cleanup, integrate, list, plan, plan-from-description, replan,
rerun-failed, retry, run, status, watch, work
```

### Current pyproject.toml version

```
0.6.8
```

### Live doctor check count

**7 checks** (verified via source `D:\xaxiu-harness-standalone\src\harness\doctor.py:304-312`):
`python_version, git, claude_binary, dpapi, engine_keys, coord_writable, task_scheduler`

(With `--probe`, engine round-trips are added per-engine.)

### Live engines subcommands

```
list, health, failures, heal, install-wrappers, list-wrappers,
fallback-policy, describe, compatibility-matrix, recommend
```

**Note**: `cooldowns` and `reliability` are NOT engines subcommands — they exist only as TOP-LEVEL hyphenated verbs `engines-cooldowns` and `engines-reliability`.

---

## Stale doc references

### Finding 1: `C:\Users\xaxiu\.claude\CLAUDE.md:171,175` — "9-check" doctor claim (HIGHEST IMPACT — load-bearing snippet)

- **Doc says (line 171)**: `harness doctor                       9-check traffic-light health table`
- **Doc says (line 175)**: `- python -m harness doctor — 9-check health table`
- **Reality**: doctor emits exactly **7** checks (verified via `harness doctor` live output AND source `src/harness/doctor.py:304-312`). The "9" came from a pre-P2-audit-consolidation count (the P2 audit on 2026-05-27 collapsed three separate checks — `_check_secrets`, `_check_engine_reachability`, `_check_env_var_inventory` — into a single `_check_engine_keys`).
- **Root cause**: `src/harness/cli.py:458, 649, 655` — the **template source-of-truth** for the global snippet hard-codes "9-check" in three places. Every fresh `install-agent-instructions --force` propagates the stale number.
- **Suggested action**: Edit `src/harness/cli.py` lines 458, 649, 655 to say "7-check" (or better: compute the count from `harness.doctor` at template-render time). Then run `harness install-agent-instructions --force` to re-stamp the user's `~/.claude/CLAUDE.md`.

### Finding 2: `C:\Users\xaxiu\.claude\CLAUDE.md:179` — references non-existent HARNESS_VISUAL_MANUAL.md (HIGHEST IMPACT)

- **Doc says**: `**Visual reference**: \`D:\xaxiu-harness-standalone\docs\HARNESS_VISUAL_MANUAL.md\` has screenshots + walkthroughs.`
- **Reality**: That file does NOT exist. W14-DOCS-CONSOLIDATE on 2026-05-27 folded HARNESS_VISUAL_MANUAL.md into OPERATOR_GUIDE.md (see README.md:7-11 and OPERATOR_GUIDE.md:4 — "Replaces the pre-consolidation set: ... + HARNESS_VISUAL_MANUAL.md + ...").
- **Root cause**: `src/harness/cli.py:662-663` — template hard-codes the stale path.
- **Suggested action**: Change template (cli.py line 662-663) to point at `docs/OPERATOR_GUIDE.md` (which subsumes the visual manual + has screenshots at `docs/screenshots/`). Then re-stamp the snippet.

### Finding 3: `docs/OPERATOR_GUIDE.md:117` — "Eight-check traffic light" claim

- **Doc says**: `Eight-check traffic light:`
- **Reality**: doctor has 7 checks. The sample output shown at lines 207-217 actually displays only 7 (python, git, claude_binary, dpapi, engine_keys, coord_dir, task_scheduler) — so the example contradicts the heading.
- **Suggested action**: Replace "Eight-check" with "Seven-check".

### Finding 4: `docs/OPERATOR_GUIDE.md:757-758` — `harness engines reliability` and `harness engines cooldowns` don't exist as subcommands

- **Doc says (line 757)**: `harness engines reliability             # historical success rate per engine`
- **Doc says (line 758)**: `harness engines cooldowns               # which engines are currently quarantined`
- **Reality**: live CLI returns:
  - `engines reliability` → `Error: unknown subcommand 'reliability'; use 'list', 'health', 'failures', or 'heal'`
  - `engines cooldowns` → same error.
  - These verbs exist ONLY as top-level hyphenated forms: `harness engines-reliability` and `harness engines-cooldowns`.
- **Suggested action**: Replace with `harness engines-reliability` and `harness engines-cooldowns` (or stop and decide whether to wire them as `engines` subcommands too — the existing top-level form is the older sibling pattern, but the doc clearly expects them under `engines`).

### Finding 5: `docs/HANDOFF.md:69` — "9-check traffic-light"

- **Doc says**: `4. Run \`python -m harness doctor\` and show me the 9-check traffic-light output.`
- **Reality**: 7 checks, not 9.
- **Suggested action**: Replace `9-check` with `7-check`.

### Finding 6: `README.md:70` — "Six-check traffic-light"

- **Doc says**: `Six-check traffic-light report; tells you exactly what to fix if anything's red.`
- **Reality**: 7 checks. README is stale in the other direction (under-counts).
- **Suggested action**: Replace `Six-check` with `Seven-check`.

### Finding 7: `README.md:213` — "22-verb CLI" in the project-structure inline comment

- **Doc says**: `│   ├── cli.py             # 22-verb CLI`
- **Reality**: 62 top-level verbs (verified via `len(cli.commands)`).
- **Suggested action**: Either delete the verb count or update to `62-verb` (and add a "live count: `harness --help`" disclaimer to prevent re-staling).

### Finding 8: `README.md:102` — "50+ top-level verbs as of v1.0.0-rc.1"

- **Doc says**: `As of v1.0.0-rc.1 (2026-05-25) there are 50+ top-level verbs.`
- **Reality**: 62 verbs. (Numerically the "50+" is still technically true since 62 > 50, but the v1.0.0-rc.1 version anchor is stale — pyproject is at 0.6.8 — and CLAUDE.md gave up on hard counts on 2026-05-27 for exactly this reason.)
- **Suggested action**: Replace with "60+ top-level verbs (live: `harness --help`)".

### Finding 9: `CLAUDE.md:68` — "12 subcommands" for `harness coord` CLI

- **Doc says (in v2/D row)**: `harness coord CLI (12 subcommands)`
- **Reality**: 13 subcommands (`cancel, cleanup, integrate, list, plan, plan-from-description, replan, rerun-failed, retry, run, status, watch, work`).
- **Suggested action**: Replace `12` with `13` (or drop the count and refer to `harness coord --help`).

### Finding 10: `CLAUDE.md:76` — the canonical subcommand list is correct

- **Doc says**: `\`harness coord\` subcommands: plan, plan-from-description, run, work, retry, rerun-failed, integrate, replan, status, watch, list, cancel, cleanup.`
- **Reality**: that lists all **13** subcommands correctly. The mismatch with line 68's "12 subcommands" is purely an arithmetic error in line 68.

### Finding 11: `README.md:112` — `coord` subcommand list missing `rerun-failed`

- **Doc says**: `\`coord\` | \`plan\`, \`plan-from-description\`, \`run\`, \`work\`, \`retry\`, \`integrate\`, \`replan\`, \`status\`, \`watch\`, \`list\`, \`cancel\`, \`cleanup\``
- **Reality**: Missing `rerun-failed` (chains replan → run → integrate). 12 listed, 13 actual.
- **Suggested action**: Add `rerun-failed` between `retry` and `integrate`.

### Finding 12: `README.md:127` — `proxy` subcommands stale

- **Doc says**: `\`proxy\` | \`start\`, \`stop\`, \`status\`, \`reset-circuit\`, \`quarantine\`...`
- **Reality**: live subcommands are `start, stop, status, reset-circuit, quarantine, disable-key, unquarantine, upstreams`. Missing `disable-key`, `unquarantine`, `upstreams` (the latter is THE main discovery verb for the 5 upstream selectors).
- **Suggested action**: Append `disable-key, unquarantine, upstreams` to the row.

### Finding 13: `README.md:116` — `engines` subcommand row only lists `cooldowns`

- **Doc says**: `\`engines\` | \`cooldowns\` | List engines + active cooldown windows from state.json.`
- **Reality**: `engines` has 10 real subcommands (`list, health, failures, heal, install-wrappers, list-wrappers, fallback-policy, describe, compatibility-matrix, recommend`). The listed `cooldowns` is NOT one of them (see Finding 4) — it lives at `engines-cooldowns`.
- **Suggested action**: Replace the row with the actual subcommand list (or refer to `harness engines --help`).

### Finding 14: `README.md:117` — `env` subcommands list

- **Doc says**: `\`env\` | — | Show which API keys are set (Kimi, DeepSeek, Anthropic, MiMo).`
- **Reality**: `env` is a single command (correct on the structural row). However the function description omits MiMo TokenPlan, Qwen, GLM, Gemini that are actually inventoried. Cosmetic — not blocking.

### Finding 15: `README.md:124` — `observer` subcommand list missing items

- **Doc says**: `\`observer\` | \`init\`, \`arm\`, \`disarm\`, \`pause\`, \`resume\`, \`status\`, \`flags\`, \`ack\`, \`cycle-now\`, \`daily-retro\`, \`audit-chat\`, \`install-scheduler\`, \`uninstall-scheduler\`...`
- **Reality**: 16 actual subcommands. Missing `budget-watch` (W14-BUDGET-METER-PER-ENGINE 2026-05-28), `restart` (W11-OBSERVER-WATCHDOG-RECOVERY), `watchdog-status` (W11-OBSERVER-WATCHDOG-RECOVERY).
- **Suggested action**: Append `budget-watch, restart, watchdog-status` or drop the explicit list.

### Finding 16: `README.md:128` — `queue` subcommands stale

- **Doc says**: `\`queue\` | \`list\`, \`execute\`...`
- **Reality**: still `list, execute` — accurate. (No drift.)

### Finding 17: `README.md:84` — references non-existent `harness commands --did-you-mean`

- **Reality**: Live CLI returns `Error: No such command 'commands'.` — there is no `commands` verb at all.
- **Doc says (line 83-84)**: Mentions `harness capabilities` (which IS live) and `harness --help`. **No reference to `harness commands --did-you-mean` found in README** — earlier evidence in the audit brief mentioned this in plan docs, but it does NOT survive in README/OPERATOR_GUIDE/AGENT_REFERENCE. Likely already cleaned up.
- **Suggested action**: No README change needed. If a stale `commands --did-you-mean` reference exists in `coord/CURRENT_PLAN.md` or other plan docs, fix there.

### Finding 18: `README.md:134` — `status` subcommand list missing `human`

- **Doc says**: `\`status\` | \`report\`, \`init\`, \`add\`, \`update\`, \`list\`, \`summary\`, \`verify\``
- **Reality**: 8 subcommands — missing `human` (W8-AUDIT follow-through alias for `harness today` per the help text).
- **Suggested action**: Add `human` to the list.

### Finding 19: `README.md:133` — `session` subcommand list

- **Doc says**: `\`session\` | \`check\`, \`bootstrap\`, \`ack\`, \`crisis-check\`, \`arm-crisis-check\`, \`ok-to-stop\``
- **Reality**: Matches. (Accurate.)

### Finding 20: `README.md:114` — `dispatch` shown as no-subcommand verb

- **Doc says**: `\`dispatch\` | — | Send a work packet to an engine; auto-routes if you do not pick one.`
- **Reality**: `dispatch` is a single (non-group) verb. Accurate.

### Finding 21: `docs/OPERATOR_GUIDE.md:266` — wizard step count

- **Doc says**: shows `--- Step 1/5 ---` through `--- Step 5/5 ---` — implies 5-step setup wizard.
- **Reality**: live `harness setup --help` text reads:
  ```
  Steps:
      1. harness doctor — preflight diagnostics
      2. Claude Code CLI availability check (with install hint)
      3. API key configuration (offers to launch keys UI)
      4. Wrapper script installation (claude-mimo / claude-kimi / etc.)
      5. Smoke dispatch (verifies end-to-end wiring)
  ```
  — 5 steps. **Accurate.** No fix needed.

### Finding 22: `docs/OPERATOR_GUIDE.md:843` — references a hypothetical `harness backup restore <path>` verb

- **Doc says**: `If a future backup verb ships (\`harness backup restore <path>\`) it'll be in \`harness --help\`. As of 2026-05-27, restore is manual.`
- **Reality**: `harness backup restore` is REAL (live as of today; the `backup` group has `create, list, prune, restore`).
- **Suggested action**: Update — `restore` already exists. Replace the "future tense" paragraph with a "How to restore" line: `python -m harness backup restore <path>`.

### Finding 23: `docs/AGENT_REFERENCE.md:281` — `xaxiu-swarm` claims model `qwen`

- **Doc says**: `Backends: \`kimi\` (CLI, agentic), \`kimi-api\`, \`deepseek\`, \`qwen\` (per the strategic plan), \`mimo\` (TOS-compliant via Claude Code subprocess), \`claude-*\` (per-provider wrappers).`
- **Reality**: `xaxiu-swarm` is a sibling repo; this doc claim is only verifiable in that repo, not here. The CLAUDE.md memory note says the swarm backends are `kimi, kimi-api, deepseek, qwen, mimo, claude-*`. Accuracy of `qwen` depends on the sibling repo — out of scope for this audit but flag-worthy.
- **Suggested action**: Verify against `xaxiu-swarm` (sibling repo), or qualify with "(may not be live in your sibling-repo clone)".

### Finding 24: Description ordering of `proxy upstreams`

- **OPERATOR_GUIDE.md:178** advertises only `harness proxy start`, `harness proxy stop`, `harness proxy status`. Does not mention `harness proxy upstreams` (the most-used discovery verb for the 5 upstreams).
- **CLAUDE.md global snippet line 95** does correctly include `harness proxy upstreams`.
- **Suggested action**: Add `python -m harness proxy upstreams` to OPERATOR_GUIDE.md § 8 (or wherever proxy is documented in the operator guide). Currently OPERATOR_GUIDE.md does NOT have a top-level proxy section at all — the only proxy mention is line 588: brief architectural note. Worth a row for operator coverage.

### Finding 25: `docs/AGENT_REFERENCE.md:260-266` — proxy section says "Default upstream is Kimi (Moonshot)"

- **Doc says**: `Default upstream is Kimi (Moonshot)`
- **Reality**: Per `harness proxy upstreams`, `kimi-http` is listed first ("default" in the cli.py template, line 446-448 of the global snippet). Live verification shows the proxy starts with `kimi-http` as default. **Accurate**, but worth noting that Kimi 403's with `access_terminated_error` from this account (verified by `engines health` output above) — so the doc-default is functionally broken for the operator. Drift is in the universe, not the doc itself.
- **Suggested action**: Consider adding an operator-readable note that the default upstream may not have a working key for accounts where Kimi was terminated 2026-05-22; the KEY_ROTATION_PLAYBOOK.md row #6 already acknowledges this.

---

## Stale version/count references

| Location | Doc says | Reality | Severity |
|---|---|---|---|
| `~/.claude/CLAUDE.md:171, 175` | "9-check" doctor | 7 checks | **HIGH (load-bearing fresh-session snippet)** |
| `~/.claude/CLAUDE.md:179` | HARNESS_VISUAL_MANUAL.md exists | File doesn't exist | **HIGH** |
| `src/harness/cli.py:458, 649, 655, 662-663` | (snippet template source) "9-check" + HARNESS_VISUAL_MANUAL.md | Drift gets re-stamped every install | **HIGH (root cause of above)** |
| `docs/OPERATOR_GUIDE.md:117` | "Eight-check" doctor | 7 checks | MED |
| `docs/HANDOFF.md:69` | "9-check" doctor | 7 checks | MED |
| `README.md:70` | "Six-check" doctor | 7 checks | MED |
| `README.md:213` | "22-verb CLI" | 62 verbs | MED |
| `README.md:102` | "50+ top-level verbs as of v1.0.0-rc.1" | 62 verbs; pyproject is 0.6.8 | LOW (count still ≥50) |
| `CLAUDE.md:68` | "harness coord CLI (12 subcommands)" | 13 subcommands | MED |
| `README.md:112` | coord subcommand list omits `rerun-failed` | 13 actual | MED |
| `README.md:116` | engines only lists `cooldowns` (not even a subcommand!) | 10 real subcommands | MED |
| `README.md:124` | observer omits `budget-watch, restart, watchdog-status` | 16 actual | LOW |
| `README.md:127` | proxy omits `disable-key, unquarantine, upstreams` | 8 actual | MED (`upstreams` is the new key verb) |
| `README.md:134` | status omits `human` | 8 actual | LOW |
| `docs/OPERATOR_GUIDE.md:757-758` | `engines reliability` / `engines cooldowns` as subcommands | They're top-level hyphenated only | **HIGH (will fail at runtime)** |
| `docs/OPERATOR_GUIDE.md:843` | "If a future backup restore verb ships" | Already shipped | MED |

`README.md:1` line: "v0.1.0 (v1.0.0-rc.1 tagged)" while pyproject is `0.6.8` — the doc itself addresses this on line 5 ("package version stays at 0.1.0 while the Horizon C internal-tool work continues") but the version-anchoring lag (0.1.0 → 0.6.8 between source-of-truth and self-description) is itself a smell.

---

## Doc that needs the most attention

Ranked by drift severity, highest first:

1. **`C:\Users\xaxiu\.claude\CLAUDE.md` (the user global snippet)** — Findings #1 (9-check claim) and #2 (HARNESS_VISUAL_MANUAL.md). This is what every fresh agent session loads first. Both issues are baked into the template at `src/harness/cli.py:458,649,655,662-663` and will re-stamp on every `install-agent-instructions --force` until the template source is fixed.

2. **`README.md`** — multiple subcommand lists are out of date (Findings #7, #8, #11, #12, #13, #15, #18); old check count (#6); old verb count (#7). The README explicitly disclaims drift ("Note: this table drifts. Run `harness --help` for the live list") which softens the impact, but new users still consult it first.

3. **`docs/OPERATOR_GUIDE.md`** — Finding #4 is a runtime-breaking claim (`harness engines reliability` will fail at the command line because `engines` doesn't have a `reliability` subcommand; only `engines-reliability` does). Finding #3 has wrong count. Finding #22 advertises a verb as "future" that has shipped.

4. **`docs/HANDOFF.md`** — Finding #5 (9-check). Single instance.

5. **`docs/AGENT_REFERENCE.md`** — coord subcommand list is correct and current (Finding #10 cross-checks the list there too — it matches). The doc is the cleanest of the bunch. Finding #23 is the only flag and it requires sibling-repo verification.

6. **`docs/KEY_ROTATION_PLAYBOOK.md`** — Brand new (shipped today). No drift detected in CLI surface claims. The `harness env-rotate` verb and `harness audit verify` are both live and behave as documented.

7. **`CLAUDE.md` (project)** — Finding #9 is the sole quantitative drift (12 → 13). The "P6 audit fix 2026-05-27" preamble note explicitly acknowledges that hard numbers in this file go stale fast.

---

## Fresh confirmations

These doc surfaces look accurate against the live CLI surface as audited 2026-05-28:

- **`docs/AGENT_REFERENCE.md` § 10.2** (coord subcommand list) — all 13 listed correctly.
- **`docs/AGENT_REFERENCE.md` § 13** (SDK signatures) — matches `harness.__all__` exactly: `DispatchResult, HarnessSDKError, ResultCorruptedError, ResultNotFoundError, RetrieveScope, ReturnMode, ReviewResult, budget_status, capabilities, dispatch, retrieve, review` (the doc lists all callables; the doc-mentions-all-sdk-fns CI gate covers this and was confirmed via the existence of `tests/test_docs_mention_all_sdk_fns.py`).
- **`docs/OPERATOR_GUIDE.md` § 2.5** (`harness ask` modes table — routed/audit/panel) — matches live `harness ask --help` exactly. Flags `--task`, `--audit`, `--panel`, `--engines`, `--file`, `--max-budget-usd`, `--timeout-s`, `--print-text`, `--no-save`, `--output` all live.
- **`docs/OPERATOR_GUIDE.md` § 2.6** (`harness engines recommend` task classes) — matches: `default | latency | verbose | cost | high-volume | multimodal | audit`.
- **`docs/HANDOFF.md` Piece C / Part 1** (the setup-prompt) — every verb referenced (`harness doctor`, `harness keys serve`, `harness ask`, `harness install-agent-instructions`) exists on the live CLI. Workflow is current.
- **`CLAUDE.md` project line 76** (coord subcommand list as comma-separated names) — accurate 13/13.
- **`KEY_ROTATION_PLAYBOOK.md`** — `env-rotate` verb, supported engines list, `audit verify`, audit-ledger event shape, exit codes — all match live surface.
- **CLAUDE.md (project) line 78** — smoke-test command `PYTHONPATH=src python -c "from harness.cli import cli; print(sorted(cli.commands.keys()))"` works and is the right primitive.
- **`xaxiu-swarm` references**: NOT removed from any doc. Per project memory `feedback_engine_dispatch_path`, `ask_kimi.py` IS deprecated but no doc references it; the swarm docs reference is intentional (sibling repo, per CLAUDE.md framing) — not drift.
- **`harness coord --help` description text** — explicitly notes the 2026-05-27 unhide and refers operators to `docs/OPERATOR_GUIDE.md § 3.3` (where it does indeed appear) and `docs/AGENT_REFERENCE.md § 10` — both cross-references resolve correctly.

---

## Highest-leverage single fix

Fixing `src/harness/cli.py` lines 458, 649, 655, 662-663 propagates to `~/.claude/CLAUDE.md` on the next `install-agent-instructions --force` AND closes the drift in `agent-instructions` output everywhere. One file, four edits:

- Lines 458 and 649 and 655: `9-check` → `7-check` (or render dynamically from `harness.doctor`).
- Lines 662-663: `HARNESS_VISUAL_MANUAL.md` → `OPERATOR_GUIDE.md` (or to `docs/OPERATOR_GUIDE.md` plus the screenshot dir `docs/screenshots/`).

After fixing cli.py, re-run `python -m harness install-agent-instructions --force` to stamp the corrected snippet into `~/.claude/CLAUDE.md`.
