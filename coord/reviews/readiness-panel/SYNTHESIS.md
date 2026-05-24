# Harness readiness — 10-reviewer synthesis

_Dispatched: 10 personas, elapsed 131.2s_

State snapshot fed to each reviewer is at `_state_snapshot.md` in this directory.

## Per-persona responses

### K1-onboarding-friction

## Rubric

1. **Install** — 2. Doc triad splits authority; operator faces conflicting gates (`doctor` OK vs `preflight` fail) and an unguided sequence of ≥5 decisions (which doc? `doctor`/`install`/`init`? fix `git_clean`? UNSET keys okay? brief now?). Non-technical users cannot self-remediate untracked-file failures.

2. **Daily run** — 3. `morning-brief` is buried in a 30-verb CLI with no daily alias or checklist, forcing the operator to remember the exact incantation amid irrelevant commands.

3. **Observe** — 4. STATUS.csv is readable; `dashboard-serve` and `observer` surfaces are usable without opening `runs/`. Engine root-cause still requires log literacy, but the panel is viable.

4. **Recover** — 2. `engines-heal` covers engine death, but preflight false-positives and proxy failures lack operator-visible remediation; the `git_clean` warn→fail path has no CLI fix.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. The operator can read STATUS.csv and run CLI commands, but the first-run experience forces a high-stakes doc choice and a preflight git failure they cannot self-resolve. Once past the wall, daily observation is viable; recovery from non-engine failures is not.

6. **Top 3 blockers**
   - **`GETTING_STARTED.md`** prescribing exact first-run sequence and explicitly excluding CLAUDE.md/SESSION_BOOTSTRAP.md from operator scope.
   - **`harness preflight --operator`** (or profile-aware default) that suppresses `git_clean` blockers and explains fixes in plain language.
   - **`harness day-start`** meta-command wrapping `preflight` + `morning-brief` + `observer status` into one daily report to eliminate decision fatigue.

### K2-documentation

## Rubric

1. **Install** — **2**. `harness doctor` is readable, but `preflight` exits 1 on a cryptic `git_clean` warning with no remediation hint, and no simple first-run wizard output is shown.
2. **Daily run** — **2**. `morning-brief` and `dashboard-serve` suggest routine awareness, yet the CLI presents 20+ undifferentiated commands with no obvious daily sequence or plain-language “what do I run today?” guide.
3. **Observe** — **2**. Observer and dashboard primitives exist, but `STATUS.csv` is packed with ticket IDs, mutation metrics, and arcane module names; no evidence of a non-technical summary view.
4. **Recover** — **2**. `engines-heal` and `doctor` are discoverable, but preflight warnings lack remediation steps and `STATUS.csv` explicitly flags undocumented proxy failure modes and missing recovery matrices.

## Hand to a non-technical operator today?
**WITH GUARDRAILS.** A motivated operator could run pre-canned commands like `morning-brief` and `dashboard-serve` if a technical user performs initial setup, hides the full `--help` surface, and provides a 1-page cheat sheet. They cannot self-install or self-recover from warnings like `git_clean` or dead engines without a runbook.

## Top 3 blockers
- **Plain-language install runbook**: translate `preflight`/`doctor` outputs into “if you see X, do Y” steps.
- **Simplified daily operator view**: collapse the 20+ CLI verbs into an opinionated daily checklist (e.g., `harness today`) instead of requiring the operator to navigate subcommands.
- **Failure-mode recovery cards**: attach human-readable remediation to every `preflight` warning and `STATUS.csv` `todo` so the operator knows which single command to run next.

### K3-failure-modes

## Rubric

**First-month failure modes**
1. **Preflight halts on `git_clean` warning.** Error: visible (`3 untracked files`) but not actionable. Recovery: not obvious (stash? delete?). → Ping engineering.
2. **Engine proxy fail-closed / key exhaustion.** Error: absent or engineering-level (W9-PROXY-FAILURE-MATRIX is todo). Recovery: undocumented. → Ping engineering.
3. **Task Scheduler silent death.** Error: none; preflight only checks “armed,” not last-run health. Recovery: unclear. → Ping engineering.
4. **Engine quarantine cascade.** Error: preflight notes dead engines. Recovery: `engines-heal` exists but is not suggested in output. → Ping engineering.

1. **Install** — 2. Preflight exits 1 on a soft git warning with no `--fix` or plain-language hint, stalling non-technical users.
2. **Daily run** — 3. `morning-brief` exists, but hidden Task Scheduler dependencies and lack of a single curated checklist add toil.
3. **Observe** — 2. STATUS.csv mixes 296 wave and dispatch rows; no evidence the dashboard is deployed for non-technical readability.
4. **Recover** — 1. Critical failures (proxy, engine death, silent exceptions) lack CLI-guided remediation or operator-facing runbooks.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. Core verbs and checks exist, but the first month will repeatedly surface ambiguous preflight halts, opaque proxy failures, and silent scheduler deaths that require engineering escalation because self-service recovery paths are not yet wired or documented.

