# Operator-UX thinking panel — synthesis

_Dispatched: 8 MiMo personas, elapsed 26s_

State snapshot fed to each reviewer is at `_state_snapshot.md`.

## U1-newbie-clone

**Top 3 changes (ranked):**
1. **`harness start` single-path wizard.** A single command that runs `doctor`, `preflight --fix --allow-stash`, generates a `.env` from a template (interactive key entry), starts the observer, and ends by opening `dashboard-serve`. Eliminates all command-choice paralysis and diagnostic interpretation.
2. **Profile-aware defaults that hide failure complexity.** When `--profile non_technical` is active (or detected), `preflight` should never exit non-zero on `git_clean`; instead, auto-stash with a loud warning and list files in plain language. Errors must show remediation as step-by-step commands, not just error codes.
3. **"Show me it works" trust demo.** After setup, the wizard runs a safe `harness dispatch ping-engine --dry-run` and prints a styled "✅ Your harness can talk to Engine [X]" with a timestamp and engine name. Proof, not just configuration.

**Wave 11 candidate:** `W11-FIRST-RUN-HEALTH-GATE`
*Acceptance criteria:* After `harness start` completes, the operator sees a single green status bar (e.g., "All 3 engines ready. Observer running. Queue empty. Next check: 09:00."). If any component is unhealthy, the gate shows a clear "Fix this now" link/step. No ambiguity about whether the system is operational.

**Kill or hide:** The top-level `engines-*` verb family (`engines-cooldowns`, `engines-heal`, `engines-reliability`). For a non-technical operator, engine management is a "call engineering" event. These should be moved under `harness engines --advanced` or accessed only via the dashboard's "Engine Health" panel, which can then show a "Copy this status for support" button.

**Minimum viable first-run path (≤5 steps):**
1. Double-click `harness-start.bat` (or run `harness start`).
2. Terminal prompts: "Enter your DeepSeek API key: _______"
3. Terminal prompts: "Enter your Kimi API key: _______" (or "skip").
4. Command auto-runs, shows progress ("Checking git... OK, Stashing files... OK, Starting observer... OK").
5. Browser opens to `localhost:8080` showing dashboard with a green "System ready" banner and a sample audit log entry.

**Trust seam:** **The morning email brief.** A non-technical operator trusts a daily email they didn't have to generate. `harness install` should offer to set up a 08:00 AM Windows Scheduled Task that runs `harness today --email operator@company.com`. The email is plain text: "Here's what happened overnight and your next actions." Seeing a reliable, unprompted summary in their inbox builds trust that the system is working autonomously.

---

## U2-installer-design

## INSTALLER DESIGNER LENS

### Top 3 Changes (2/10 → 7/10)
1. **Standalone executable installer** (`harness-setup.exe` / `.msi`). Bundles Python 3.12, all pip dependencies, and the harness code. Zero terminal commands until the wizard runs. Eliminates all `git clone`, `pip install`, environment confusion.
2. **Unified first-run wizard** that owns the entire setup flow: detects missing API keys, opens DPAPI window for secure input, runs a non-destructive integration test, and writes the daily Task Scheduler job. Single entry point, no choice paralysis.
3. **Daily ritual command** (`harness day-start`) that replaces the morning three-step. Runs preflight, generates brief, shows flags, and prompts for recovery in a TUI menu. One memorable verb.

### Wave 11 Candidate
`W11-INSTALLER-METRICS-AND-ROLLBACK`  
Acceptance criteria: The installer must record install method (exe/msi/winget), detected OS, Python source (bundled/system), and post-install smoke test pass/fail to `install_metrics.json`. On failure or user request, a one-click rollback must remove all installed files and Scheduled Tasks, leaving the original directory pristine.

### Feature to Kill/Hide
**Direct `harness dispatch` invocation**. For the non-technical operator, routing should be invisible. Hide `dispatch`, `burst`, `lock`, `coord`, and `orchestrator` behind a `--advanced` flag or a separate `harness expert` subcommand. The operator's surface is `today`, `morning-brief`, `observer`, and `engines heal`.

