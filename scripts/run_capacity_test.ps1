[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$UserId = "local-user",
    [string]$AccessToken = "",
    [int[]]$ConcurrencyLevels = @(1, 2, 4, 8),
    [ValidateRange(1, 200)]
    [int]$SamplesPerLevel = 20,
    [ValidateRange(1, 120)]
    [int]$RequestTimeoutSeconds = 45,
    [ValidateRange(1, 120000)]
    [int]$MaxP95Ms = 8000,
    [ValidateRange(1, 120000)]
    [int]$MaxP99Ms = 15000,
    [ValidateRange(0, 100)]
    [double]$MaxErrorRatePercent = 1,
    [string]$Instruction = "",
    [string]$OutputDirectory = "",
    [switch]$AllowDataCreation,
    [switch]$EnableExternalModel,
    [switch]$RequireExternalProvider,
    [switch]$RequirePostgreSQL
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http

if ([string]::IsNullOrWhiteSpace($Instruction)) {
    $Instruction = [Text.Encoding]::UTF8.GetString(
        [Convert]::FromBase64String(
            "5Yib5bu6IFNBUCBNTSBQMlAg6YeH6LSt5Yiw5LuY5qy+5rWB56iL"
        )
    )
}

if (-not $AllowDataCreation) {
    throw "Capacity testing creates a project and one process per sample. Re-run with -AllowDataCreation after confirming the target."
}
if ($RequireExternalProvider -and -not $EnableExternalModel) {
    throw "-RequireExternalProvider requires -EnableExternalModel."
}
if ($ConcurrencyLevels.Count -eq 0) {
    throw "At least one concurrency level is required."
}
$levels = @($ConcurrencyLevels | Sort-Object -Unique)
foreach ($level in $levels) {
    if ($level -lt 1 -or $level -gt 64) {
        throw "Concurrency levels must be between 1 and 64: $level"
    }
}

$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$outputPath = if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    Join-Path $workspaceRoot "output\capacity-test"
}
else {
    [IO.Path]::GetFullPath($OutputDirectory)
}
$apiRoot = $BaseUrl.TrimEnd("/")
$targetUri = [Uri]$apiRoot
if (
    -not $targetUri.IsAbsoluteUri -or
    $targetUri.Scheme -notin @("http", "https") -or
    -not [string]::IsNullOrWhiteSpace($targetUri.UserInfo) -or
    -not [string]::IsNullOrWhiteSpace($targetUri.Query) -or
    -not [string]::IsNullOrWhiteSpace($targetUri.Fragment)
) {
    throw "BaseUrl must be an absolute HTTP(S) URL without credentials, query, or fragment."
}
$effectiveAccessToken = if (-not [string]::IsNullOrWhiteSpace($AccessToken)) {
    $AccessToken
}
else {
    [Environment]::GetEnvironmentVariable("SAP_FLOW_ACCESS_TOKEN")
}
if ([string]::IsNullOrWhiteSpace($effectiveAccessToken) -and -not $targetUri.IsLoopback) {
    throw "A Bearer token is required for non-loopback targets. Set SAP_FLOW_ACCESS_TOKEN or pass -AccessToken."
}

New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$client = [Net.Http.HttpClient]::new()
$client.Timeout = [TimeSpan]::FromSeconds($RequestTimeoutSeconds)
if ([string]::IsNullOrWhiteSpace($effectiveAccessToken)) {
    $client.DefaultRequestHeaders.Add("X-User-ID", $UserId)
}
else {
    $client.DefaultRequestHeaders.Authorization =
        [Net.Http.Headers.AuthenticationHeaderValue]::new("Bearer", $effectiveAccessToken)
}

function New-JsonRequest {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Method,
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [AllowNull()]
        [object]$Body = $null
    )

    $request = [Net.Http.HttpRequestMessage]::new(
        [Net.Http.HttpMethod]::new($Method),
        "$apiRoot$Path"
    )
    if ($null -ne $Body) {
        $json = $Body | ConvertTo-Json -Depth 100 -Compress
        $content = [Net.Http.ByteArrayContent]::new(
            [Text.Encoding]::UTF8.GetBytes($json)
        )
        $content.Headers.ContentType =
            [Net.Http.Headers.MediaTypeHeaderValue]::new("application/json")
        $content.Headers.ContentType.CharSet = "utf-8"
        $request.Content = $content
    }
    return $request
}