6. **Top 3 blockers**
   - `harness preflight --fix` or guided plain-language remediation for git/stash warnings.
   - Shipped W9-PROXY-FAILURE-MATRIX plus `harness engines` surfacing one recommended recovery verb when quarantined.
   - Operator-filtered status view (e.g., `harness status --operator`) that hides raw dispatch logs and surfaces only health and next actions.

### K4-cli-ergonomics

## Rubric

1. **Install — 3** `doctor` reads clearly, but `preflight` is missing from `--help`, exits 1 on `git_clean` without a remediation hint, and requires the operator to reason about untracked files.

2. **Daily run — 3** `morning-brief` exists, yet there is no single obvious daily entry-point; the operator must guess whether to run `loop`, `loops`, `coord`, or just read the dashboard.

3. **Observe — 4** Dashboard, observer, and STATUS.csv provide good visibility, but the CLI lacks a unified `harness today` summary that surfaces all three for a non-technical user.

4. **Recover — 3** `engines-heal` and `doctor` cover some failures, but common stale states (untracked files, routing locks) lack a one-step remediation verb such as `harness fix` or `harness unlock`.

5. **Hand to a non-technical operator today?** **WITH GUARDRAILS**. Installation and daily observation are possible, but the 60+ subcommand surface is overwhelming, verb naming is inconsistent (`loop` vs `loops`, hidden `preflight`), and recovery requires interpreting diagnostic badges rather than running a guided repair command. A printed runbook is mandatory.

6. **Top 3 blockers**
   - **`harness today` meta-command**: rolls up `preflight`, `observer`, and `coord status` into one daily operator summary.
   - **`harness tidy` / `preflight --fix`**: auto-remediate `git_clean`, lock drift, and stale caches without manual git commands.
   - **Discoverability fix for `preflight`**: surface it in `harness --help` and add a `--fix` flag so the readiness gate is findable and actionable.

### K5-honest-readiness

## Rubric
1. **Install** — 2. Preflight exits 1 on untracked files with no actionable remediation; a non-technical user cannot clear the readiness gate.
2. **Daily run** — 2. Twenty-plus verbs and cryptic flags (`--explore-on-uncertainty`) with no obvious single “start my day” command.
3. **Observe** — 3. Dashboard and morning-brief exist, but output is jargon-heavy and the 296-row STATUS.csv is unfiltered noise.
4. **Recover** — 2. `engines-heal` exists, yet preflight git warnings lack fix hints and open W9 proxy/redaction gaps leave critical failures undocumented.

5. **Hand to a non-technical operator today?** NO. The preflight readiness gate fails with an ambiguous git warning that would halt a non-technical user before day one. The CLI is a dense forest of expert flags rather than a guided workflow. Most critically, open security gaps (secret exfiltration path, undocumented proxy fail-open behavior) mean typical failures become silent data-loss events that a non-technical operator cannot detect or remediate.

6. **Top 3 blockers:** (1) A single `harness daily` verb that sequences morning-brief → dispatch → observer → status, hiding advanced flags. (2) A `harness preflight --fix` that auto-resolves git warnings, stash issues, and engine cooldowns without Python knowledge. (3) Ship W9-PROXY-FAILURE-MATRIX and W9-REDACTION-INTEGRITY-TEST and wire them into `harness doctor` so key-leak scenarios are caught and reported in plain language.

### M1-install

## Rubric

**Install (3/5):** `harness install` with a first-run wizard and `harness doctor` diagnostics are strong scaffolding. However, env-var setup (`KIMI_API_KEY`, `DEEPSEEK_API_KEY`) has no visible wizard step — the operator must know *where* to set Windows environment variables, which is non-trivial without guidance. DPAPI says "read works" but the *seeding* step (writing keys into DPAPI initially) isn't shown — likely undocumented for the happy path. Exit code 1 on `preflight` due to a git warning will alarm a non-technical operator who doesn't know `1 ≠ fail`.

**Daily run (3/5):** `harness morning-brief` plus `harness coord status` is a reasonable two-command cadence, and `harness dashboard-serve` exists for visual monitoring. The `--profile non_technical` flag reduces verbosity. But the *default* flags (mode, escalation-threshold, explore-on-uncertainty) aren't obviously set once — the operator must either always pass flags or edit a config file. A `daily` or `start` verb that loads a saved profile is missing.

