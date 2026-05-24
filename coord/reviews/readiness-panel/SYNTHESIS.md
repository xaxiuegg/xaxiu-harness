# Harness readiness — 10-reviewer synthesis

_Dispatched: 10 personas, elapsed 152.8s_

State snapshot fed to each reviewer is at `_state_snapshot.md` in this directory.

## Per-persona responses

### K1-onboarding-friction

## Rubric

1. **Install** — 2. `doctor` reports OK while `preflight` hard-fails (exit 4) on dirty git, unregistered loop, and observer timeout; the 6+ remediation decisions (commit vs stash, loop start, observer retry vs scheduler check) exceed a non-technical operator's 30-minute runway.

2. **Daily run** — 3. `daily` and `morning-brief` are discoverable, but the CLI never signals that `install` → `env-wizard` → `loop start` → green `preflight` must precede them, forcing 6+ operator decisions before the first brief.

3. **Observe** — 4. `dashboard-serve`, `heartbeat`, `STATUS.csv`, and engine reliability commands give strong visibility without reading run files; only the observer probe timeout in preflight hints the observation layer may need a manual kick-start.

4. **Recover** — 3. `doctor`, `engines-heal`, and preflight fix-hints exist, but divergent advice (`doctor` OK vs `preflight` FAIL) and branching fixes (commit *or* stash; re-run *or* check scheduler) force decisions rather than a single obvious path.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. The CLI surface is rich with diagnostics and wizards, yet the first-run path is blocked by a failing preflight that demands git operations and distributed-system intuition; an operator needs a human runbook or babysitter for the initial 30-minute bootstrap, after which daily verbs are manageable.

6. **Top 3 blockers**:
   - `harness onboard` quickstart artifact — one ordered checklist/script from clone to first `morning-brief` replacing guesswork.
   - `harness preflight --fix` — auto-stash dirty files, start the loop, and retry observer probe instead of printing branching options.
   - `harness observer bootstrap` — one-shot scheduler registration that eliminates the ambiguous timeout remediation.

### K2-documentation

## Rubric

1. **Install** — 3. Preflight emits a hard FAIL (exit code 4) for git dirty and observer timeout that expects the operator to understand git stash or scheduler diagnostics, which is too much for a non-technical user.
2. **Daily run** — 4. Dedicated `daily` and `morning-brief` verbs show intentional low-toil design, though we cannot see their actual output to confirm the workflow is fully self-explanatory.
3. **Observe** — 4. Dashboard, morning-brief, and STATUS.csv provide multiple non-code views, yet the observer probe timeout proves the health pipeline itself can become opaque without warning.
4. **Recover** — 3. `engines-heal` and `env-wizard` cover engine and key issues, but typical first-run failures (git state, observer timeout) lack one-click remediation from the CLI.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. The CLI already surfaces plain-language "Run to fix" hints and operator-centric verbs (`daily`, `morning-brief`, `env-wizard`), so a non-technical user could likely run the routine day-to-day once past setup. However, the initial bootstrap still crashes into a hard preflight FAIL that requires git and scheduler literacy, meaning they would need a technical buddy on-call for installation and any observer hiccup.

6. **Top 3 blockers**
- `harness preflight --fix` (or `harness fix`): a single command that auto-stashes git, registers the dev loop, and restarts the observer so the operator never manually touches git or Task Scheduler.
- `harness observer start` with guaranteed bootstrap: eliminate the timeout-based hard blocker by shipping a resilient start verb that retries and self-heals instead of surfacing FAIL.
- `docs/OPERATOR_QUICKSTART.md`: one-page morning routine with exact copy-paste blocks and a jargon glossary (DPAPI, packet, retro), because `--help` and preflight still read like developer tools.

### K3-failure-modes

## Rubric

**Failure modes (first month):**
1. **Git-dirty preflight FAIL** — Message is clear to a developer, but “Commit or stash” assumes git fluency; a non-technical operator will ping engineering. Recovery is not CLI-obvious.
2. **Observer probe timeout** — “Timed out” is clear, but the fix (`harness observer scheduler-status`) is opaque; if re-running preflight fails, operator pings engineering.
3. **Both-engines-failed (DeepSeek+MiMo cascade)** — The error is explicit, yet no CLI verb resolves a content-filter/key root cause; operator must ping engineering.
4. **Loop not registered** — Clear warning with exact fix (`harness loop start`); recovery is obvious without help.
5. **STATUS.csv blindness** — No error message, but 310 rows drown signal; operator lacks a filtered view and likely gives up reading it.