function Invoke-CapacityApi {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Method,
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [AllowNull()]
        [object]$Body = $null
    )

    $request = New-JsonRequest -Method $Method -Path $Path -Body $Body
    $response = $null
    try {
        $response = $client.SendAsync($request).GetAwaiter().GetResult()
        $responseText = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
        $responseData = if ([string]::IsNullOrWhiteSpace($responseText)) {
            $null
        }
        else {
            $responseText | ConvertFrom-Json
        }
        if (-not $response.IsSuccessStatusCode) {
            $errorObject = if ($null -ne $responseData) {
                $property = $responseData.PSObject.Properties["error"]
                if ($null -ne $property) { $property.Value } else { $null }
            }
            else {
                $null
            }
            $errorCode = if (
                $null -ne $errorObject -and
                -not [string]::IsNullOrWhiteSpace([string]$errorObject.code)
            ) {
                [string]$errorObject.code
            }
            else {
                "HTTP_$([int]$response.StatusCode)"
            }
            throw "$Method $Path failed with status $([int]$response.StatusCode) and code $errorCode."
        }
        return $responseData
    }
    finally {
        if ($null -ne $response) {
            $response.Dispose()
        }
        $request.Dispose()
    }
}

function Get-Percentile {
    param(
        [Parameter(Mandatory = $true)]
        [object[]]$Values,
        [Parameter(Mandatory = $true)]
        [double]$Percentile
    )

    if ($Values.Count -eq 0) {
        return $null
    }
    $sorted = @($Values | ForEach-Object { [double]$_ } | Sort-Object)
    $index = [Math]::Ceiling($sorted.Count * $Percentile) - 1
    $index = [Math]::Max(0, [Math]::Min($sorted.Count - 1, $index))
    return [int][Math]::Round($sorted[$index])
}

