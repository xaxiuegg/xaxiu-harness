# install-harness.ps1
# xaxiu-harness Windows installer + first-run wizard (Wave 4)
#
# Run from the project root (where pyproject.toml lives).
#   pwsh -File bin\install-harness.ps1

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
. "$scriptDir\lib\wizard-helpers.ps1"

$ProjectRoot = (Get-Location).Path
$VenvPath = Join-Path $ProjectRoot ".venv"
$StatePath = Join-Path $ProjectRoot "state"

# ---------------------------------------------------------------------------
# Pre-flight
# ---------------------------------------------------------------------------

function Test-Prerequisites {
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        Write-Error "Python 3.11+ is required but not found on PATH."
        exit 1
    }
    $verStr = (& python --version 2>&1) -replace "Python "
    $ver = [version]$verStr
    if ($ver -lt [version]"3.11") {
        Write-Error "Python 3.11+ required (got $ver)."
        exit 1
    }

    $git = Get-Command git -ErrorAction SilentlyContinue
    if (-not $git) {
        Write-Error "git is required but not found on PATH."
        exit 1
    }

    if (-not (Test-Path (Join-Path $ProjectRoot "pyproject.toml"))) {
        Write-Error "Run this script from the xaxiu-harness project root (where pyproject.toml lives)."
        exit 1
    }
}

# ---------------------------------------------------------------------------
# Venv + editable install
# ---------------------------------------------------------------------------

function Install-Editable {
    if (-not (Test-Path $VenvPath)) {
        Write-Output "Creating virtual environment at .venv ..."
        python -m venv "$VenvPath"
    }

    $pip = Join-Path $VenvPath "Scripts\pip.exe"
    & $pip install --upgrade pip | Out-Null
    Write-Output "Installing xaxiu-harness in editable mode with dev dependencies ..."
    & $pip install -e ".[dev]" | Out-Null
}

# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

function Invoke-SmokeTest {
    $pytest = Join-Path $VenvPath "Scripts\pytest.exe"
    Write-Output "Running test suite ..."
    & $pytest tests\ -q
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Tests failed. Fix failures before proceeding."
        exit 1
    }
}

# ---------------------------------------------------------------------------
# First-run wizard
# ---------------------------------------------------------------------------

function Invoke-FirstRunWizard {
    Write-Output ""
    Write-Output "=== xaxiu-harness First-Run Wizard ==="
    Write-Output ""

    $operatorName = Read-Host "Operator name (your name)"
    $projectName = Read-Host "Default project name (e.g., my-project)"

    if ($operatorName -and $projectName) {
        $adapterDir = Join-Path $ProjectRoot "adapters" $projectName
        $adapterFile = Join-Path $adapterDir "harness-adapter.yaml"
        if (-not (Test-Path $adapterFile)) {
            $harnessExe = Join-Path $VenvPath "Scripts\harness.exe"
            & $harnessExe init -p $projectName -t generic-coding | Out-Null
            Write-Output "Created default adapter: adapters/$projectName/harness-adapter.yaml"
        } else {
            Write-Output "Adapter already exists for '$projectName'; skipping init."
        }
    }

    Write-Output ""
    Write-Output "--- API Keys (leave blank to skip) ---"
    Invoke-SecureSecretSet -Name "KIMI_API_KEY"      -Prompt "Kimi API key"
    Invoke-SecureSecretSet -Name "DEEPSEEK_API_KEY"  -Prompt "DeepSeek API key"
    Invoke-SecureSecretSet -Name "ANTHROPIC_API_KEY" -Prompt "Anthropic API key"

    Write-Output ""
    if (Read-HostYesNo -Prompt "Enable autonomous dev loop scheduled task?" -Default Y) {
        $regScript = Join-Path $ProjectRoot "bin\register-dev-loop-task.ps1"
        if (Test-Path $regScript) {
            & $regScript
        } else {
            Write-Warning "register-dev-loop-task.ps1 not found; skipping task registration."
        }
    }

    # Wave 7 operator-mode integration (skip if adapter schema lacks operator section)
    Write-Output ""
    # TODO: Add operator-mode prompt when Wave 7 lands (review_each / full_dev_authority / dry_run)
}

# ---------------------------------------------------------------------------
# State directory with restricted DACL
# ---------------------------------------------------------------------------

function Initialize-StateDirectory {
    Write-Output "Initializing state/ directory with restricted permissions ..."
    Initialize-StateDirectoryAcl -StatePath $StatePath
    Write-Output "  state/ ready."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

Test-Prerequisites
Install-Editable
Invoke-SmokeTest
Invoke-FirstRunWizard
Initialize-StateDirectory

Write-Output ""
Write-Output "========================================"
Write-Output "xaxiu-harness installation complete."
Write-Output "========================================"
Write-Output "  Virtual env:  $VenvPath"
Write-Output "  State dir:    $StatePath"
Write-Output "  Adapter dir:  $(Join-Path $ProjectRoot "adapters")"
Write-Output ""
Write-Output "Verify secrets:   harness env"
Write-Output "Run dispatch:     harness dispatch -p <project> --packet <path>"
Write-Output "Uninstall:        .\bin\uninstall-harness.ps1"
Write-Output ""
