# dev-loop-tick.ps1
# Windows Task Scheduler invokes this every 30 minutes.
# Each invocation is one autonomous tick of the xaxiu-harness dev loop.
# Stateless from Claude's perspective; all state lives in coord/dev_loop/state.json.

param(
    [string]$ProjectRoot = "D:\Projects\xaxiu-harness",
    [string]$ManagerPrompt = "D:\Projects\xaxiu-harness\coord\dev_loop\manager.md",
    [int]$TimeoutSeconds = 900  # 15 minutes max per tick
)

$ErrorActionPreference = "Stop"
$tickStart = Get-Date

# Lock file prevents overlapping ticks if Task Scheduler fires while previous still running
$LockFile = Join-Path $ProjectRoot "coord\dev_loop\.tick.lock"
if (Test-Path $LockFile) {
    $lockAge = (Get-Date) - (Get-Item $LockFile).LastWriteTime
    if ($lockAge.TotalMinutes -lt 30) {
        Write-Output "[$($tickStart.ToString('o'))] tick skipped: previous tick still running (lock age $($lockAge.TotalMinutes.ToString('0.0')) min)"
        exit 0
    } else {
        # Stale lock; remove and proceed
        Remove-Item $LockFile -Force
    }
}
New-Item -ItemType File -Path $LockFile -Force | Out-Null

try {
    Set-Location $ProjectRoot

    # Pre-flight: check loop_status and phase escalations to short-circuit if globally paused
    $statePath = Join-Path $ProjectRoot "coord\dev_loop\state.json"
    if (-not (Test-Path $statePath)) {
        Write-Output "[$($tickStart.ToString('o'))] tick aborted: state.json missing at $statePath"
        exit 1
    }
    $state = Get-Content $statePath -Raw | ConvertFrom-Json
    if ($state.loop_status -eq "operator_paused") {
        Write-Output "[$($tickStart.ToString('o'))] tick skipped: loop_status=operator_paused"
        exit 0
    }
    if ($state.loop_status -eq "exhausted_plan") {
        Write-Output "[$($tickStart.ToString('o'))] tick skipped: loop_status=exhausted_plan (all waves done)"
        exit 0
    }

    # Invoke Claude in --print mode with the dev manager prompt
    $logFile = Join-Path $ProjectRoot "coord\dev_loop\log.jsonl"
    $tickLog = Join-Path $ProjectRoot "coord\dev_loop\last-tick.log"

    Write-Output "[$($tickStart.ToString('o'))] tick start"
    $claudeArgs = @(
        "--print",
        "--add-dir", $ProjectRoot,
        "--append-system-prompt-file", $ManagerPrompt,
        "execute one dev-loop tick now"
    )
    $proc = Start-Process -FilePath "claude" -ArgumentList $claudeArgs `
        -NoNewWindow -PassThru -RedirectStandardOutput $tickLog -RedirectStandardError "$tickLog.err"
    $finished = $proc.WaitForExit($TimeoutSeconds * 1000)
    if (-not $finished) {
        $proc.Kill()
        Write-Output "[$($tickStart.ToString('o'))] tick KILLED after ${TimeoutSeconds}s timeout"
        # Append timeout to log.jsonl
        $entry = @{
            timestamp = (Get-Date).ToString("o")
            tick_count = ($state.tick_count + 1)
            phase_acted_on = $null
            outcome = "timeout"
            summary = "tick exceeded ${TimeoutSeconds}s timeout and was killed"
        } | ConvertTo-Json -Compress
        Add-Content -Path $logFile -Value $entry -Encoding utf8
        exit 1
    }
    $exit = $proc.ExitCode
    Write-Output "[$($tickStart.ToString('o'))] tick completed exit=$exit duration=$((Get-Date) - $tickStart)"
    exit $exit
}
finally {
    if (Test-Path $LockFile) {
        Remove-Item $LockFile -Force
    }
}
