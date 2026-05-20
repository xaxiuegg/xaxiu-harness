# register-dev-loop-task.ps1
# ONE-SHOT setup. Run this once (as the operator, NOT elevated) to install the
# xaxiu-harness dev loop into Windows Task Scheduler.
#
# Cadence: every 30 minutes.
# Behavior: invokes bin/dev-loop-tick.ps1 which runs one Claude --print tick.
# Lock: dev-loop-tick.ps1 self-skips if a prior tick is still running.
# To pause: schtasks /Change /TN "XaxiuHarnessDevLoop" /DISABLE
# To remove: Unregister-ScheduledTask -TaskName "XaxiuHarnessDevLoop" -Confirm:$false

$ErrorActionPreference = "Stop"

$TaskName = "XaxiuHarnessDevLoop"
$ScriptPath = "D:\Projects\xaxiu-harness\bin\dev-loop-tick.ps1"

if (-not (Test-Path $ScriptPath)) {
    Write-Error "Cannot find $ScriptPath. Run this from a checkout of xaxiu-harness."
    exit 1
}

# Action: invoke PowerShell with -File pointing at the tick script
$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-ExecutionPolicy Bypass -NoProfile -WindowStyle Hidden -File `"$ScriptPath`""

# Trigger: every 30 minutes, starting now, indefinitely
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Minutes 30) `
    -RepetitionDuration ([System.TimeSpan]::MaxValue)

# Principal: current user (NOT SYSTEM — Claude auth keychain is per-user)
# Run whether logged on or not, but don't store password (S4U logon type)
$Principal = New-ScheduledTaskPrincipal `
    -UserId "$env:USERDOMAIN\$env:USERNAME" `
    -LogonType S4U `
    -RunLevel Limited

# Settings: allow running on battery, wake to run, don't stop if running long
$Settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -WakeToRun `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15) `
    -RestartCount 0 `
    -MultipleInstances IgnoreNew

# Remove if exists (idempotent)
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Output "Existing task found; unregistering..."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $Action `
    -Trigger $Trigger `
    -Principal $Principal `
    -Settings $Settings `
    -Description "xaxiu-harness autonomous dev loop tick (every 30 min)" | Out-Null

Write-Output ""
Write-Output "Task registered: $TaskName"
Write-Output "  Cadence:      every 30 min, starting $(Get-Date -Format 'HH:mm:ss')"
Write-Output "  Wake-to-run:  enabled"
Write-Output "  Run as:       $env:USERDOMAIN\$env:USERNAME"
Write-Output ""
Write-Output "To pause:   schtasks /Change /TN `"$TaskName`" /DISABLE"
Write-Output "To resume:  schtasks /Change /TN `"$TaskName`" /ENABLE"
Write-Output "To remove:  Unregister-ScheduledTask -TaskName `"$TaskName`" -Confirm:`$false"
Write-Output ""
Write-Output "First tick fires within 30 min. Monitor coord/dev_loop/log.jsonl and coord/dev_loop/escalations.md."
