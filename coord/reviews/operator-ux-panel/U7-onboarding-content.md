<!-- persona=U7-onboarding-content status=OK (23994ms) -->

# U7-onboarding-content

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
