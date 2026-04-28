param(
    [int]$IntervalMinutes = 30,
    [int]$MmLimit = 200,
    [string]$ProjectRoot = "F:\projects\tools\working\malody_tools\malody_api"
)

$ErrorActionPreference = "Continue"

if ($IntervalMinutes -lt 5) {
    $IntervalMinutes = 5
}

Set-Location $ProjectRoot
New-Item -ItemType Directory -Path ".\logs" -Force | Out-Null

while ($true) {
    $timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    Add-Content -Path ".\logs\mm_scheduler.log" -Value "[$timestamp] MM scheduler tick."
    try {
        python .\malody_rankings.py --mm-only --mm-limit $MmLimit *> ".\logs\mm_scheduler_last_run.log"
    } catch {
        $errTs = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
        Add-Content -Path ".\logs\mm_scheduler.log" -Value "[$errTs] MM run failed: $($_.Exception.Message)"
    }
    Start-Sleep -Seconds ($IntervalMinutes * 60)
}