1. **Install** — 2. `env-wizard` eases API keys, but the git-dirty hard block + observer warnings make a ≤30-min green preflight unlikely without engineering help.
2. **Daily run** — 3. `daily` and `morning-brief` exist, yet sequencing isn’t self-evident; low-toil only after memorization or docs.
3. **Observe** — 3. Dashboard and `heartbeat` help, but observer timeout in preflight and noisy CSV erode confidence.
4. **Recover** — 2. `engines-heal`/`env-wizard` cover simple paths, yet git blocks and engine-cascade failures lack operator-grade recovery.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. Core commands exist, but preflight assumes git literacy, STATUS.csv is a firehose, and engine outages degrade to opaque errors. It is usable only if an engineer pre-clears git/loop state and remains on-call for engine-level failures.

6. **Top 3 blockers:**
- **`harness morning` unified verb**: Sequences daily/brief/preflight and narrates blockers in plain English.
- **`harness status today` filter**: Hides 300+ shipped rows to surface only active blockers.
- **`--operator-safe` preflight flag**: Auto-stashes or bypasses git dirty state so non-coders aren’t hard-blocked.

### K4-cli-ergonomics

## Rubric
1. **Install** — 2. `env-wizard` and `doctor` are clear, but preflight hard-blocks on git cleanliness and loop registration, forcing git fluency and navigation of the `loop` vs `loops` naming split.
2. **Daily run** — 2. `daily` and `morning-brief` exist, yet the 22-verb surface offers no obvious sequencing guardrails; a non-technical operator cannot infer the morning ritual from `--help` alone.
3. **Observe** — 2. `dashboard-serve` and the `observer` group exist, but there is no top-level `status` verb; the operator must read `STATUS.csv` or know to invoke `coord status` and `observer scheduler-status`.
4. **Recover** — 3. `doctor`, `engines-heal`, and preflight fix-hints are strong, but recovery is fragmented across `loop start`, nested `observer` subcommands, and manual git steps.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. The first-run wizards and preflight gate pattern are solid, but the 22-verb API surface is overwhelming, status is fragmented across files and nested subcommands, and hard blockers require git operations and precise verb recall that a runbook alone cannot bridge without L1 support.

6. **Top 3 blockers**:
   - **Top-level `harness status` verb**: A single daily, non-CSV, dashboard-in-terminal summary of loop, observer, and engine health (not buried under `coord`).
   - **`harness fix` meta-recovery verb**: One-command auto-remediation of preflight failures (git stash, observer restart, loop re-register) so the operator never touches git directly.
   - **Operator-slim CLI mode**: A `--simple` flag or role that hides the 15+ advanced verbs (adapter, lint-spec, lock, burst, etc.) and surfaces only daily, status, stop, and fix.

### K5-honest-readiness

## Rubric

1. **Install** — 1. Preflight exits 4 with git_clean and observer timeout; “commit or stash” is not something a non-technical user does.  
2. **Daily run** — 2. `harness daily` exists, but the routine is blocked by preflight failures and an unregistered dev loop.  
3. **Observe** — 3. Dashboard and morning-brief are operator-friendly, yet the observer probe timing out means the picture cannot be trusted without help.  
4. **Recover** — 2. Engine-specific healing exists, but bootstrap failures (git state, loop registration, observer hang) lack one-button remediation.  

5. **Hand to a non-technical operator today?** NO. The surface area is impressive, but the very first gate—`harness preflight`—hard-fails with a git hygiene error and an observer timeout. A non-technical friend cannot stash commits or debug why the observer probe hangs. Until the harness can bootstrap itself from a fresh clone to a green preflight without Python or git knowledge, it remains a dev tool, not an operator appliance.

6. **Top 3 blockers**
   - `harness install --autonomous` that auto-resolves git_clean (auto-stash or ignore), registers the dev loop, and seeds the observer so preflight exits 0 on first run.
   - `harness daily --repair` that internally fixes preflight/loop/observer warnings before doing work, collapsing the morning routine to one command.
   - A bulletproof `dashboard-serve` that falls back to a static, engine-less status page when the observer is down, guaranteeing the operator always has a readable health view.

### M1-install

