# uninstall-harness.ps1
# Clean removal of xaxiu-harness installation artifacts (Wave 4).
#
# Preserves state/ and .venv/ by default.
#   --purge-secrets  : Also remove DPAPI secrets file
#   --purge-state    : Also remove the entire state/ directory

param(
    [switch]$PurgeSecrets,
    [switch]$PurgeState
)

$ErrorActionPreference = "Stop"

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Definition
. "$scriptDir\lib\wizard-helpers.ps1"

$ProjectRoot = (Get-Location).Path
$StatePath = Join-Path $ProjectRoot "state"
$VenvPath = Join-Path $ProjectRoot ".venv"
$TaskName = "XaxiuHarnessDevLoop"

# ---------------------------------------------------------------------------
# Confirmation
# ---------------------------------------------------------------------------

$purgeMsg = ""
if ($PurgeSecrets) { $purgeMsg += " (including secrets)" }
if ($PurgeState)   { $purgeMsg += " (including state dir)" }

Write-Output "This will uninstall the xaxiu-harness editable package and unregister the scheduled task.$purgeMsg"
if (-not (Read-HostYesNo -Prompt "Proceed with uninstall?" -Default N)) {
    Write-Output "Uninstall cancelled."
    exit 0
}

# ---------------------------------------------------------------------------
# Unregister scheduled task
# ---------------------------------------------------------------------------

$taskRemoved = $false
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    $taskRemoved = $true
    Write-Output "Unregistered scheduled task: $TaskName"
} else {
    Write-Output "Scheduled task not found: $TaskName"
}

# ---------------------------------------------------------------------------
# pip uninstall
# ---------------------------------------------------------------------------

$pipRemoved = $false
$pip = Join-Path $VenvPath "Scripts\pip.exe"
if (Test-Path $pip) {
    & $pip uninstall harness -y | Out-Null
    $pipRemoved = $true
    Write-Output "pip-uninstalled: harness"
} else {
    # Fallback: try global pip
    $globalPip = Get-Command pip -ErrorAction SilentlyContinue
    if ($globalPip) {
        & pip uninstall harness -y | Out-Null
        $pipRemoved = $true
        Write-Output "pip-uninstalled: harness (via global pip)"
    } else {
        Write-Warning "pip not found; skipping pip uninstall."
    }
}

# ---------------------------------------------------------------------------
# Optional destructive cleanup
# ---------------------------------------------------------------------------

$secretsRemoved = $false
$stateRemoved = $false

if ($PurgeSecrets) {
    $secretsFile = Join-Path $StatePath "secrets.dpapi"
    if (Test-Path $secretsFile) {
        Remove-Item $secretsFile -Force
        $secretsRemoved = $true
        Write-Output "Removed secrets file."
    }
}

if ($PurgeState) {
    if (Test-Path $StatePath) {
        Remove-Item $StatePath -Recurse -Force
        $stateRemoved = $true
        Write-Output "Removed state/ directory."
    }
}

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

Write-Output ""
Write-Output "========================================"
Write-Output "Uninstall summary"
Write-Output "========================================"
Write-Output "  Scheduled task removed:  $taskRemoved"
Write-Output "  Package uninstalled:     $pipRemoved"
Write-Output "  Secrets purged:          $secretsRemoved"
Write-Output "  State dir purged:        $stateRemoved"
Write-Output ""
Write-Output "Preserved (not removed):"
if (-not $stateRemoved)   { Write-Output "  - state/" }
if (-not $secretsRemoved) { Write-Output "  - state/secrets.dpapi" }
Write-Output "  - .venv/"
Write-Output "  - source tree"
Write-Output ""
