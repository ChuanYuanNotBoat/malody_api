param(
    [string]$TaskName = "MalodyMMCrawler",
    [int]$IntervalMinutes = 30,
    [int]$MmLimit = 200,
    [string]$ProjectRoot = "F:\projects\tools\working\malody_tools\malody_api",
    [switch]$Remove
)

$ErrorActionPreference = "Stop"

$scriptPath = Join-Path $ProjectRoot "scripts\mm_autorun.ps1"

if ($Remove) {
    $removed = $false
    foreach ($name in @($TaskName, "${TaskName}_User")) {
        if (Get-ScheduledTask -TaskName $name -ErrorAction SilentlyContinue) {
            try {
                Unregister-ScheduledTask -TaskName $name -Confirm:$false -ErrorAction Stop
                Write-Host "Removed task: $name"
                $removed = $true
            } catch {
                Write-Warning "Failed to remove task '$name': $($_.Exception.Message)"
            }
        }
    }
    if (-not $removed) {
        Write-Host "Task not found: $TaskName / ${TaskName}_User"
    }
    return
}

if (-not (Test-Path $scriptPath)) {
    throw "Scheduler script not found: $scriptPath"
}

$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -IntervalMinutes $IntervalMinutes -MmLimit $MmLimit -ProjectRoot `"$ProjectRoot`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable

function Remove-TaskIfExists {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name
    )
    if (Get-ScheduledTask -TaskName $Name -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $Name -Confirm:$false -ErrorAction Stop
    }
}

try {
    # Preferred path: machine startup task (requires elevated privileges).
    Remove-TaskIfExists -Name $TaskName
    $startupTrigger = New-ScheduledTaskTrigger -AtStartup
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $startupTrigger -Settings $settings -RunLevel Highest -ErrorAction Stop | Out-Null
    Write-Host "Installed startup task: $TaskName"
    return
} catch {
    Write-Warning "Failed to install startup task '$TaskName': $($_.Exception.Message)"
    Write-Warning "Falling back to current-user logon task without elevation."
}

$fallbackTaskName = "${TaskName}_User"
try {
    Remove-TaskIfExists -Name $fallbackTaskName
    $logonTrigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
    Register-ScheduledTask -TaskName $fallbackTaskName -Action $action -Trigger $logonTrigger -Settings $settings -RunLevel Limited -ErrorAction Stop | Out-Null
    Write-Host "Installed user logon task: $fallbackTaskName"
} catch {
    throw "Failed to install fallback user task '$fallbackTaskName': $($_.Exception.Message)"
}