### Minimum Viable First-Run Path
1. **Download and run** `harness-setup.exe`.
2. **Wizard step 1**: Click "Install" (auto-bundles Python, pip, deps).
3. **Wizard step 2**: Paste your API keys into labeled fields (saves to DPAPI automatically).
4. **Wizard step 3**: Click "Test & Start" (runs `harness doctor --quick` and installs the `harness day-start` daily scheduled task).
5. **Done**. A `harness day-start` window opens with green checks.

### Trust Seam
A **post-install "smoke test" dashboard** that visually proves the full loop works. The wizard's final screen shows a mini-dashboard: three colored dots (git clean, API keys present, engine ping) and a "Run sample task" button that dispatches a dummy prompt to the cheapest engine and streams the output within the wizard itself. Seeing it *work* end-to-end in 30 seconds builds more trust than any log.

---

## U3-cli-vs-gui

**Top 3 changes for 2→7/10:**

1. **Replace CLI with persistent GUI.** A system-tray app (Electron/Wails) that launches on boot, shows a green/yellow/red status icon, and has a single-window dashboard. The 30+ commands become buttons in a clear hierarchy (Daily → Observe → Recover). The CLI remains for power users via `--expert` flag.

2. **Flatten the daily workflow to one screen.** The GUI opens every morning to a "Daily Brief" tab that auto-loads the output of `preflight`, `today`, and `observer flags` into a single, scrollable report with explicit "Next Actions" buttons (e.g., `[Fix Engine: DeepSeek]`). No command recall needed.

3. **Make first-run a guided wizard in the GUI.** On first launch, the GUI checks prerequisites (git, Python, API keys) via its own "Preflight" panel, presents each missing item with a 1-click "Fix" button or clear, embedded instructions ("Paste your DeepSeek API key here"), and confirms "Your harness is ready" before closing the wizard.

**Wave 11 candidate:**
`W11-GUI-RECOVERY-CARDS` — When the GUI detects a failure (dead engine, uncommitted changes), it pops a card that isolates the problem, shows a 2-sentence cause, and offers one or two large buttons for the safest fix (e.g., "Quarantine Engine" / "Show me the files"). Acceptance: a non-technical user can resolve any `[X]` preflight item using only the card without external help.

**Kill or Hide:**
**All CLI commands except `harness-gui`.** The operator-facing `--help` output is the root of overwhelm. Hide the entire CLI surface behind an "Advanced / CLI Mode" toggle in the GUI settings. The default experience is the GUI window only.

**Minimum viable first-run path:**
1. Double-click `xaxiu-harness-gui.exe` (installer creates this).
2. Walk through the 3-step setup wizard (it auto-detects requirements, guides key entry).
3. Click the "Start Daily Loop" button on the main screen.
4. Trust the green status icon in the system tray.

**Trust seam:**
**A live, real-time "Work Pulse"** in the GUI's status bar. It shows a tiny, updating feed of what the harness is doing right now (e.g., "Monitored DeepSeek → OK", "Awaiting operator input: #TASK-142"). Seeing continuous, benign activity is the tangible signal it's working.

---

## U4-error-recovery

## 1. Top 3 Changes (Leverage Ranking)

1. **Contextual error-to-recovery mapping**: Replace `[X] git_clean` with: `"[!] Uncommitted files: 'prompt.md', 'output.csv'. Fix: Run 'harness recover git' (stash & commit) or 'harness recover git --drop' (discard changes)."` One command, plain language, immediate action.

2. **A single `harness recover` wizard**: On any failure, the CLI prompts: `"Something needs fixing. What happened? [1] Engine died [2] Files are messy [3] Secret missing [4] I don't know."` Selecting "I don't know" runs a full diagnostic and outputs a numbered fix plan. No command memorization.

3. **Visual recovery progress**: After a fix, show a green bar: `"RECOVERY COMPLETE [██████████] 4/4 checks passed: Engine 'DeepSeek' reconnected, untracked files committed, secret 'OPENAI_KEY' detected, observer restarted."` The operator sees success, not just absence of errors.

## 2. Wave 11 Candidate Row

