param(
    [string]$TaskName = "MalodyMMCrawler",
    [int]$IntervalMinutes = 30,
    [int]$MmLimit = 200,
    [string]$ProjectRoot = "F:\projects\tools\working\malody_tools\malody_api",
    [switch]$Remove
)

$scriptPath = Join-Path $ProjectRoot "scripts\mm_autorun.ps1"

if ($Remove) {
    if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed task: $TaskName"
    } else {
        Write-Host "Task not found: $TaskName"
    }
    return
}

if (-not (Test-Path $scriptPath)) {
    throw "Scheduler script not found: $scriptPath"
}

$arg = "-NoProfile -ExecutionPolicy Bypass -File `"$scriptPath`" -IntervalMinutes $IntervalMinutes -MmLimit $MmLimit -ProjectRoot `"$ProjectRoot`""
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg
$trigger = New-ScheduledTaskTrigger -AtStartup
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -StartWhenAvailable

if (Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest | Out-Null
Write-Host "Installed startup task: $TaskName"