## Rubric
1. **Install (2/5)** – `harness doctor` shows env vars can be set via `env-wizard`, but the fresh-clone operator hits `preflight` blockers (git dirty, loop task not registered) that require understanding git and Task Scheduler beyond basic commands.
2. **Daily run (3/5)** – The `daily` verb exists, but the example `preflight` output shows a FAIL with instructions like "Commit or stash"—toil that requires git knowledge.
3. **Observe (4/5)** – `STATUS.csv`, `dashboard-serve`, and CLI commands (`heartbeat`, `morning-brief`) give visibility without reading raw files.
4. **Recover (4/5)** – Preflight errors have explicit "Run to fix" commands; `engines-heal` and `doctor` provide guided recovery.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. The operator can run commands and follow guided wizards, but the initial `preflight` failure due to git state and unregistered loops would stop them cold. They’d need a one-time setup script that automates git commit and loop registration, or a human helper for that first hurdle.

6. **Top 3 blockers**
   - **First-run script missing** that auto-commits/stashes and runs `harness loop start` to clear common `preflight` fails.
   - **Git-clean check in preflight** is too strict for a fresh clone; it should allow a known-clean repo or provide a non-interactive fix command.
   - **Loop registration** must be part of `install` or `init`, not a manual step.

### M2-daily-workflow

## Rubric
1.  **Install: 3/5** — Guided `install` and `env-wizard` exist, but a non-technical operator must troubleshoot `preflight` failures (git clean, loop registration) without clear, single-command fixes.
2.  **Daily run: 4/5** — `morning-brief` is the right verb, but its utility is undermined by a `preflight` that fails on common issues (stale git state), forcing extra steps.
3.  **Observe: 4/5** — `morning-brief`, `doctor`, `preflight`, and STATUS.csv provide layered observability. The operator avoids digging in `runs/`, but must correlate multiple command outputs.
4.  **Recover: 4/5** — CLI outputs include actionable "Run to fix:" hints and a dashboard. Failure modes are logged, but recovery for observer timeouts is vague ("will retry").

5.  **Hand to a non-technical operator today?** **WITH GUARDRAILS.** The CLI is self-documenting enough for daily flow (`morning-brief`, `preflight`), and STATUS.csv is readable. However, a blocked `preflight` (as shown) requires manual intervention that assumes basic git literacy or a support channel, creating a dependency on technical backup.

6.  **Top 3 blockers**
    *   **A `harness preflight --autofix` command** to auto-stash git changes and register loops, moving install/observe from a 3→5.
    *   **A single `harness daily` subcommand** that chains `morning-brief` + `preflight` with a clear success/failure summary, reducing command recall burden.
    *   **An observer probe health-check in `doctor`** to proactively surface and fix the timeout warning, increasing recovery confidence from a 4→5.

### M3-error-recovery

## Rubric

1. **Install** — **4/5.** `doctor` and `preflight` are clean, one-command gates. But the `git_clean` fail says "Commit or stash" without the exact command — a non-technical operator will stall here and have to escalate. Needs `git stash` copy-paste guidance inline.

2. **Daily run** — **4/5.** `harness morning-brief` + `harness daily` exist; loop start hint is explicit. The observer warning ("will retry next preflight") means the operator just re-runs — acceptable. Minor toil: if re-run also times out, there's no second-step guidance.

3. **Observe** — **3/5.** STATUS.csv is scannable, `dashboard-serve` exists, `heartbeat` is listed. But we see no evidence the dashboard surfaces engine health, escalation history, or loop status in non-technical language. The 310-row CSV is the primary observability surface — that's a raw file, not an operator experience.

4. **Recover** — **3/5.** `engines-heal` is a strong verb for the most common failure. Preflight gives "Run to fix:" hints, which is the right pattern. But two gaps: (a) the L5 escalation contract has no visible output template — when an L5 fires, what does the operator *see* and *do*? Unknown. (b) Observer timeout → "re-run or check scheduler-status" — if the scheduler itself is broken, the operator is dead with no next step.

5. **Hand to non-technical operator today?** **WITH GUARDRAILS.** The CLI verbs and preflight hints are 80% there. A non-technical operator can install, run daily, and recover from dead engines. But the `git_clean` blocker has no copy-paste fix, L5 escalation behavior is undocumented in the snapshot, and observability requires reading raw CSV. With a short runbook covering those three gaps, this is hand-offable within a day.

6. **Top 3 blockers**
   - **`git_clean` remediation is not copy-pasteable.** Preflight should print `git stash` or auto-stash with `--fix` flag. Single biggest blocker for non-technical operator.
   - **No L5 escalation output contract visible.** Operator needs to see what an L5 surface looks like and what the single action is. Without this, autonomous mode is a black box on hard failures.
   - **Observer has no second-tier recovery path.** If `observer scheduler-status` also fails, the operator needs `engines-heal`-style one-command recovery or a clear "file this" packet — neither is present.