**W11-RECOVERY-WIZARD-INTERACTIVE**
Acceptance criteria: When `harness preflight` or any dispatch fails, the operator can type `harness recover` and enter an interactive TUI (text-based UI) that lists failures as simple questions, offers 1-2 fix options per item (with `--dry-run` previews), and executes chosen fixes sequentially with progress bars. Success = operator resolves 80% of common failures without leaving the wizard or reading documentation.

## 3. Feature to KILL/HIDE

**Kill `engines-heal` as a standalone verb.** It's a technical deep-dive command that overlaps with recovery flows. Hide it behind `harness engines --advanced heal` or merge its logic into the `recover` wizard's "Engine died" path. The operator shouldn't need to know the difference between `heal` and `reset` and `quarantine`.

## 4. Minimum Viable First-Run Path

1. `cd D:\xaxiu-harness-standalone`
2. `harness setup` (single command: checks Python, creates folder, seeds sample YAML, shows "✓ Ready").
3. `harness authenticate` (wizard: paste one API key, tests connection).
4. `harness day-start` (wraps `preflight` + `today`; output is a one-paragraph status with a single "✓ All clear" or "⚠ 1 issue—run `harness fix`").

Total: 4 commands, no decisions, no doc-reading.

## 5. Trust Seam

**The "wall of green" confirmation.** After any recovery or setup, display a 4-line ASCII dashboard:
```
ENGINES [✓ DeepSeek] [✓ Kimi]
FILES   [✓ 0 uncommitted]
SECRETS [✓ 3/3 detected]
OBSERVER[✓ Running]
```
This is the only trust signal that matters: a binary, visual summary of system health that matches their mental model of "everything is working." No log parsing required.

---

## U5-cost-visibility

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

---

## U6-trust-calibration

**Top 3 changes (2→7):**
1. **`harness today` as the one true command.** Collapse preflight/morning-brief/observer flags into one output: green status, tasks done overnight, cost, and next action in plain English. If only one command exists, this must be it.
2. **Visible trust heartbeat.** A persistent, human-readable "pulse" on the dashboard: green bar = active, amber = idle/error, with plain-text reason ("Working on ticket #123", "Waiting for operator input"). No log diving.
3. **Replace escalation levels with plain-language alerts.** Change `L1-L5` to "Low/Medium/High/Critical" with attached one-sentence remediation: "High: Engine X died. Click 'heal' or ignore for 24h." Non-technical operators can act on that.

**Wave 11 candidate:**
`W11-COST-PER-TASK-NORMALIZED`
Acceptance: Dashboard shows average cost per completed task (e.g., "Typo fix: $0.12, Feature draft: $1.45") with historical trend. Operator can instantly gauge efficiency vs. burning money.

**Feature to KILL/HIDE:**
The entire `engines` subcommand group (`engines-cooldowns`, `engines-heal`, `engines-reliability`). Replace with a single `harness engine-status` that shows only engine names + green/red + one-line cause ("OpenAI: healthy", "DeepSeek: key expired"). Technical root-cause belongs in `doctor --advanced`.

**Minimum viable first-run (5 steps):**
1. `harness init` → generates `config.yaml`.
2. Edit `config.yaml` → add API keys (guided prompts).
3. `harness install` → sets up Windows Task Scheduler for daily loop.
4. `harness today` → shows first status.
5. `harness dashboard-serve` → opens browser with live heartbeat + cost view.

**Trust seam:**
The **"yesterday's ROI" widget** on the dashboard: "Completed 8 tasks, cost $4.20, saved ~2h manual work. Last task: 'Drafted Q2 report summary'." Operators trust verifiable value delivery, not just uptime.

---

## U7-onboarding-content

**Top 3 changes (ranked by leverage):**

1. **Single "magic command" wrapper.** Create `harness day` that runs `preflight --operator`, `today`, and `observer flags` sequentially, with plain-language output and auto-fix for non-critical issues. All 20+ verbs become hidden subcommands; `--help` shows only `day`, `status`, `help`, and `feedback`.

2. **First-run wizard with zero terminal knowledge.** After double-clicking an installer EXE, a GUI window runs `doctor`, auto-fixes environment issues, asks 3 questions (project folder, operator name, optional schedule), and outputs a single shortcut: "Start My Day" that runs `harness day`.