**Observe (4/5):** Observer primitives, heartbeat, STATUS.csv, dashboard, and `morning-brief` all target the non-technical lens directly. The 296-row STATUS.csv is readable in Excel. Engine cooldowns/reliability have dedicated verbs. Only gap: no `--watch` or live-updating view for dispatch runs.

**Recover (2/5):** `engines-heal` is a good one-command recovery. But the proxy failure matrix (W9, still `todo`) means proxy failures are opaque. `preflight` exit-code ambiguity hides real problems. No `harness fix --auto` verb that resolves common warnings (e.g., git clean) without the operator understanding git.

## 5. Hand to a non-technical operator today?

**WITH GUARDRAILS.** The CLI surface is rich and `--profile non_technical` exists, but three critical seams require hand-holding: (a) initial env-var population has no guided path, (b) DPAPI seeding is invisible in the snapshot, and (c) preflight's warning-vs-failure semantics will confuse anyone who doesn't know exit codes. A 30-minute pairing session would cover it; alone, expect 90+ minutes of floundering.

## 6. Top 3 blockers

1. **`harness install --wizard` must demo env-var setting end-to-end** — show the exact Windows Settings dialog or auto-populate from a `.env` file.
2. **`harness preflight` needs human-readable pass/fail** — replace exit code 1 for warnings with "PASS with notes"; save exit 1 for actual failures.
3. **`harness quickstart` verb** — a single command that runs `doctor` → `install` → `init` → `preflight` with progress narration in `non_technical` profile, replacing the 4-step sequence the operator must currently memorize.

### M2-daily-workflow

## Rubric

1. **Install — 4/5.** Doctor/preflight are comprehensive and readable; `install` verb exists. Deduction: the `git_clean` warning in preflight output would confuse a non-technical operator ("what do I do?"). Needs a `harness clean` or actionable message.

2. **Daily run — 3/5.** `morning-brief` is the right concept, but the operator's sequence isn't scripted or documented. CLI options (`--mode`, `--engine-fill`) add cognitive load. Needs a `harness daily` wrapper or a one-page "Your Morning" card.

3. **Observe — 3/5.** `dashboard-serve` exists but it's unclear if it shows real-time status without reading files. `morning-brief` gives a snapshot. STATUS.csv is human-readable but 296 rows are overwhelming. No `harness status --summary` for quick pulse.

4. **Recover — 4/5.** `engines-heal`, clear escalation thresholds (`L1-L5`), `preflight` with explicit `[!]` vs `[OK]`. `doctor` output is actionable. Deduction: recovery path for the `git_clean` warning is missing from CLI help.

5. **Hand to a non-technical operator today?** **WITH GUARDRAILS.** The system has strong diagnostics (`doctor`, `preflight`, `morning-brief`) and clear escalation definitions, but the daily workflow lacks a curated, minimal command sequence. A non-technical operator could survive with a one-page guide and the dashboard, but would likely stall on warnings (git_clean) or misconfigure flags (`--engine-fill`). Install is near-ready; runtime operation needs a guided "safe mode" default.

6. **Top 3 blockers:**
   1. **`harness daily` script** — a single command that runs preflight, morning-brief, and prints a 10-line summary with today's focus (from STATUS.csv `todo` rows). Moves daily run score +1.
   2. **`harness status --summary`** — dashboard/CLI verb showing: engine health, last loop run, active escalations, top 3 todo items. Moves observe score +1.
   3. **Actionable warnings** — every `[!]` in preflight/doctor should have a `fix:` hint or `harness fix <issue>` verb. Removes install/recover friction.

### M3-error-recovery

## Rubric

1. **Install** — 3/5. Preflight exits with code 1 on a non-fatal warning (untracked files), which could confuse a non-technical operator who expects green=all clear.
2. **Daily run** — 4/5. The morning sequence (`doctor`, `preflight`, `morning-brief`) is clear and CLI-driven. Low toil.
3. **Observe** — 3/5. `status`, `heartbeat`, and `dashboard-serve` exist, but a typical failure (e.g., an engine timeout) isn't guaranteed to surface as a clear, actionable item in the dashboard without the operator knowing to run `engines-heal` or check logs.
4. **Recover** — 2/5. A Python traceback from an unexpected exception (e.g., a network blip causing a module error) would block the operator dead. They can't interpret it. The `engines-heal` and `panic-dump` commands are recovery tools, but the path *to* them from an opaque error is unclear.

5. **Hand to a non-technical operator today?** **WITH GUARDRAILS**. The operator can run the daily commands and use the dashboard for visibility. However, any failure that results in a raw Python exception will halt them. They need a "handle" for every common error type that avoids tracebacks and points to a CLI recovery command, or a reliable on-call Python-savvy backup.

