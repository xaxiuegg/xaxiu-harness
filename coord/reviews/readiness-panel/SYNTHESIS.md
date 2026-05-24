# Harness readiness — 10-reviewer synthesis

_Dispatched: 10 personas, elapsed 163.0s_

State snapshot fed to each reviewer is at `_state_snapshot.md` in this directory.

## Per-persona responses

### K1-onboarding-friction

## Rubric

1. **Install** — 2. The fresh-clone path forces ~8 operator decisions (which of 3 docs, install method, global flags, `doctor` vs. `preflight`, how to fix `git`/ `pytest`/ dead-engine failures); `preflight` fails on `pytest_cache` and `git_clean` with fixes requiring Python/git skills, and dead-engine remediation points to unreadable JSONL logs.
2. **Daily run** — 3. `harness morning-brief` is a single obvious verb, but the first-run sequence is gated by red `preflight` checks that a non-technical operator cannot clear autonomously, creating toil before the briefing ever runs.
3. **Observe** — 4. `morning-brief`, `dashboard-serve`, `STATUS.csv`, and `coord status` provide rich, engine-log-free visibility; the operator never needs to open `runs/` files by hand.
4. **Recover** — 2. Remediation hints (`fix: Inspect state/engine_performance_log.jsonl`, `Run pytest, fix failures`) demand traceback literacy and log analysis; there is no `harness recover` automation to bridge the gap.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. A non-technical operator can consume `morning-brief` and `STATUS.csv` once the system is green, but cannot independently clear `preflight` (pytest failures, dead-engine triage, git stashing) or install Python dependencies. They need a technical owner to prep the environment and handle any red preflight state.

6. **Top 3 blockers**
- `--operator` preflight mode that skips dev-only gates (`pytest_cache`) and auto-quarantines dead engines instead of asking the operator to read JSONL.
- Single-page onboarding doc that collapses 20+ CLI verbs into an exact 3-command path: `install` → `doctor` → `morning-brief`.
- `harness recover` command that automates safe fixes (git stash, engine quarantine) and presents plain-language confirmation instead of tracebacks or raw state files.

### K2-documentation

## Rubric

1. **Install** — 2. Preflight emits fixes, but "inspect JSONL" and "fix pytest failures" require dev skills; engine quarantine and test repair are not self-service for a non-coder.
2. **Daily run** — 3. `morning-brief` and `heartbeat` exist, yet the CLI lists 25+ verbs with no daily sequence spelled out; the operator must hunt for the right ones.
3. **Observe** — 4. `dashboard-serve`, `observer`, and STATUS.csv give visibility without opening `runs/`, but 269-row CSV lacks a plain-language summary for quick scanning.
4. **Recover** — 2. Failures surface clearly, yet remediation text points to JSONL logs, git stash, and pytest runs rather than simple CLI verbs or click-to-fix actions.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. The CLI surfaces problems in plain English and offers `morning-brief`, but a non-technical operator cannot act on engine quarantine, pytest failures, or JSONL logs without assistance. They could run the daily loop if a technical owner handled initial setup and kept preflight green, but self-recovery is out of reach.

6. **Top 3 blockers:**
- `docs/operator-runbook.md` — one-page daily checklist (morning-brief → dashboard → observer) written for non-technical readers.
- `harness preflight --fix` — auto-remediates dead engines (auto-quarantine), dirty git (auto-stash), and stale pytest cache without Python knowledge.
- `harness status --today` — human-readable overnight summary replacing 269-row CSV archaeology.

### K3-failure-modes

## Rubric
1. **Install** — 2. Preflight fails on pytest cache and git state, and dead-engine remediation requires inspecting JSONL; a non-technical user cannot reach green unassisted.
2. **Daily run** — 3. `morning-brief` and `heartbeat` exist, but no single obvious daily checklist is surfaced; operators must juggle verbs and flags.
3. **Observe** — 3. STATUS.csv is readable, yet engine health and loop diagnostics still push operators toward JSONL/logs rather than a self-service dashboard.
4. **Recover** — 2. Preflight prints "fix:" hints, but every common failure routes to actions (pytest, git, JSONL) a non-technical operator cannot execute alone.

