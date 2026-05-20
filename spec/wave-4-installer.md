# Spec: Wave 4 — Windows installer + first-run wizard

## Goal

Ship `xaxiu-harness` as something a non-technical operator can install on a Windows machine in under 5 minutes without authoring any Python or shell. After install, `harness <verb>` works from any directory and the autonomous dev loop is registered as a Windows scheduled task.

## Installer technology choice

**PowerShell-based installer** (no .msi, no Inno Setup, no PyInstaller bundle for v1).

Rationale:
- Operator already runs PowerShell elevated for the dev loop registration script ([bin/register-dev-loop-task.ps1](bin/register-dev-loop-task.ps1))
- No new toolchain dependency; no signing requirements (yet)
- Transparent — operator can read what the script does before running it
- Easy to extend later with a graphical wrapper (Wave 4.x or 5)

Trade-off accepted: distribution is "git clone then run script" rather than "double-click .msi". Suitable for v1.0; Wave 4.x can layer a signed .msi when there's a reason (broader distribution, code-signing for enterprise).

## Install flow (`bin/install-harness.ps1`)

1. **Pre-flight checks**:
   - Python 3.11+ on PATH; abort with friendly message if missing.
   - `git` on PATH (needed for `pip install -e .` from source).
   - Operator is in the project clone directory (script checks `pyproject.toml` exists in cwd).
2. **Create venv** at `$ProjectRoot\.venv` if not present; activate it.
3. **`pip install --upgrade pip` then `pip install -e ".[dev]"`** — editable install includes dev deps for ongoing dev loop ticks.
4. **Run smoke test**: `python -m pytest tests/ -q` — abort install if red.
5. **First-run wizard** (interactive PowerShell prompts):
   - Operator name + project name (used to init the default adapter).
   - For each engine (Kimi, DeepSeek, Anthropic): "Provide API key, leave blank to skip" → if provided, encrypt via DPAPI and store; show only "SET" thereafter.
   - "Enable autonomous dev loop? (Y/n)" → if Y, register Task Scheduler entry via [bin/register-dev-loop-task.ps1](bin/register-dev-loop-task.ps1).
   - "Operator mode for the loop? (review_each / full_dev_authority / dry_run)" → writes to default adapter's `operator` section (Wave 7 dependency).
6. **Initialize `state/` directory** with the restricted DACL (per `spec/ACCEPTED_LIMITATIONS.md::ACCEPT-1` resolution).
7. **Success summary** printed: where things live, how to run `harness env` to verify, how to uninstall.

## Uninstall flow (`bin/uninstall-harness.ps1`)

1. Confirm with operator (default No on destructive prompt).
2. Unregister Task Scheduler entry "XaxiuHarnessDevLoop".
3. `pip uninstall harness -y` (uninstalls the editable; leaves source tree).
4. **Preserve by default**: `state/` directory, `.venv/`, secrets. Add flags `--purge-secrets`, `--purge-state` for explicit destructive cleanup.
5. Print summary of what was removed and what was kept.

## First-run wizard implementation

Single PowerShell function `Invoke-FirstRunWizard` in `bin/install-harness.ps1`. Uses `Read-Host -AsSecureString` for API keys; converts to bytes; calls Python helper `python -m harness.secrets.dpapi set <env-name>` via stdin pipe (the helper reads stdin, encrypts, writes — never echoes value).

Each step has a "skip" option. The wizard is idempotent — re-running it offers to overwrite existing values with confirmation.

## Acceptance criteria

1. Fresh clone on a fresh Windows machine: `cd xaxiu-harness; .\bin\install-harness.ps1` completes in < 5 min, ending with `harness env` showing SET for any keys the operator entered.
2. `Get-ScheduledTask -TaskName XaxiuHarnessDevLoop` shows the task registered (if operator opted in).
3. `.\bin\uninstall-harness.ps1` removes the task and pip-uninstalls; `state/` preserved unless `--purge-state` passed.
4. Re-running `install-harness.ps1` is idempotent — does not error on second invocation.
5. New tests: `tests/test_install_smoke.py` mocks PowerShell calls and verifies the wizard's helper functions.

## Out of scope (Wave 4.x / later)

- Signed .msi installer
- Graphical wizard
- macOS/Linux installer (depends on cross-platform secrets backend — Wave 4.x)
- One-line `iwr install.xaxiu.cloud | iex` web installer (depends on hosting decision)
