[CmdletBinding()]
param(
    [string]$BaseUrl = "",
    [int]$ApiPort = 0,
    [int]$WebPort = 0
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$session = "sap-flow-smoke-$([Guid]::NewGuid().ToString('N'))"
$codeFile = Join-Path $PSScriptRoot "browser_smoke.js"
$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$runtimeDir = [IO.Path]::GetFullPath((Join-Path $workspaceRoot "output\browser-smoke"))
$apiProcess = $null
$webProcess = $null
$managedServers = [string]::IsNullOrWhiteSpace($BaseUrl)

function Get-FreeTcpPort {
    $listener = [Net.Sockets.TcpListener]::new([Net.IPAddress]::Loopback, 0)
    try {
        $listener.Start()
        return ([Net.IPEndPoint]$listener.LocalEndpoint).Port
    }
    finally {
        $listener.Stop()
    }
}

function Wait-HttpReady {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Url,
        [int]$TimeoutSeconds = 45
    )

    $deadline = [DateTime]::UtcNow.AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 3
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 500) {
                return
            }
        }
        catch {
            Start-Sleep -Milliseconds 300
        }
    } while ([DateTime]::UtcNow -lt $deadline)

    throw "Timed out waiting for $Url"
}

function Invoke-Playwright {
    param(
        [Parameter(Mandatory = $true)]
        [string[]]$Arguments
    )

    $output = & npx.cmd --yes --package @playwright/cli playwright-cli --session $session @Arguments 2>&1
    if ($LASTEXITCODE -ne 0) {
        Write-Host ($output -join "`n")
        throw "Playwright command failed: $($Arguments -join ' ')"
    }
    return $output
}

function Restore-EnvironmentValue {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Name,
        [AllowNull()]
        [string]$Value
    )

    if ($null -eq $Value) {
        Remove-Item -LiteralPath "Env:$Name" -ErrorAction SilentlyContinue
    }
    else {
        Set-Item -LiteralPath "Env:$Name" -Value $Value
    }
}

try {
    if ($managedServers) {
        if (-not $runtimeDir.StartsWith($workspaceRoot, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Browser smoke runtime path escaped the workspace: $runtimeDir"
        }
        New-Item -ItemType Directory -Force -Path $runtimeDir | Out-Null
        foreach ($name in @("sap_blueprint.db", "sap_blueprint.db-shm", "sap_blueprint.db-wal")) {
            $target = [IO.Path]::GetFullPath((Join-Path $runtimeDir $name))
            if (-not $target.StartsWith($runtimeDir, [StringComparison]::OrdinalIgnoreCase)) {
                throw "Refusing to remove unexpected browser smoke path: $target"
            }
            Remove-Item -LiteralPath $target -Force -ErrorAction SilentlyContinue
        }

        if ($ApiPort -eq 0) { $ApiPort = Get-FreeTcpPort }
        if ($WebPort -eq 0) { $WebPort = Get-FreeTcpPort }
        if ($ApiPort -eq $WebPort) { $WebPort = Get-FreeTcpPort }

        $apiUrl = "http://127.0.0.1:$ApiPort"
        $BaseUrl = "http://127.0.0.1:$WebPort"
        $databasePath = (Join-Path $runtimeDir "sap_blueprint.db").Replace('\', '/')
        $python = Join-Path $workspaceRoot ".venv\Scripts\python.exe"
        $node = (Get-Command node.exe).Source
        $vite = Join-Path $workspaceRoot "node_modules\vite\bin\vite.js"
        foreach ($required in @($python, $node, $vite)) {
            if (-not (Test-Path -LiteralPath $required)) {
                throw "Required browser smoke runtime is missing: $required"
            }
        }

        $previousDatabaseUrl = [Environment]::GetEnvironmentVariable("DATABASE_URL")
        $previousCorsOrigins = [Environment]::GetEnvironmentVariable("CORS_ORIGINS")
        $previousApiUrl = [Environment]::GetEnvironmentVariable("VITE_API_URL")
        $previousApiTimeout = [Environment]::GetEnvironmentVariable("VITE_API_TIMEOUT_MS")
        $previousExportTimeout = [Environment]::GetEnvironmentVariable("VITE_EXPORT_TIMEOUT_MS")
        try {
            $env:DATABASE_URL = "sqlite:///$databasePath"
            $env:CORS_ORIGINS = $BaseUrl
            $env:VITE_API_URL = $apiUrl
            $env:VITE_API_TIMEOUT_MS = "2000"
            $env:VITE_EXPORT_TIMEOUT_MS = "44000"
            $apiProcess = Start-Process -FilePath $python `
                -ArgumentList @("-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$ApiPort") `
                -WorkingDirectory (Join-Path $workspaceRoot "apps\api") `
                -RedirectStandardOutput (Join-Path $runtimeDir "api.stdout.log") `
                -RedirectStandardError (Join-Path $runtimeDir "api.stderr.log") `
                -WindowStyle Hidden `
                -PassThru
            $webProcess = Start-Process -FilePath $node `
                -ArgumentList @("`"$vite`"", "--host", "127.0.0.1", "--port", "$WebPort", "--strictPort") `
                -WorkingDirectory (Join-Path $workspaceRoot "apps\web") `
                -RedirectStandardOutput (Join-Path $runtimeDir "web.stdout.log") `
                -RedirectStandardError (Join-Path $runtimeDir "web.stderr.log") `
                -WindowStyle Hidden `
                -PassThru
        }
        finally {
            Restore-EnvironmentValue -Name "DATABASE_URL" -Value $previousDatabaseUrl
            Restore-EnvironmentValue -Name "CORS_ORIGINS" -Value $previousCorsOrigins
            Restore-EnvironmentValue -Name "VITE_API_URL" -Value $previousApiUrl
            Restore-EnvironmentValue -Name "VITE_API_TIMEOUT_MS" -Value $previousApiTimeout
            Restore-EnvironmentValue -Name "VITE_EXPORT_TIMEOUT_MS" -Value $previousExportTimeout
        }

        Wait-HttpReady -Url "$apiUrl/health/ready"
        Wait-HttpReady -Url $BaseUrl
    }

    $browserUrl = if ($managedServers) { "$BaseUrl/?browserSmokeManaged=1" } else { $BaseUrl }
    Invoke-Playwright @("open", $browserUrl) | Out-Null
    Invoke-Playwright @("run-code", "--filename", $codeFile) | Out-Null
    Write-Host "Browser smoke passed: local undo/redo/layout/recovery, node/edge/lane editing, edge inspector/viewer restrictions, members and visible access audits, model policy, cancel/timeout/conflict recovery, local P95 budget, persisted release lifecycle, asynchronous blueprint jobs/downloads, responsive widths, and browser errors."
}
finally {
    try { Invoke-Playwright @("close") | Out-Null } catch { }
    foreach ($process in @($webProcess, $apiProcess)) {
        if ($null -ne $process -and -not $process.HasExited) {
            Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
            $process.WaitForExit(5000) | Out-Null
        }
    }
}
