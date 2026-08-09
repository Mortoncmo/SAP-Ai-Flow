[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:5173"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$session = "sap-flow-smoke-$([Guid]::NewGuid().ToString('N'))"
$codeFile = Join-Path $PSScriptRoot "browser_smoke.js"

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

try {
    Invoke-Playwright @("open", $BaseUrl) | Out-Null
    Invoke-Playwright @("run-code", "--filename", $codeFile) | Out-Null
    Write-Host "Browser smoke passed: lane operations, node preservation, mobile width, and console errors."
}
finally {
    try { Invoke-Playwright @("close") | Out-Null } catch { }
}
