# Packet: Wave 4 — Windows installer + first-run wizard

## Mission

Implement `bin/install-harness.ps1` and `bin/uninstall-harness.ps1` per `spec/wave-4-installer.md`. PowerShell-based installer that takes a fresh clone of xaxiu-harness and makes it operator-ready in under 5 minutes.

## In-scope deliverables

NEW files:
- `bin/install-harness.ps1` (~150-250 LOC) — full install flow with wizard
- `bin/uninstall-harness.ps1` (~80-120 LOC) — clean removal
- `bin/lib/wizard-helpers.ps1` (~50-80 LOC) — shared PowerShell functions used by both
- `tests/test_install_smoke.py` (~100 LOC) — unit tests for the Python helpers the wizard calls

NEW Python helper (in existing module):
- Extend `src/harness/secrets/dpapi.py` with a `__main__` entrypoint so `python -m harness.secrets.dpapi set <name>` reads stdin, encrypts, stores. This is what the wizard pipes secrets into.

## Implementation guidance

### Pre-flight (install-harness.ps1)

```powershell
function Test-Prerequisites {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) { Write-Error "Python 3.11+ required."; exit 1 }
    # Check version >= 3.11
    $ver = [version](python --version 2>&1 -split " ")[1]
    if ($ver -lt [version]"3.11") { Write-Error "Python 3.11+ required (got $ver)"; exit 1 }

    if (-not (Test-Path pyproject.toml)) {
        Write-Error "Run from the xaxiu-harness project root."
        exit 1
    }
}
```

### Wizard

Use `Read-Host -AsSecureString` for API keys. Convert and pipe to Python helper via stdin:

```powershell
$secure = Read-Host "Kimi API key (leave blank to skip)" -AsSecureString
$bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
try {
    $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
} finally {
    [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
}
if ($plain) {
    $plain | python -m harness.secrets.dpapi set KIMI_API_KEY
}
```

### Python helper `python -m harness.secrets.dpapi set <NAME>`

Add to `src/harness/secrets/dpapi.py`:

```python
def _cli_set(name: str) -> None:
    import sys
    value = sys.stdin.read().rstrip("\n")
    if not value:
        sys.exit(2)  # blank input
    encrypt_secret(name, value)
    sys.stdout.write(f"{name}: SET\n")

if __name__ == "__main__":
    import sys
    if len(sys.argv) >= 3 and sys.argv[1] == "set":
        _cli_set(sys.argv[2])
        sys.exit(0)
    else:
        sys.stderr.write("Usage: python -m harness.secrets.dpapi set <NAME>\n")
        sys.exit(2)
```

NEVER print the value, even on error. Existing dpapi.py invariants must hold.

### Task Scheduler integration

Reuse `bin/register-dev-loop-task.ps1` (already in repo). Call it from the wizard:

```powershell
if (Read-HostYesNo "Enable autonomous dev loop scheduled task?" -Default Y) {
    & .\bin\register-dev-loop-task.ps1
}
```

### Operator-mode integration (Wave 7 dependency)

When Wave 7 lands, the wizard prompts:
```
Operator mode for the loop?
  1) review_each       (default — each commit/dispatch needs approval)
  2) full_dev_authority  (autonomous; only L5 errors escalate)
  3) dry_run           (no commits, no dispatches; surface plans only)
```
Selection writes to the adapter's `operator.mode`. If Wave 7 hasn't landed when this packet runs, skip this prompt — TODO comment to add later.

## Acceptance criteria

1. `pwsh -File bin/install-harness.ps1` on a clean clone:
   - Creates `.venv/`, installs editable, runs pytest
   - Prompts for at least one API key, encrypts via DPAPI, verifies `harness env` shows SET
   - Optionally registers scheduled task
   - Total elapsed < 5 minutes
2. `python -m harness.secrets.dpapi set KIMI_API_KEY` reads stdin and encrypts; round-trip with `python -c "from harness.secrets.dpapi import decrypt_secret; print(decrypt_secret('KIMI_API_KEY'))"` returns the original (DO NOT include this round-trip in committed tests — tests should never decrypt a real value to stdout).
3. `pwsh -File bin/uninstall-harness.ps1` unregisters scheduled task; `state/` preserved; pip-uninstalls.
4. Re-running install is idempotent.
5. `python -m pytest tests/ -q` shows ≥89 + new tests (≥100), all green.
6. Single commit: `feat(installer): Windows install + uninstall + first-run wizard (Wave 4)`.

## Reference

- `spec/wave-4-installer.md` — full spec
- `bin/register-dev-loop-task.ps1` — pattern reference for PowerShell + Task Scheduler
- `src/harness/secrets/dpapi.py` — existing DPAPI helpers (extend with `__main__`)
- `spec/ACCEPTED_LIMITATIONS.md::ACCEPT-1` — DACL on `state/` directory, resolved by this wave per the limitation's resolution path

## Output format

In-place additions to `src/harness/secrets/dpapi.py` (`__main__` block). New PowerShell scripts under `bin/`. New test file `tests/test_install_smoke.py`. Single commit.