**Failure modes (first month)**
- **Dead engines** — Error clear (`[!] dead_engines`); recovery ("inspect JSONL / quarantine") is opaque → **ping engineering**.
- **Pytest cache blocking autonomy** — Error clear (`[X] pytest_cache`); recovery ("Run pytest, fix failures") requires coding → **ping engineering**.
- **Git dirty state** — Error clear (`[X] git_clean`); recovery ("Commit or stash") is borderline for a non-technical user → **likely ping engineering**.
- **Silent missing API keys** — Error unclear (`doctor` shows UNSET keys but overall OK); failure surfaces later with no obvious recovery → **ping engineering**.
- **Mid-loop routing failure** — Error unclear (buried in `runs/` files); no CLI recovery path → **ping engineering**.

**Hand to a non-technical operator today?** WITH GUARDRAILS. The daily verbs and STATUS.csv are accessible, but nearly every preflight failure mode routes to technical remediation the operator cannot execute alone. They can run the harness only if an engineer pre-clears the environment and stands by for escalations during the first month.

**Top 3 blockers**
- `harness preflight --fix` flag to auto-stash git, reset pytest cache, and quarantine dead engines.
- `harness operator-report` command translating every `[X]`/`[!]` into plain-language, copy-paste Windows/Task Scheduler instructions.
- `docs/OPERATOR_RUNBOOK.md` with exact non-technical remediation steps and screenshots for each preflight failure.

### K4-cli-ergonomics

## Rubric

1. **Install** — 2. `harness install` and `doctor` are helpful, but `preflight` fails on `pytest_cache` (expects the operator to run/fix Python tests) and `dead_engines` remediation requires inspecting a `.jsonl` log—both violate the no-code constraint.
2. **Daily run** — 3. `morning-brief` is a well-named primitive, yet it is buried among 22 verbs with no single obvious “start my day” sequence or alias surfaced in the CLI.
3. **Observe** — 3. `dashboard-serve`, `STATUS.csv`, and `observer` provide visibility, but there is no top-level `status`/`today` command; the operator must manually synthesize `coord`, `engines`, and `observer` output.
4. **Recover** — 2. `preflight` and `doctor` surface hints, but fixes for engine death and pytest cache require code changes or structured-log forensics, leaving a non-technical operator stuck.

## Operator readiness

5. **Hand to a non-technical operator today?** WITH GUARDRAILS. They can run `harness install`, read `STATUS.csv`, and open the dashboard, but any `preflight` failure—especially `pytest_cache` or dead engines—requires Python debugging or JSONL inspection they cannot perform. A technical teammate must greenlight the first run and handle engine rotation.

## Top 3 blockers

6. **Top 3 blockers**
   - **`harness today` (or `status`) verb:** a single human-readable summary of loop health, last dispatch, and observer alerts, eliminating the need to manually join `coord`/`observer`/`engines` output.
   - **`harness preflight --fix` / `harness quarantine`:** automated remediation for dead engines and stale pytest cache without asking the operator to touch source code or `.jsonl` logs.
   - **`harness daily` alias:** one obvious entry point that composes `morning-brief`, loop liveness, and observer status; 22 verbs create decision paralysis for non-technical users.

### K5-honest-readiness

## Rubric

1. **Install** — 2. Preflight fails on dead engines, dirty git, and pytest cache; remediation requires inspecting JSONL logs and fixing Python tests, which is out of scope for a non-technical user.
2. **Daily run** — 2. No documented daily sequence; CLI is crowded with verbs like `burst`, `lock`, and `orchestrator`, creating decision fatigue instead of a single obvious morning command.
3. **Observe** — 3. `dashboard-serve` and `morning-brief` help, but STATUS.csv remains developer-centric (commit hashes, coverage %, UUIDs), so the operator lacks an at-a-glance human-readable pulse.
4. **Recover** — 2. Failure messages point to logs and git stash/pytest fixes; there is no non-technical one-click remediation for dead engines or dirty repo states.

5. **Hand to a non-technical operator today?** NO. The harness boots into a failing preflight that demands git hygiene, pytest cleanup, and manual engine log inspection. The CLI vocabulary and STATUS.csv are written for developers, leaving a non-technical friend stuck before day one with no self-service path back to green.

