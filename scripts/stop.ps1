[CmdletBinding()]
param()

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$stateFile = Join-Path $projectRoot '.runtime\services.json'
if (-not (Test-Path -LiteralPath $stateFile)) {
    Write-Host 'No services started by this project were recorded.'
    exit 0
}

$records = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
$failed = $false
foreach ($record in $records) {
    $serviceProcess = Get-Process -Id ([int]$record.pid) -ErrorAction SilentlyContinue
    if ($null -eq $serviceProcess) { continue }
    # Check identity before stopping a PID which Windows could have reused.
    if (($serviceProcess.Path -ne $record.executable) -or
        ($serviceProcess.StartTime.ToUniversalTime().Ticks.ToString() -ne [string]$record.startTimeUtcTicks)) {
        Write-Warning ('Skipped PID {0}: it no longer matches this project.' -f $record.pid)
        continue
    }
    & "$env:SystemRoot\System32\taskkill.exe" /PID ([string]$record.pid) /T /F | Out-Null
    if ($LASTEXITCODE -ne 0) {
        $failed = $true
        Write-Warning ('Could not stop {0} (PID {1}).' -f $record.name, $record.pid)
    } else {
        Write-Host ('Stopped {0}.' -f $record.name)
    }
}
if ($failed) { exit 1 }
Remove-Item -LiteralPath $stateFile -Force
Write-Host 'DeerFlow services are stopped.'