### M4-observability

## Rubric

**1. Install — 3/5**
`doctor` + `preflight` surface issues with clear "Run to fix:" hints — excellent. But preflight *currently fails* (exit code 4) and resolving the `git_clean` blocker requires git knowledge the operator lacks. No one-click `preflight --fix` path exists.

**2. Daily run — 4/5**
`morning-brief`, `daily`, and `coord status` form a clear triad. Observer cadence runs autonomously. Minor deduction: the brief output wasn't shown — can't confirm it surfaces everything the operator needs (dispatch outcomes, engine health, blockers).

**3. Observe — 2/5**
This is the weakest surface. The **dashboard at 7878** is the primary visibility layer for a non-technical operator, but its actual rendered content is unknown — I can't verify it shows dispatch status, engine health, or escalation flags. STATUS.csv is canonical but is a flat file the operator must open; 310 rows without filtering/facets is opaque. Observer flags exist but the probe is currently *timed out*, so this surface is dark. The gap between "I can run `coord status`" and "I can watch a run without opening `runs/`" is large.

**4. Recover — 3/5**
`engines-heal`, `engines-cooldowns`, and `preflight` remediation hints are good. The MiMo filter issue shows the team *documents* failures in STATUS.csv with root cause — exemplary. But stderr tracebacks from dispatch failures have no operator-friendly translation; when something breaks mid-run, the operator must still dig into files or paste output to someone technical.

**5. Hand to a non-technical operator today? — WITH GUARDRAILS**
The CLI surface is well-designed for the profile: verb-noun commands, `doctor`/`preflight` gates, remediation hints. But three gaps block autonomous operation: preflight is currently failing with no self-service fix for the git blocker, the observer watchdog is down (so the operator's monitoring safety net is absent), and the dashboard's actual adequacy is unverified. With a technical person on call for escalations and a same-day fix for the preflight/git issue, it's usable today. Without that, the operator will get stuck within the first hour.

**6. Top 3 blockers**

1. **Dashboard rendering audit** — ship screenshots or a spec of what the 7878 dashboard actually shows; if dispatch status, engine health, and escalation flags aren't rendered, the non-technical operator has no real-time observability. Fixing this could move overall score from ~3 to ~4.
2. **Preflight self-repair for `git_clean`** — add a `harness preflight --autofix` that runs `git stash` automatically. Currently this is a hard blocker the operator can't resolve alone.
3. **Observer probe timeout resolution** — the observer is the watchdog on dev-manager authority; with it dark, there's no autonomous safety net. Either auto-restart it in the install path or surface the failure as a dashboard banner with a one-click remediation command.

### M5-trust

## Rubric

1. **Install** — 3/5
Preflight clearly surfaces blockers with actionable "Run to fix:" steps, but git_clean failure requires git knowledge (commit/stash) beyond stated operator capabilities.

2. **Daily run** — 3/5
`harness daily` (W10-DAILY-QUICKSTART-VERB) exists and is operator-labeled, but dev loop warning blocks autonomous start—operator cannot self-remediate.

3. **Observe** — 3/5
Observer module shipped (W20-OBSERVER) with dashboard/status CSV, but probe timeout means monitoring cannot be verified functional—observer is the check on dev-manager authority.

4. **Recover** — 4/5
Preflight's "Run to fix:" paths are clear. STATUS.csv provides task-level visibility. Doctor output confirms infrastructure health.

5. **Hand to non-technical operator today?** — **NO**

Preflight FAIL (exit code 4) is a hard blocker refusing autonomous mode. The observer probe—the independent check on dev-manager authority—is timing out, meaning the "trust but verify" loop is broken. The operator cannot un-stick git state without Python/git knowledge. While the architecture shows good safety design (L1-L5 escalation thresholds, `explore-on-uncertainty` options, audit-followup-commit-policy), these mechanisms cannot be exercised because the loop cannot start. Trust in autonomous operation requires both the loop running *and* the observer confirming its behavior; neither condition holds.

6. **Top 3 blockers**
1. **Git auto-clean** — Ship `harness preflight --fix` or auto-stash so operator never hits this wall
2. **Observer reliability** — Fix probe timeout; observer is the sole check on dev-manager authority
3. **Loop registration self-heal** — `harness loop start` should be called by preflight when warning detected, not operator responsibility
