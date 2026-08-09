[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [string]$UserId = "local-user",
    [string]$AccessToken = "",
    [string]$Scenario = "",
    [string]$OutputDirectory = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$workspaceRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$scenarioPath = if ([string]::IsNullOrWhiteSpace($Scenario)) {
    Join-Path $workspaceRoot "examples\mm-p2p-acceptance-demo.json"
}
else {
    [IO.Path]::GetFullPath($Scenario)
}
$outputPath = if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    Join-Path $workspaceRoot "output\acceptance-demo"
}
else {
    [IO.Path]::GetFullPath($OutputDirectory)
}
$apiRoot = $BaseUrl.TrimEnd("/")
$effectiveAccessToken = if (-not [string]::IsNullOrWhiteSpace($AccessToken)) {
    $AccessToken
}
else {
    [Environment]::GetEnvironmentVariable("SAP_FLOW_ACCESS_TOKEN")
}
$headers = if ([string]::IsNullOrWhiteSpace($effectiveAccessToken)) {
    @{ "X-User-ID" = $UserId }
}
else {
    @{ "Authorization" = "Bearer $effectiveAccessToken" }
}

if (-not (Test-Path -LiteralPath $scenarioPath -PathType Leaf)) {
    throw "Demo scenario not found: $scenarioPath"
}
New-Item -ItemType Directory -Force -Path $outputPath | Out-Null
$scenarioData = Get-Content -Raw -Encoding utf8 -LiteralPath $scenarioPath | ConvertFrom-Json

function Invoke-DemoApi {
    param(
        [Parameter(Mandatory = $true)]
        [ValidateSet("GET", "POST", "PUT", "DELETE")]
        [string]$Method,
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [AllowNull()]
        [object]$Body = $null
    )

    $parameters = @{
        Uri = "$apiRoot$Path"
        Method = $Method
        Headers = $headers
        UseBasicParsing = $true
    }
    if ($null -ne $Body) {
        $parameters.ContentType = "application/json; charset=utf-8"
        $jsonBody = $Body | ConvertTo-Json -Depth 100 -Compress
        $parameters.Body = [Text.Encoding]::UTF8.GetBytes($jsonBody)
    }
    try {
        $response = Invoke-WebRequest @parameters
        if ($null -eq $response.RawContentStream -or $response.RawContentStream.Length -eq 0) {
            return $null
        }
        if ($response.RawContentStream.CanSeek) {
            $response.RawContentStream.Position = 0
        }
        $reader = [IO.StreamReader]::new(
            $response.RawContentStream,
            [Text.UTF8Encoding]::new($false),
            $true,
            1024,
            $true
        )
        try {
            $responseText = $reader.ReadToEnd()
        }
        finally {
            $reader.Dispose()
        }
        return $responseText | ConvertFrom-Json
    }
    catch {
        $responseBody = ""
        if ($null -ne $_.Exception.Response) {
            try {
                $reader = [IO.StreamReader]::new($_.Exception.Response.GetResponseStream())
                $responseBody = $reader.ReadToEnd()
                $reader.Dispose()
            }
            catch {
                $responseBody = ""
            }
        }
        throw "$Method $Path failed. $responseBody"
    }
}

$ready = Invoke-WebRequest -UseBasicParsing -Uri "$apiRoot/health/ready" -TimeoutSec 10
if ($ready.StatusCode -ne 200) {
    throw "API readiness check failed: $($ready.StatusCode)"
}

$project = Invoke-DemoApi -Method POST -Path "/api/v1/projects" -Body $scenarioData.project
$process = Invoke-DemoApi `
    -Method POST `
    -Path "/api/v1/projects/$($project.id)/processes" `
    -Body $scenarioData.process
$revision = [int]$process.current_revision
$graph = $process.graph

foreach ($instruction in $scenarioData.instructions) {
    $requestId = "acceptance-demo-$([Guid]::NewGuid().ToString('N'))"
    $modified = Invoke-DemoApi `
        -Method POST `
        -Path "/api/v1/processes/$($process.id)/modify" `
        -Body @{
            request_id = $requestId
            base_revision = $revision
            instruction = [string]$instruction
            locale = "zh-CN"
        }
    $revision = [int]$modified.result_revision
    $graph = $modified.graph
}

