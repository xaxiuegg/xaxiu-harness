<!-- persona=U3-cli-vs-gui status=OK (22310ms) -->

# U3-cli-vs-gui

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