6. **Top 3 blockers**:
   - **Standardize error surfacing.** All exceptions must be caught and rendered as a non-technical "operator packet" with a severity (e.g., `[L4]`), a plain-English summary, and a recommended CLI fix (e.g., `Run 'harness engines-heal --engine DeepSeek'`).
   - **Add a `harness recover` command.** A single entry point that runs a sequence of checks (`doctor`, `engines-heal`, `preflight`) and presents a pass/fail summary, giving the operator one command to try first.
   - **Make the escalation threshold contract explicit in output.** The `--escalation-threshold` setting should be printed in the `doctor` or `preflight` header so the operator knows what level of issue will surface vs. be silently handled.

### M4-observability

## Rubric

1. **Install** — 4/5. `doctor` and `preflight` are clean CLI commands with clear OK/FAIL output. But `git_clean` warning with exit code 1 requires knowing what "3 untracked files" means and whether it's safe to ignore — a non-technical operator won't know.

2. **Daily run** — 4/5. `morning-brief` + `harness loop` + dashboard-serve is a clear three-command sequence. The --help is legible. Missing: a single `harness start-my-day` wrapper that chains them, or a morning checklist in a non-technical-friendly format.

3. **Observe** — 3/5. This is the crux. Dashboard at 7878 + STATUS.csv + observer flags + morning-brief give surfaces — but STATUS.csv's "Notes" column is wall-of-text technical prose (commit SHAs, module names, KB counts). The observer's authority audit output format is unknown from the snapshot. The operator *can* see status, but interpreting it requires reading dense technical notes or clicking through a dashboard whose UX isn't described. The gap: no evidence of a human-readable "what happened overnight" narrative that the morning-brief actually produces in plain language.

4. **Recover** — 3/5. `engines-heal` exists, `engines-cooldowns` exists, `doctor` diagnoses env issues. But the W9 rows expose real gaps: proxy fail-open/fail-closed behavior is undocumented, silent exceptions aren't audited, and a non-technical operator facing a traceback has no `harness fix-it` or structured remediation flow. Recovery paths exist for engines; they're thin for everything else.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. The CLI surface is rich and the `doctor`/`preflight` commands gate startup. But observability relies on STATUS.csv whose Notes column reads like engineer commit logs, not operator guidance. The morning-brief may or may not produce plain-language output — the snapshot doesn't confirm it. An operator can *install and start the loop*, but would struggle to interpret what's happening or recover from non-engine failures without hand-holding.

6. **Top 3 blockers**
   - **`harness today` or morning-brief that outputs a plain-language "here's what happened, here's what needs attention"** — right now STATUS.csv Notes are developer prose, not operator guidance.
   - **`harness explain <ID>` that translates a STATUS.csv row into "what is this, is it blocking me, what do I do"** — closing the interpretability gap for the 296-row tracker.
   - **`harness fix-it` or structured remediation for common non-engine failures** (git dirty, observer flag raised, loop stalled) — right now only engine recovery has CLI verbs.

### M5-trust

## Rubric

1. **Install (4/5):** Preflight exits code 1 due to git untracked files. Doctor shows all OK. A non-technical operator could follow CLI commands but might be confused by the non-zero exit. Missing explicit "run `git clean`" guidance.

2. **Daily run (4/5):** `harness morning-brief` and `harness loop start` are clear. The operator can install via Task Scheduler. However, the expected morning sequence (brief → loop status → dashboard) isn't documented as a single "runbook" in the operator's language.

3. **Observe (3/5):** `dashboard-serve` exists, but the snapshot doesn't confirm it's designed for non-technical readability. `observer` output likely requires parsing logs. STATUS.csv is readable, but real-time loop health isn't surfaced in a simple CLI summary.

4. **Recover (3/5):** `engines-heal` and `preflight` are recovery commands. However, the git warning requires understanding version control. The `panic-dump` output likely contains traces. No clear "If you see error X, run command Y" table for common failures like engine cooldowns.

5. **Hand to a non-technical operator today?** **WITH GUARDRAILS.**
   The core CLI is robust with observer, heal, and status commands. A non-technical operator can install, start the loop, and check status. However, the lack of a plain-English runbook, non-obvious git warning resolution, and potential need to interpret observer logs for recovery means a technical "guardian" should be available for troubleshooting beyond basic operations.

6. **Top 3 blockers:**
   1. **Operator Runbook:** A `HARNESS_QUICKSTART.md` with the exact 3-command daily sequence (install → start → observe) and explicit remediation for the git warning.
   2. **Recovery Guide:** A `harness recover --what` command or a section in the runbook mapping `preflight` warnings and common `observer` flags to specific CLI fixes.
   3. **Simple Health Dashboard:** Enhance `harness loop status` or add `harness health` to output a plain-text summary: loop state, last observer pass/fail, and any active cooldowns—no file digging required.