$expected = $scenarioData.expected
if ($graph.nodes.Count -ne [int]$expected.node_count) {
    throw "Unexpected node count: $($graph.nodes.Count)"
}
if ($graph.edges.Count -ne [int]$expected.edge_count) {
    throw "Unexpected edge count: $($graph.edges.Count)"
}
if ($graph.lanes.Count -ne [int]$expected.lane_count) {
    throw "Unexpected lane count: $($graph.lanes.Count)"
}
$actualNodeLabels = @($graph.nodes | ForEach-Object { [string]$_.label })
foreach ($expectedLabel in $expected.node_labels) {
    if ($actualNodeLabels -notcontains [string]$expectedLabel) {
        throw "Expected node is missing: $expectedLabel"
    }
}
$actualLaneLabels = @($graph.lanes | ForEach-Object { [string]$_.label })
foreach ($expectedLabel in $expected.lane_labels) {
    if ($actualLaneLabels -notcontains [string]$expectedLabel) {
        throw "Expected swimlane is missing: $expectedLabel"
    }
}
$approvalNode = $graph.nodes |
    Where-Object { $_.label -eq [string]$expected.approval_source_label } |
    Select-Object -First 1
$purchaseOrderNode = $graph.nodes |
    Where-Object { $_.label -eq [string]$expected.approval_target_label } |
    Select-Object -First 1
$approvalEdge = $graph.edges |
    Where-Object { $_.source -eq $approvalNode.id -and $_.target -eq $purchaseOrderNode.id } |
    Select-Object -First 1
if ($null -eq $approvalEdge -or $approvalEdge.label -ne [string]$expected.approval_edge_label) {
    throw "Approval edge label did not match the acceptance scenario."
}

$release = Invoke-DemoApi `
    -Method POST `
    -Path "/api/v1/processes/$($process.id)/releases" `
    -Body @{ base_revision = $revision }
$releaseDetail = Invoke-DemoApi `
    -Method GET `
    -Path "/api/v1/processes/$($process.id)/releases/$($release.release_no)"

$markdownPath = Join-Path $outputPath "mm-p2p-blueprint-release-$($release.release_no).md"
$docxPath = Join-Path $outputPath "mm-p2p-blueprint-release-$($release.release_no).docx"
foreach ($export in @(
    @{ format = "markdown"; path = $markdownPath },
    @{ format = "docx"; path = $docxPath }
)) {
    Invoke-WebRequest `
        -UseBasicParsing `
        -Uri "$apiRoot/api/v1/processes/$($process.id)/exports" `
        -Method POST `
        -Headers $headers `
        -ContentType "application/json; charset=utf-8" `
        -Body (@{ revision_no = $revision; format = $export.format } | ConvertTo-Json -Compress) `
        -OutFile $export.path
}

$docxBytes = [IO.File]::ReadAllBytes($docxPath)
if ($docxBytes.Length -lt 2 -or $docxBytes[0] -ne 0x50 -or $docxBytes[1] -ne 0x4B) {
    throw "DOCX export is not a valid ZIP payload: $docxPath"
}
$markdownText = Get-Content -Raw -Encoding utf8 -LiteralPath $markdownPath
if (-not $markdownText.Contains([string]$scenarioData.process.name)) {
    throw "Markdown export does not contain the process name: $markdownPath"
}

$summary = [ordered]@{
    project_id = $project.id
    process_id = $process.id
    revision_no = $releaseDetail.revision_no
    release_no = $releaseDetail.release_no
    lifecycle_state = $releaseDetail.lifecycle_state
    node_count = $releaseDetail.graph.nodes.Count
    edge_count = $releaseDetail.graph.edges.Count
    lane_count = $releaseDetail.graph.lanes.Count
    markdown = $markdownPath
    docx = $docxPath
}
$summaryPath = Join-Path $outputPath "acceptance-summary.json"
$summary | ConvertTo-Json -Depth 10 | Set-Content -Encoding utf8 -LiteralPath $summaryPath
[pscustomobject]$summary | Format-List
Write-Host "Acceptance demo passed. Summary: $summaryPath"