function Invoke-ModifyBatch {
    param(
        [Parameter(Mandatory = $true)]
        [int]$Level,
        [Parameter(Mandatory = $true)]
        [object[]]$Processes
    )

    $batchResults = @()
    for ($offset = 0; $offset -lt $Processes.Count; $offset += $Level) {
        $lastIndex = [Math]::Min($Processes.Count - 1, $offset + $Level - 1)
        $pending = [Collections.ArrayList]::new()
        foreach ($descriptor in @($Processes[$offset..$lastIndex])) {
            $requestId = "capacity-$([Guid]::NewGuid().ToString('N'))"
            $request = New-JsonRequest `
                -Method "POST" `
                -Path "/api/v1/processes/$($descriptor.process_id)/modify" `
                -Body @{
                    request_id = $requestId
                    base_revision = 0
                    instruction = $Instruction
                    locale = "zh-CN"
                }
            $watch = [Diagnostics.Stopwatch]::StartNew()
            try {
                $task = $client.SendAsync($request)
                [void]$pending.Add([pscustomobject]@{
                    descriptor = $descriptor
                    request_id = $requestId
                    request = $request
                    task = $task
                    watch = $watch
                })
            }
            catch {
                $watch.Stop()
                $request.Dispose()
                $batchResults += [pscustomobject][ordered]@{
                    concurrency = $Level
                    sample_no = $descriptor.sample_no
                    process_id = $descriptor.process_id
                    request_id = $requestId
                    success = $false
                    status_code = 0
                    latency_ms = [int]$watch.Elapsed.TotalMilliseconds
                    error_code = "CLIENT_START_FAILED"
                    provider = $null
                    model = $null
                    attempts = $null
                    model_calls = $null
                    cache_status = $null
                }
            }
        }

        while ($pending.Count -gt 0) {
            for ($index = $pending.Count - 1; $index -ge 0; $index--) {
                $item = $pending[$index]
                if (-not $item.task.IsCompleted) {
                    continue
                }
                $item.watch.Stop()
                $sample = [ordered]@{
                    concurrency = $Level
                    sample_no = $item.descriptor.sample_no
                    process_id = $item.descriptor.process_id
                    request_id = $item.request_id
                    success = $false
                    status_code = 0
                    latency_ms = [int]$item.watch.Elapsed.TotalMilliseconds
                    error_code = $null
                    provider = $null
                    model = $null
                    attempts = $null
                    model_calls = $null
                    cache_status = $null
                }
                $response = $null
                try {
                    $response = $item.task.GetAwaiter().GetResult()
                    $sample.status_code = [int]$response.StatusCode
                    $responseText = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
                    $data = if ([string]::IsNullOrWhiteSpace($responseText)) {
                        $null
                    }
                    else {
                        $responseText | ConvertFrom-Json
                    }
                    $metrics = if ($null -ne $data) {
                        $property = $data.PSObject.Properties["metrics"]
                        if ($null -ne $property) { $property.Value } else { $null }
                    }
                    else {
                        $null
                    }
                    $errorObject = if ($null -ne $data) {
                        $property = $data.PSObject.Properties["error"]
                        if ($null -ne $property) { $property.Value } else { $null }
                    }
                    else {
                        $null
                    }
                    if ($response.IsSuccessStatusCode -and $null -ne $metrics) {
                        $sample.provider = [string]$metrics.provider
                        $sample.model = [string]$metrics.model
                        $sample.attempts = [int]$metrics.attempts
                        $sample.model_calls = [int]$metrics.model_calls
                        $sample.cache_status = [string]$metrics.cache_status
                        $sample.success = $true
                        if (
                            $RequireExternalProvider -and
                            ($sample.provider -eq "local" -or $sample.model_calls -ne 1)
                        ) {
                            $sample.success = $false
                            $sample.error_code = "EXTERNAL_PROVIDER_NOT_USED"
                        }
                    }
                    elseif ($null -ne $errorObject -and $null -ne $errorObject.code) {
                        $sample.error_code = [string]$errorObject.code
                    }
                    else {
                        $sample.error_code = if ($response.IsSuccessStatusCode) {
                            "INVALID_SUCCESS_RESPONSE"
                        }
                        else {
                            "HTTP_$([int]$response.StatusCode)"
                        }
                    }
                }
                catch {
                    $sample.error_code = "CLIENT_REQUEST_FAILED"
                }
                finally {
                    if ($null -ne $response) {
                        $response.Dispose()
                    }
                    $item.request.Dispose()
                }
                $batchResults += [pscustomobject]$sample
                $pending.RemoveAt($index)
            }
            if ($pending.Count -gt 0) {
                Start-Sleep -Milliseconds 5
            }
        }
    }
    return $batchResults
}

try {
    $ready = Invoke-CapacityApi -Method "GET" -Path "/health/ready"
    if ($null -eq $ready -or $ready.status -ne "ok") {
        throw "API readiness did not return status=ok."
    }
    $databaseBackend = [string]$ready.database_backend
    if ([string]::IsNullOrWhiteSpace($databaseBackend)) {
        throw "API readiness did not report database_backend."
    }
    if ($RequirePostgreSQL -and $databaseBackend -ne "postgresql") {
        throw "Capacity acceptance requires PostgreSQL, but readiness reported $databaseBackend."
    }

    $runId = [Guid]::NewGuid().ToString("N")
    $expectedCalls = $levels.Count * $SamplesPerLevel
    Write-Host "Capacity target: $apiRoot"
    Write-Host "Concurrency levels: $($levels -join ', '); samples per level: $SamplesPerLevel"
    Write-Host "This run creates $expectedCalls processes and may issue $expectedCalls external model calls."

    $project = Invoke-CapacityApi -Method "POST" -Path "/api/v1/projects" -Body @{
        name = "Capacity Test $runId"
        sap_context = @{
            edition = "S/4HANA"
            release = "2023"
            deployment = "private_cloud"
            country = "CN"
        }
    }
    if ($EnableExternalModel) {
        $project = Invoke-CapacityApi `
            -Method "PUT" `
            -Path "/api/v1/projects/$($project.id)" `
            -Body @{ external_model_enabled = $true }
        if (-not $project.external_model_enabled) {
            throw "The project did not enable the external model policy."
        }
    }

    $startedAt = [DateTime]::UtcNow
    $allSamples = @()
    foreach ($level in $levels) {
        $processes = @()
        for ($sampleNo = 1; $sampleNo -le $SamplesPerLevel; $sampleNo++) {
            $process = Invoke-CapacityApi `
                -Method "POST" `
                -Path "/api/v1/projects/$($project.id)/processes" `
                -Body @{
                    name = "Capacity L$level S$sampleNo"
                    module = "MM"
                    process_scope = "P2P"
                }
            $processes += [pscustomobject]@{
                process_id = [string]$process.id
                sample_no = $sampleNo
            }
        }
        $allSamples += @(Invoke-ModifyBatch -Level $level -Processes $processes)
    }

    $levelSummaries = @()
    $thresholdFailures = @()
    foreach ($level in $levels) {
        $samples = @($allSamples | Where-Object { $_.concurrency -eq $level })
        $successes = @($samples | Where-Object { $_.success })
        $latencies = @($successes | ForEach-Object { $_.latency_ms })
        $errorRate = if ($samples.Count -eq 0) {
            100.0
        }
        else {
            [Math]::Round(100.0 * ($samples.Count - $successes.Count) / $samples.Count, 2)
        }
        $p50 = Get-Percentile -Values $latencies -Percentile 0.50
        $p95 = Get-Percentile -Values $latencies -Percentile 0.95
        $p99 = Get-Percentile -Values $latencies -Percentile 0.99
        $levelPassed = (
            $successes.Count -gt 0 -and
            $errorRate -le $MaxErrorRatePercent -and
            $null -ne $p95 -and $p95 -le $MaxP95Ms -and
            $null -ne $p99 -and $p99 -le $MaxP99Ms
        )
        if (-not $levelPassed) {
            $thresholdFailures += "concurrency=$level error_rate=$errorRate p95=$p95 p99=$p99"
        }
        $cacheCounts = [ordered]@{ bypassed = 0; miss = 0; hit = 0; shared = 0 }
        foreach ($sample in $successes) {
            if ($cacheCounts.Contains([string]$sample.cache_status)) {
                $cacheCounts[[string]$sample.cache_status]++
            }
        }
        $modelCallSum = ($successes | Measure-Object -Property model_calls -Sum).Sum
        $levelSummaries += [pscustomobject][ordered]@{
            concurrency = $level
            samples = $samples.Count
            successes = $successes.Count
            error_rate_percent = $errorRate
            p50_ms = $p50
            p95_ms = $p95
            p99_ms = $p99
            reported_model_calls = if ($null -eq $modelCallSum) { 0 } else { [int]$modelCallSum }
            cache_status = $cacheCounts
            passed = $levelPassed
        }
    }

    $completedAt = [DateTime]::UtcNow
    $report = [ordered]@{
        schema_version = "1.0"
        run_id = $runId
        started_at_utc = $startedAt.ToString("o")
        completed_at_utc = $completedAt.ToString("o")
        target = $apiRoot
        project_id = [string]$project.id
        database_backend = $databaseBackend
        external_model_enabled = [bool]$EnableExternalModel
        external_provider_required = [bool]$RequireExternalProvider
        concurrency_levels = $levels
        samples_per_level = $SamplesPerLevel
        expected_modify_requests = $expectedCalls
        thresholds = [ordered]@{
            max_error_rate_percent = $MaxErrorRatePercent
            max_p95_ms = $MaxP95Ms
            max_p99_ms = $MaxP99Ms
        }
        levels = $levelSummaries
        passed = ($thresholdFailures.Count -eq 0)
        failures = $thresholdFailures
    }
    $stamp = $startedAt.ToString("yyyyMMdd-HHmmss")
    $reportPath = Join-Path $outputPath "capacity-report-$stamp.json"
    $samplesPath = Join-Path $outputPath "capacity-samples-$stamp.csv"
    $report | ConvertTo-Json -Depth 20 | Set-Content -Encoding utf8 -LiteralPath $reportPath
    $allSamples |
        Sort-Object concurrency, sample_no |
        Export-Csv -NoTypeInformation -Encoding utf8 -LiteralPath $samplesPath

    $levelSummaries | Format-Table -AutoSize
    Write-Host "Capacity report: $reportPath"
    Write-Host "Capacity samples: $samplesPath"
    Write-Host "Created project: $($project.id)"
    if (-not $report.passed) {
        throw "Capacity thresholds failed: $($thresholdFailures -join '; ')"
    }
    Write-Host "Capacity test passed for the configured target and thresholds."
}
finally {
    $client.Dispose()
}