6. **Top 3 blockers**
   - **Zero-friction installer**: A first-run wizard that auto-selects working engines, suppresses dev-only pytest/git checks, and writes Task Scheduler entries without requiring a green preflight.
   - **Plain-language status view**: A `harness status --human` or dashboard pane that translates STATUS.csv into "what happened today / what's broken / what to click" without UUIDs or commit hashes.
   - **One-click self-healing**: An `harness engines heal` command that auto-quarantines dead engines and fails over to live ones, eliminating JSONL log inspection and key rotation manual steps.

### M1-install

## Rubric
1. **Install**: 3/5 — `harness doctor` and `harness install` provide a clear path, but dead engines (preflight) require troubleshooting API keys and state files, likely needing help.
2. **Daily run**: 2/5 — Morning sequence (`preflight` → `loop`) is logical, but fixing `dead_engines` and `git_clean` failures isn't obvious without guidance; the non-technical operator can't parse the engine log.
3. **Observe**: 3/5 — `dashboard-serve`, `heartbeat`, and `STATUS.csv` give visibility, but correlating issues (e.g., from `observer` or `preflight`) into a simple "is it healthy?" view isn't automatic.
4. **Recover**: 2/5 — `preflight` lists fixes like rotating keys or stashing, but the operator lacks `doctor --fix` or one-command key rotation; dead engines and pytest failures require Python debugging.

**5. Hand to a non-technical operator today?** NO.
The operator can run commands, but the preflight failures (dead engines, dirty git, test failures) require inspecting JSONL logs, rotating API keys at the provider level, and debugging Python tests—tasks beyond their capability. Without a "fix" or "health-check" command that automatically resolves common issues (like `harness doctor --fix`), they will get stuck immediately.

**6. Top 3 blockers**
1. **`harness doctor --fix`** (missing): Should auto-stash git, rotate/quarantine dead engines, and skip failed tests.
2. **Key rotation CLI** (missing): `harness engines rotate <engine>` to refresh keys without env-var editing.
3. **Preflight ignore/override** (missing): `harness preflight --force` to bypass non-critical warnings for initial runs.

### M2-daily-workflow

## Rubric

1. **Install** — 3/5: `harness install` + wizard exists, but `preflight` failures (dead engines, dirty git) require troubleshooting beyond "press a button."
2. **Daily run** — 4/5: `harness morning-brief` is the obvious start, but 2/6 preflight checks failing today adds cognitive load for diagnosis.
3. **Observe** — 5/5: `dashboard-serve` + `heartbeat` + `coord status` + `STATUS.csv` give clear, non-log-dependent visibility.
4. **Recover** — 3/5: CLI fix hints exist, but "rotate keys or quarantine" and "commit or stash" assume technical knowledge the operator lacks.

5. **Hand to a non-technical operator today?** WITH GUARDRAILS.
   Reasoning: The core workflow (install, morning brief, observe dashboard, read STATUS.csv) is accessible. However, recovery from today's preflight failures (engine rotation, git operations) requires technical support. The system is ready for supervised use but not fully self-service for error recovery.

6. **Top 3 blockers:**
   1. `preflight` fix hints need a `--non-technical` mode that offers copy-paste commands or "ask for help" escalation.
   2. Intermittent dead engines (anthropic, gemini) suggest missing auto-quarantine or `harness engines --auto-fix`.
   3. No `harness morning-brief --summary` that outputs a plain-English "green/yellow/red" with next action.

### M3-error-recovery

## Rubric

1. **Install** — 2/5 — Preflight fails on `dead_engines` and `git_clean`. Fix for dead engines points to a JSONL log the operator cannot parse. Git fix is clear (`git stash`). Preflight is a blocker gate, so a fresh clone would not go green.
2. **Daily run** — 3/5 — `harness morning-brief` is obvious. However, preflight (likely a morning prerequisite) will fail until the operator resolves technical issues, which is not low-toil.
3. **Observe** — 5/5 — STATUS.csv, dashboard, and CLI (`status`, `heartbeat`) provide full visibility without needing to read raw files or logs.
4. **Recover** — 1/5 — Critical failure: `pytest_cache` fix says "Run pytest, fix failures, then retry." The operator cannot debug or fix Python test failures. This blocks them dead. The `dead_engines` fix also requires reading a performance log and potentially rotating API keys—a technical task.

