# wizard-helpers.ps1
# Shared PowerShell helpers for xaxiu-harness install/uninstall wizard.

$ErrorActionPreference = "Stop"

function Read-HostYesNo {
    <#
    .SYNOPSIS
        Prompt the operator with a yes/no question.
    .PARAMETER Prompt
        The question text.
    .PARAMETER Default
        Default choice: 'Y' or 'N'.
    #>
    param(
        [Parameter(Mandatory)]
        [string]$Prompt,

        [Parameter(Mandatory)]
        [ValidateSet('Y', 'N')]
        [string]$Default
    )

    $suffix = if ($Default -eq 'Y') { ' [Y/n]' } else { ' [y/N]' }
    $answer = Read-Host "$Prompt$suffix"
    if ([string]::IsNullOrWhiteSpace($answer)) {
        $answer = $Default
    }
    return ($answer -match '^[Yy]')
}


function Invoke-SecureSecretSet {
    <#
    .SYNOPSIS
        Prompt for a secret with Read-Host -AsSecureString, then pipe it into
        python -m harness.secrets.dpapi set <NAME>.
    .PARAMETER Name
        The secret identifier (e.g. KIMI_API_KEY).
    .PARAMETER Prompt
        The prompt text shown to the operator.
    #>
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [string]$Prompt
    )

    $secure = Read-Host $Prompt -AsSecureString
    $bstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $plain = [Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    } finally {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }

    if ($plain) {
        $plain | python -m harness.secrets.dpapi set $Name
        Write-Output "  $Name`: SET"
    } else {
        Write-Output "  $Name`: skipped"
    }
}


function Initialize-StateDirectoryAcl {
    <#
    .SYNOPSIS
        Create the state/ directory with a restricted DACL granting only the
        current user FullControl. Inherits to child files.
    #>
    param(
        [Parameter(Mandatory)]
        [string]$StatePath
    )

    if (-not (Test-Path $StatePath)) {
        New-Item -ItemType Directory -Path $StatePath -Force | Out-Null
    }

    $currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
    $acl = Get-Acl -Path $StatePath

    # Remove inherited rules and enable protection so only explicit ACEs apply
    $acl.SetAccessRuleProtection($true, $false)

    # Grant current user FullControl
    $userRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $currentUser,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit,
        [System.Security.AccessControl.PropagationFlags]::None,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    $acl.AddAccessRule($userRule)

    # Add SYSTEM read for backup/indexers (optional, read-only)
    $systemRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        "NT AUTHORITY\SYSTEM",
        [System.Security.AccessControl.FileSystemRights]::ReadAndExecute,
        [System.Security.AccessControl.InheritanceFlags]::ContainerInherit -bor [System.Security.AccessControl.InheritanceFlags]::ObjectInherit,
        [System.Security.AccessControl.PropagationFlags]::None,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    $acl.AddAccessRule($systemRule)

    Set-Acl -Path $StatePath -AclObject $acl
}
