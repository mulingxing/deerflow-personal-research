[CmdletBinding()]
param([switch]$OpenBrowser)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $projectRoot
$runtimeDir = Join-Path $projectRoot '.runtime'
$stateFile = Join-Path $runtimeDir 'services.json'
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$nodeExe = Join-Path $projectRoot '.tools\node\node.exe'
$pnpmScript = Join-Path $projectRoot '.tools\pnpm\node_modules\pnpm\bin\pnpm.cjs'
$webDir = Join-Path $projectRoot 'web'
$started = @()

function Test-RecordedProcess($record) {
    $serviceProcess = Get-Process -Id ([int]$record.pid) -ErrorAction SilentlyContinue
    return ($null -ne $serviceProcess -and
        $serviceProcess.Path -eq $record.executable -and
        $serviceProcess.StartTime.ToUniversalTime().Ticks.ToString() -eq [string]$record.startTimeUtcTicks)
}

function Test-PortInUse([int]$port) {
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $pending = $client.ConnectAsync('127.0.0.1', $port)
        if ($pending.Wait(500)) { return $client.Connected }
        return $false
    } catch { return $false } finally { $client.Dispose() }
}

function Wait-Http([string]$url, [int]$seconds) {
    $deadline = [DateTime]::UtcNow.AddSeconds($seconds)
    while ([DateTime]::UtcNow -lt $deadline) {
        foreach ($record in $script:started) {
            if (-not (Test-RecordedProcess $record)) {
                throw ('{0} exited. See logs in {1}' -f $record.name, $runtimeDir)
            }
        }
        try {
            $result = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 5
            if ($result.StatusCode -eq 200) { return }
        } catch { }
        Start-Sleep -Milliseconds 500
    }
    throw ('Timed out waiting for {0}. See logs in {1}' -f $url, $runtimeDir)
}

function Save-Service($serviceProcess, [string]$name, [string]$executable) {
    $serviceProcess.Refresh()
    $record = [pscustomobject]@{
        name = $name
        pid = $serviceProcess.Id
        executable = $executable
        startTimeUtcTicks = $serviceProcess.StartTime.ToUniversalTime().Ticks.ToString()
    }
    $script:started += $record
    ConvertTo-Json -InputObject @($script:started) | Set-Content -LiteralPath $stateFile -Encoding UTF8
}

try {
    foreach ($requiredPath in @($pythonExe, $nodeExe, $pnpmScript, (Join-Path $webDir 'node_modules\next\package.json'))) {
        if (-not (Test-Path -LiteralPath $requiredPath)) { throw ('Missing dependency: ' + $requiredPath) }
    }
    if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.local.example' -Destination '.env' }
    if (-not (Test-Path -LiteralPath 'conf.yaml')) { Copy-Item -LiteralPath 'conf.deepseek.yaml.example' -Destination 'conf.yaml' }
    New-Item -ItemType Directory -Path $runtimeDir -Force | Out-Null

    if (Test-Path -LiteralPath $stateFile) {
        $records = Get-Content -LiteralPath $stateFile -Raw | ConvertFrom-Json
        $matching = @($records | Where-Object { Test-RecordedProcess $_ })
        if ($records.Count -eq 2 -and $matching.Count -eq 2 -and
            (Test-PortInUse 8000) -and (Test-PortInUse 3000)) {
            Write-Host 'DeerFlow is already running: http://127.0.0.1:3000'
            if ($OpenBrowser) { Start-Process 'http://127.0.0.1:3000' }
            exit 0
        }
        & (Join-Path $PSScriptRoot 'stop.ps1')
    }
    foreach ($port in @(8000, 3000)) {
        if (Test-PortInUse $port) { throw ('Port {0} is already used by another process. No process was stopped.' -f $port) }
    }

    $env:PATH = "$(Join-Path $projectRoot '.venv\Scripts');$(Join-Path $projectRoot '.tools\node');$(Join-Path $projectRoot '.tools\uv');$env:PATH"
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    $env:UV_CACHE_DIR = Join-Path $projectRoot '.cache\uv'
    $env:UV_PYTHON_INSTALL_DIR = Join-Path $projectRoot '.tools\python'
    $env:UV_PYTHON_BIN_DIR = Join-Path $projectRoot '.tools\bin'
    $env:npm_config_cache = Join-Path $projectRoot '.cache\npm'
    $env:NEXT_TELEMETRY_DISABLED = '1'

    Write-Host 'Starting API on http://127.0.0.1:8000 ...'
    $backend = Start-Process -FilePath $pythonExe -ArgumentList @('-u', 'scripts/run_backend.py', '--host', '127.0.0.1', '--port', '8000') -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'backend.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'backend.stderr.log') -PassThru
    Save-Service $backend 'backend' $pythonExe
    Wait-Http 'http://127.0.0.1:8000/api/config' 60

    Write-Host 'Starting web UI on http://127.0.0.1:3000 ...'
    $frontendArgs = @(('"{0}"' -f $pnpmScript), '--dir', ('"{0}"' -f $webDir), 'dev', '--hostname', '127.0.0.1', '--port', '3000')
    $frontend = Start-Process -FilePath $nodeExe -ArgumentList $frontendArgs -WorkingDirectory $projectRoot -WindowStyle Hidden -RedirectStandardOutput (Join-Path $runtimeDir 'frontend.stdout.log') -RedirectStandardError (Join-Path $runtimeDir 'frontend.stderr.log') -PassThru
    Save-Service $frontend 'frontend' $nodeExe
    Wait-Http 'http://127.0.0.1:3000' 180

    Write-Host ''
    Write-Host 'Web UI:   http://127.0.0.1:3000'
    Write-Host 'API docs: http://127.0.0.1:8000/docs'
    Write-Host 'Fill DEEPSEEK_API_KEY and TAVILY_API_KEY in .env before running web research.'
    Write-Host 'After changing .env or conf.yaml: run stop.cmd, then start.cmd.'
    Write-Host 'Run verify.cmd to check local services without calling the model API.'
    if ($OpenBrowser) { Start-Process 'http://127.0.0.1:3000' }
} catch {
    Write-Host ('Startup failed: ' + $_.Exception.Message) -ForegroundColor Red
    if ($started.Count -gt 0 -and (Test-Path -LiteralPath $stateFile)) {
        & (Join-Path $PSScriptRoot 'stop.ps1')
    }
    exit 1
}