3. **Visual status bar in the system tray.** A tiny icon (green/yellow/red) shows harness health. Green = overnight loop ran, no escalations. Yellow = warnings. Red = operator action needed. Hovering shows "Last run: 2 hours ago. 1 item needs you." Clicking opens `harness day` output in Notepad.

**Wave 11 candidate:**

`W11-FIRST-WEEK-TOUR` — On first 5 launches of `harness day`, the output includes a collapsible tip section (rendered in terminal colors) explaining one concept: "What the observer does," "What an escalation means," "How to read the budget," etc. Acceptance: after 5 days, the operator can explain what 3 of the 4 core concepts mean without referencing docs.

**Feature to kill/hide:**

Bury the full `--help` command list. Only expose via `harness help --all`. The primary `harness --help` output becomes 4 lines: "Run 'harness day' to start. Run 'harness status' for quick check. Run 'harness help --all' for advanced commands. Run 'harness feedback' to tell us what's confusing."

**Minimum viable first-run path (≤5 steps):**

1. Double-click `xaxiu-harness-installer.exe`
2. In the setup wizard, click "Choose Folder" and select your project.
3. Click "Start Setup" — it runs doctor, fixes environment, shows "✅ Ready."
4. Double-click "Start My Day" shortcut on desktop.
5. Read the plain-language summary: "Everything ran overnight. No problems. Suggested: check the budget report below."

**Trust seam:**

The **overnight heartbeat proof**. Every morning, `harness day` starts with: "At 3:14 AM, the harness ran 4 tasks successfully. No errors. Cost: $0.42." The specific timestamp and cost prove it's real, not a static message. This is the only signal that converts "I think it works" into "I know it worked while I slept."

---

## U8-pragmatic-roadmap

**Top 3 changes (ranked):**
1.  **`harness day-start` (one command)**: Replace the 3-command morning sequence with a single verb that runs `preflight`, then `today`, then `observer status`, piping the output into a clear, green/yellow/red terminal report. This eliminates decision fatigue and gives a single, trustworthy daily ritual.
2.  **`preflight --operator` profile**: Make this the default for non-technical users. It auto-silences `[X] git_clean` (run `git stash` automatically), explains `[!]` warnings in plain language ("Your API key for DeepSeek is missing"), and presents remediation as a simple "Run this command" line. Integrates the runbook.
3.  **First-run `harness init` wizard**: After `harness install`, the wizard should generate a `GETTING_STARTED.md` with a personalized 3-step plan (based on `doctor` output), set the operator profile, and schedule the first `day-start`. No choice, no docs to read.

**W11 Candidate:**
`W11-DASHBOARD-TRUST-CARD`
Add a single, auto-refreshing panel to `dashboard-serve` and `morning-brief` called "System Trust." It shows: 1) Last successful dispatch (timestamp, engine, result), 2) Next scheduled loop, 3) Observer status (green/red). Acceptance: A non-technical operator can glance at the card and in 5 seconds know if the system is healthy and active.

**Feature to KILL:**
**Hide 80% of the CLI.** Move `adapter`, `budget`, `burst`, `coord`, `engines-cooldowns`, `engines-reliability`, `lock`, `orchestrator` behind `--advanced` in `--help` or into a separate `harness-admin` command. The daily operator surface should be ≤10 verbs: `day-start`, `status`, `today`, `queue`, `observer`, `dashboard`, `engines-heal`, `doctor`, `init`, `panic-dump`.

**Minimum Viable First-Run Path:**
1.  Run `harness install` (schedules Task Scheduler, runs wizard).
2.  Wizard prompts: "Paste your API keys" (with links to get them). Wizard sets them in DPAPI.
3.  Wizard says: "Your first run is scheduled for tomorrow at 9 AM. To run now, type: `harness day-start`".
4.  Operator runs `harness day-start`.
5.  Sees: "System Trust: [GREEN] All engines ready. Last dispatch: [none]. Next loop: tomorrow 9:00 AM. Suggested: Run `harness queue list` to see the first task."

**Trust Seam:**
**The `day-start` summary must include a "Last 24h Success" counter**—a simple "X of Y tasks completed successfully" with a link to a plain-text log. A number that stays green over days is the only signal a non-technical user will believe long-term.

---
