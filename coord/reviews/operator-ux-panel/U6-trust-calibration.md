<!-- persona=U6-trust-calibration status=OK (20143ms) -->

# U6-trust-calibration

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