5. **Hand to a non-technical operator today?** NO.
The operator would be immediately blocked by the `pytest_cache` preflight failure. The remediation path ("fix failures") requires Python debugging, which is outside their capabilities. Without a single command to reset or clear this state (e.g., `harness preflight --clear-failures`), the harness is unusable for them.

6. **Top 3 blockers**
    1. **`pytest_cache` failure remediation** — Needs a `harness fix tests` command that runs tests and either clears the cache on pass or presents a non-technical-friendly summary on failure.
    2. **`dead_engines` remediation** — Needs `harness engines quarantine <engine>` or a clear CLI command to rotate/reload keys, hiding the JSONL log.
    3. **Escalation contract for L5 (Python bugs)** — Need a concrete `harness panic-dump` + support-send workflow so the operator knows exactly what to do (e.g., "run `harness support send`") when a Python traceback surfaces, rather than just seeing an error.

### M4-observability

## Rubric
1. **Install — 2/5** — Preflight fails (dead engines, test failures) requiring Python/git debugging beyond YAML/CLI skills.
2. **Daily run — 4/5** — `dashboard-serve`, `morning-brief`, and `heartbeat` exist; sequence is logical if preflight is green.
3. **Observe — 3/5** — STATUS.csv, dashboard, and observer flags are good surfaces, but engine health and test failures require inspecting `state/` logs.
4. **Recover — 2/5** — Remediation hints exist in `doctor`/`preflight` output but require understanding "rotate keys," "fix failures," or reading `lastfailed`.

## 5. Hand to a non-technical operator today? **NO**
The harness has strong observability surfaces (STATUS.csv, dashboard, observer flags) and the CLI is well-structured for a non-technical operator. However, the current snapshot shows actionable blockers—dead engines and test failures—that the operator cannot resolve with their allowed skills (YAML edits, CLI commands, Task Scheduler). The remediation messages ("rotate keys," "run pytest, fix failures") are too vague for someone who cannot read logs or author Python. Without first clearing these blockers and ensuring `harness preflight` passes green, handing this over would leave the operator stuck on day one.

## 6. Top 3 blockers
1. **Dead engines** — Provide a one-command `harness engines-quarantine` or key-rotation wizard that the operator can run without inspecting `state/` files.
2. **Test failures** — Either auto-fix or surface a clear "acknowledge and skip" path for the operator, since they cannot debug pytest.
3. **Preflight verbosity** — Transform "modified tracked files" and "last run had failures" into guided CLI flows (e.g., `harness preflight --fix`) that handle or explain each issue interactively.

### M5-trust

## Rubric

1. **Install** (2/5): Preflight fails with two blockers: dirty git state and pytest failures. Fix instructions require Python/debugging (run pytest, commit). Non-technical operator cannot resolve without assistance.

2. **Daily run** (3/5): `morning-brief` command exists, but sequence isn't obvious. Requires knowing to run preflight first, which currently fails. No clear "start my day" script.

3. **Observe** (4/5): STATUS.csv is operator-readable. Dashboard command exists. Observer commands available but not simplified for non-technical use.

4. **Recover** (2/5): Remediation paths are technical. "Run pytest, fix failures" and "rotate keys or quarantine engine" require Python/engine knowledge. No simplified recovery CLI for common issues.

5. **Hand to non-technical operator?** NO. The preflight failures block autonomous use, and recovery requires technical intervention. Without resolving git state and test failures, the operator cannot safely start the loop. The trust contract isn't established because the operator cannot verify the system is in a clean state.

6. **Top 3 blockers**:
   - **`harness fix --non-technical`** command that auto-commits stashes and runs pytest via CI, providing plain-language results.
   - **`harness loop --start`** wrapper that runs preflight, fails clearly with dashboard instructions if red, then starts with safe defaults (L5 escalation, conservative mode).
   - **`harness recover --common`** that handles dead engines (rotate keys automatically) and git state (stash changes) with non-technical explanations.
