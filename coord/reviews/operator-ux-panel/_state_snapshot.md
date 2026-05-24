## CLI verbs (`harness --help`)

```
Usage: python -m harness [OPTIONS] COMMAND [ARGS]...

  xaxiu-harness: dispatch, observe, and retro across LLM engines.

Options:
  --mode [review_each|full_dev_authority|dry_run]
                                  Operator mode: review_each /
                                  full_dev_authority / dry_run.
  --escalation-threshold [L1|L2|L3|L4|L5]
                                  Only escalations at or above this level
                                  surface to operator.
  --engine-fill [aggressive|conservative|manual]
                                  Whether to fill idle Kimi slots with queued
                                  work.
  --max-parallel-supervisors INTEGER
                                  Max supervisors that may run in parallel
                                  within a tick.
  --explore-on-uncertainty [dispatch_alternatives|inline|ask_operator]
                                  What to do when the dev manager is
                                  uncertain.
  --observer-cadence-minutes INTEGER
                                  Cadence for the workflow-audit observer
                                  cycle.
  --profile [technical|non_technical]
                                  Operator profile (affects packet templates /
                                  error verbosity).
  --help                          Show this message and exit.

Commands:
  adapter              Manage harness adapters (generate, list, validate).
  budget               Dispatch budget + per-engine cost ledger.
  burst                Temporarily route all traffic to one engine.
  coord                Coordinator commands: plan, run, integrate, status.
  dashboard-serve      Run the operator-facing dashboard.
  dispatch             Execute a packet; auto-route if no backend is given.
  doctor               Preflight: check git, python, DPAPI, secrets,...
  engines              Query or modify the engine pool.
  engines-cooldowns    Show active engine cooldowns.
  engines-heal         W8-ENGINES-HEAL: one-command recovery for dead /...
  engines-reliability  Show / publish engine reliability ranking from...
  env                  Check which API keys are set (reports per-key +...
  heartbeat            Passive dev-manager liveness signal for the operator.
  init                 Create starter adapter YAML for a project.
  install              Setup Task Scheduler entries and first-run wizard.
  lint-spec            Pre-flight: validate a markdown spec for...
  lock                 Exclusive routing lock (disables auto-routing).
  loop                 Autonomous dev loop — productized coord/dev_loop/...
  loops                Manage user-defined scheduled loops.
  memory               W5-S: engine-agnostic operator memory (memory/*.md...
  morning-brief        W5-RR 2026-05-23: end-of-overnight DeepSeek...
  observer             Independent harness observer — authority audit,...
  orchestrator         W5-T: autonomous orchestrator (Path α:...
  panic-dump      
```

## OPERATOR_RUNBOOK.md

