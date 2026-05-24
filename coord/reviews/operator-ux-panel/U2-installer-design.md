<!-- persona=U2-installer-design status=OK (25615ms) -->

# U2-installer-design

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