```markdown
# Operator runbook — daily playbook

This page is for the **non-technical operator** running xaxiu-harness
day-to-day.  If you can edit YAML, run a command in a terminal, and
read a CSV file, you're set.  You will NOT need to write or read
Python.

If something below doesn't match what you're seeing on your machine,
your engineering teammate has changed something — ask them.

---

## Morning sequence — 3 commands

Every morning, run these three commands in the harness directory.
That's it.

```powershell
cd D:\xaxiu-harness-standalone
harness preflight
harness today
```

(After `harness today`, optionally run `harness morning-brief` for the
longer-form overnight handoff doc — most days `harness today` is enough.)

### What each does

| Command | What you see | If it complains |
|---|---|---|
| `cd D:\xaxiu-harness-standalone` | Moves the terminal into the harness directory.  Every `harness` command runs from here. | If the folder doesn't exist, the harness isn't installed yet — see `docs/INSTALL.md`. |
| `harness preflight` | Green checks (`[OK]`) for the engines, observer, loops, git, pytest cache, dead engines | Run `harness preflight --fix` (see below) |
| `harness today` | Plain-language summary: what shipped, recent audits, blockers, suggested next actions | If empty: nothing happened in the last 24h — that's fine |

If `harness preflight` shows all `[OK]` (or only `[!]` warnings),
you're good for the day.

If it shows `[X]` (fail), follow the **Recovery** section below.

---

## When preflight shows `[X]` — recovery

The harness has a single command that fixes the three most common
problems automatically:

```powershell
harness preflight --fix
```

This handles:

1. **`[X] git_clean`** — you have modified files that haven't been
   committed.  By default `--fix` will **not** stash them silently
   (W9-PREFLIGHT-FIX-NOSTASH — earlier silent stashes dropped
   in-progress work).  Instead it names the modified files and asks
   you to either:
   - Resolve manually with `git commit` or `git stash push`, or
   - Re-run as `harness preflight --fix --allow-stash` to opt in to
     the legacy auto-stash.  When you opt in, the success line
     starts with `[STASHED]` so the action is loud, and `git stash
     pop` will bring your work back.
2. **`[X] pytest_cache`** — leftover from someone's testing.  `--fix`
   clears it; pytest will rebuild on its next run.
3. **`[!] dead_engines`** — one of the LLM engines stopped working
   (key revoked, endpoint changed, rate limit).  `--fix` quarantines
   the bad engine so the harness routes around it.  You can reset it
   later with `harness engines reset <engine-name>` once your
   engineering teammate has fixed the root cause.

   For a richer view of the dead engine + a key-presence probe in one
   shot, run `harness engines heal` (or `harness engines-heal`).  It
   tells you whether the API key is back in DPAPI and, if so, marks the
   engine `recovering` so the dispatcher gives it one more attempt.

**Always preview first**:

```powershell
harness preflight --fix --dry-run
```

This shows exactly what `--fix` would do — no changes applied.
Re-run without `--dry-run` once you're happy with the preview.

---

## When preflight runs slow

Direct invocation of `harness preflight --skip-engines` and
`harness today` typically completes in ~7s on a clean machine.
Under contention (e.g. you're running them while a `harness
dispatch` is in flight), expect them to run up to 2× slower; this
is expected and the commands won't deadlock — they have bounded
PowerShell-probe timeouts (5s, with graceful degrade).  If the
operator-facing budget feels off (preflight regularly >15s, today
regularly >20s), report it and run `harness preflight --skip-engines`
with `--format json` to capture per-check timings.

---

## When something looks weird

These three commands answer "what's the harness doing?":

```powershell
harness morning-brief --since-hours 12   # last 12h activity
harness queue list                        # what's queued for the loop
harness observer flags                    # any escalations needing attention
```

If `harness observer flags` shows a HIGH severity flag, that's the
harness asking for help.  Read the message; if it's not obvious,
ask your engineering teammate — but **always** include the
output of `harness panic-dump` so they have full context (it's
secret-scrubbed automatically; safe to share).

---

## When you want to see the dashboard

```powershell
harness dashbo
```

## W9 readiness panel verdict

```markdown
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
- **Failure-mode recovery cards**: attach human-readable rem
```

## Operator profile (memory: user_non_technical_role)

The operator is NON-TECHNICAL.  Can:
  - Edit YAML, run CLI commands, manage Windows Task Scheduler
  - Read STATUS.csv

Cannot:
  - Author Python
  - Debug tracebacks
  - Read engine logs and root-cause issues

User-stated framing (2026-05-25): treats LLM tools like
ChatGPT/Claude Code (type, get answer).  Honest rating today
for that user profile: 2/10.

Wave 10 already queued (operator-readiness UX):
  W10-PREFLIGHT-EXIT-CODE-SEMANTICS, W10-DAILY-QUICKSTART-VERB,
  W10-ENV-VAR-WIZARD, W10-STATUS-CSV-OVERWHELM,
  W10-PREFLIGHT-REMEDIATION-CARDS, W10-PROFILE-AWARE-DEFAULTS,
  W10-DPAPI-SEEDING-VISIBILITY, plus 3 infrastructure rows.

Question: what would actually move 2/10 -> 7/10?  Not just W10
polish — the structural UX changes.
