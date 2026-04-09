param(
    [string]$BaseUrl = "http://localhost:5055",
    [string[]]$MovieLibraries = @(),
    [string[]]$TvLibraries = @(),
    [int[]]$ConcurrencyList = @(1, 4, 8),
    [int]$PollIntervalSeconds = 2,
    [int]$TimeoutMinutes = 180,
    [string]$OutputDir = "X:\codex\tasks\reports\sync-performance",
    [switch]$KeepTestSettings
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Invoke-ApiJson {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST", "PUT")] [string]$Method,
        [Parameter(Mandatory = $true)][string]$Url,
        [object]$Body = $null,
        [int]$TimeoutSec = 30
    )

    if ($Method -eq "GET") {
        return Invoke-RestMethod -Method Get -Uri $Url -TimeoutSec $TimeoutSec
    }

    if ($null -eq $Body) {
        return Invoke-RestMethod -Method $Method -Uri $Url -TimeoutSec $TimeoutSec
    }

    $json = $Body | ConvertTo-Json -Depth 20
    return Invoke-RestMethod -Method $Method -Uri $Url -ContentType "application/json" -Body $json -TimeoutSec $TimeoutSec
}

function Wait-SyncIdle {
    param(
        [string]$ApiBase,
        [int]$TimeoutSec = 120
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $status = Invoke-ApiJson -Method GET -Url "$ApiBase/sync/status"
        if ($status.state -ne "running") {
            return $status
        }
        Start-Sleep -Seconds 1
    }
    throw "Sync still running after waiting $TimeoutSec seconds."
}

function New-Scenario {
    param(
        [string]$Name,
        [string[]]$Libraries
    )
    return [PSCustomObject]@{
        Name = $Name
        Libraries = @($Libraries | Where-Object { $_ -and $_.Trim() } | ForEach-Object { $_.Trim() } | Select-Object -Unique)
    }
}

function Build-MarkdownSummary {
    param(
        [Parameter(Mandatory = $true)] [System.Collections.IEnumerable]$Rows
    )

    $lines = @()
    $lines += "# Sync Performance Validation Summary"
    $lines += ""
    $lines += "| Scenario | Concurrency | Result | Duration(s) | Items Synced | Discovered | Fallback (done/total) | Failed Items | list_library_items(s) | detail_requests(s) | db_insert(s) | analysis(s) |"
    $lines += "| --- | ---: | --- | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |"

    foreach ($r in $Rows) {
        $lines += "| $($r.scenario_name) | $($r.concurrency) | $($r.last_result) | $([math]::Round([double]$r.duration_seconds, 2)) | $($r.items_synced) | $($r.items_discovered) | $($r.detail_requests_completed)/$($r.detail_requests_total) | $($r.failed_items) | $([math]::Round([double]$r.timing_list_library_items, 2)) | $([math]::Round([double]$r.timing_detail_requests, 2)) | $([math]::Round([double]$r.timing_db_insert, 2)) | $([math]::Round([double]$r.timing_analysis, 2)) |"
    }

    return ($lines -join "`r`n")
}

function Get-AvailableLibraryNames {
    param([string]$ApiBase)
    $resp = Invoke-ApiJson -Method GET -Url "$ApiBase/libraries"
    $items = @()
    if ($resp -and $resp.items) {
        $items = @($resp.items)
    }
    return @(
        $items |
            ForEach-Object { [string]$_.name } |
            Where-Object { $_ -and $_.Trim() } |
            Select-Object -Unique
    )
}

function Validate-Libraries {
    param(
        [string[]]$Wanted,
        [string[]]$Available,
        [string]$ScenarioName
    )
    $availSet = @{}
    foreach ($a in $Available) {
        $availSet[$a.ToLowerInvariant()] = $a
    }
    $missing = @()
    foreach ($w in $Wanted) {
        if (-not $availSet.ContainsKey($w.ToLowerInvariant())) {
            $missing += $w
        }
    }
    if ($missing.Count -gt 0) {
        throw "Scenario '$ScenarioName' has invalid libraries: $($missing -join ', '). Available libraries: $($Available -join ', ')"
    }
}

$apiBase = $BaseUrl.TrimEnd("/")
$runId = Get-Date -Format "yyyyMMdd-HHmmss"
$runDir = Join-Path $OutputDir $runId
New-Item -ItemType Directory -Path $runDir -Force | Out-Null

Write-Host "Run ID: $runId"
Write-Host "Output: $runDir"
Write-Host "API Base: $apiBase"

$health = Invoke-ApiJson -Method GET -Url "$apiBase/health"
Write-Host "Health OK: $($health.status)"

$originalSettings = Invoke-ApiJson -Method GET -Url "$apiBase/settings"
$originalSettingsPath = Join-Path $runDir "settings.before.json"
$originalSettings | ConvertTo-Json -Depth 20 | Out-File -FilePath $originalSettingsPath -Encoding utf8

$scenarioList = New-Object System.Collections.Generic.List[object]
$movieUnique = @($MovieLibraries | Where-Object { $_ -and $_.Trim() } | ForEach-Object { $_.Trim() } | Select-Object -Unique)
$tvUnique = @($TvLibraries | Where-Object { $_ -and $_.Trim() } | ForEach-Object { $_.Trim() } | Select-Object -Unique)

if ($movieUnique.Count -gt 0) {
    $scenarioList.Add((New-Scenario -Name "movies-only" -Libraries $movieUnique))
}
if ($movieUnique.Count -gt 0 -and $tvUnique.Count -gt 0) {
    $combo = @($movieUnique + $tvUnique | Select-Object -Unique)
    $scenarioList.Add((New-Scenario -Name "movies-plus-tv" -Libraries $combo))
}
if ($scenarioList.Count -eq 0) {
    $currentLibs = @($originalSettings.libraries)
    $scenarioList.Add((New-Scenario -Name "current-libraries" -Libraries $currentLibs))
}

$availableLibraries = Get-AvailableLibraryNames -ApiBase $apiBase
if ($availableLibraries.Count -eq 0) {
    throw "No libraries returned by /libraries. Please verify Emby settings and connectivity first."
}
Write-Host "Available libraries: $($availableLibraries -join ', ')"
foreach ($scenario in $scenarioList) {
    Validate-Libraries -Wanted $scenario.Libraries -Available $availableLibraries -ScenarioName $scenario.Name
}

$resultRows = New-Object System.Collections.Generic.List[object]

try {
    Wait-SyncIdle -ApiBase $apiBase -TimeoutSec 120 | Out-Null

    foreach ($scenario in $scenarioList) {
        foreach ($concurrency in $ConcurrencyList) {
            $safeScenario = ($scenario.Name -replace "[^a-zA-Z0-9\-_]", "_")
            $runLabel = "$safeScenario-c$concurrency"
            Write-Host ""
            Write-Host "=== Running $runLabel ==="
            Write-Host "Libraries: $($scenario.Libraries -join ', ')"

            $payload = [ordered]@{
                emby = [ordered]@{
                    base_url = [string]$originalSettings.emby.base_url
                    api_key  = [string]$originalSettings.emby.api_key
                    user_id  = [string]$originalSettings.emby.user_id
                }
                libraries = @($scenario.Libraries)
                excluded_paths = @($originalSettings.excluded_paths)
                sync = [ordered]@{
                    concurrency = [int]$concurrency
                }
                shenyi = [ordered]@{
                    base_url = [string]$originalSettings.shenyi.base_url
                    api_key  = [string]$originalSettings.shenyi.api_key
                }
                webhook_token = [string]$originalSettings.webhook_token
            }

            Invoke-ApiJson -Method PUT -Url "$apiBase/settings" -Body $payload | Out-Null
            Write-Host "Settings updated for $runLabel"

            $triggeredAt = Get-Date
            Invoke-ApiJson -Method POST -Url "$apiBase/sync" | Out-Null
            Write-Host "Sync triggered at $($triggeredAt.ToString("s"))"

            $snapshots = New-Object System.Collections.Generic.List[object]
            $deadline = $triggeredAt.AddMinutes($TimeoutMinutes)
            $finalStatus = $null

            while ($true) {
                $status = Invoke-ApiJson -Method GET -Url "$apiBase/sync/status"
                $snapshots.Add([PSCustomObject]@{
                    polled_at = (Get-Date).ToString("s")
                    state = [string]$status.state
                    current_step = [string]$status.current_step
                    current_library = [string]$status.current_library
                    items_synced = [int]$status.items_synced
                    items_discovered = [int]$status.items_discovered
                    libraries_total = [int]$status.libraries_total
                    libraries_completed = [int]$status.libraries_completed
                    detail_requests_total = [int]$status.detail_requests_total
                    detail_requests_completed = [int]$status.detail_requests_completed
                    current_page = [int]$status.current_page
                    current_page_size = [int]$status.current_page_size
                    current_library_total_items = [int]$status.current_library_total_items
                    failed_items = [int]$status.failed_items
                })

                if ([string]$status.state -ne "running" -and [string]$status.last_finished_at) {
                    $finalStatus = $status
                    break
                }

                if ((Get-Date) -gt $deadline) {
                    throw "Timeout waiting sync completion for $runLabel."
                }
                Start-Sleep -Seconds $PollIntervalSeconds
            }

            $snapPath = Join-Path $runDir "$runLabel.snapshots.json"
            $snapshots | ConvertTo-Json -Depth 20 | Out-File -FilePath $snapPath -Encoding utf8

            $timings = @{}
            if ($finalStatus.timings) {
                $timings = $finalStatus.timings
            }

            $row = [PSCustomObject]@{
                run_id = $runId
                scenario_name = $scenario.Name
                concurrency = [int]$concurrency
                libraries = ($scenario.Libraries -join ";")
                state = [string]$finalStatus.state
                last_result = [string]$finalStatus.last_result
                error = [string]$finalStatus.error
                analysis_error = [string]$finalStatus.analysis_error
                last_started_at = [string]$finalStatus.last_started_at
                last_finished_at = [string]$finalStatus.last_finished_at
                duration_seconds = [double]($finalStatus.duration_seconds | ForEach-Object { if ($null -eq $_) { 0 } else { $_ } })
                items_synced = [int]$finalStatus.items_synced
                items_discovered = [int]$finalStatus.items_discovered
                detail_requests_total = [int]$finalStatus.detail_requests_total
                detail_requests_completed = [int]$finalStatus.detail_requests_completed
                failed_items = [int]$finalStatus.failed_items
                analysis_groups = [int]$finalStatus.analysis_groups
                timing_list_user_views = [double]($timings.list_user_views | ForEach-Object { if ($null -eq $_) { 0 } else { $_ } })
                timing_list_library_items = [double]($timings.list_library_items | ForEach-Object { if ($null -eq $_) { 0 } else { $_ } })
                timing_detail_requests = [double]($timings.detail_requests | ForEach-Object { if ($null -eq $_) { 0 } else { $_ } })
                timing_normalize_items = [double]($timings.normalize_items | ForEach-Object { if ($null -eq $_) { 0 } else { $_ } })
                timing_db_delete = [double]($timings.db_delete | ForEach-Object { if ($null -eq $_) { 0 } else { $_ } })
                timing_db_insert = [double]($timings.db_insert | ForEach-Object { if ($null -eq $_) { 0 } else { $_ } })
                timing_analysis = [double]($timings.analysis | ForEach-Object { if ($null -eq $_) { 0 } else { $_ } })
            }
            $resultRows.Add($row)

            Write-Host ("Completed {0}: result={1}, duration={2}s, synced={3}, fallback={4}/{5}" -f `
                $runLabel, $row.last_result, ([math]::Round($row.duration_seconds, 2)), $row.items_synced, `
                $row.detail_requests_completed, $row.detail_requests_total)
        }
    }
}
finally {
    if (-not $KeepTestSettings) {
        try {
            Invoke-ApiJson -Method PUT -Url "$apiBase/settings" -Body $originalSettings | Out-Null
            Write-Host "Settings restored to original snapshot."
        }
        catch {
            Write-Warning "Failed to restore settings automatically: $($_.Exception.Message)"
        }
    }
}

$jsonPath = Join-Path $runDir "results.json"
$csvPath = Join-Path $runDir "results.csv"
$mdPath = Join-Path $runDir "SUMMARY.md"

$resultRows | ConvertTo-Json -Depth 20 | Out-File -FilePath $jsonPath -Encoding utf8
$resultRows | Export-Csv -Path $csvPath -NoTypeInformation -Encoding UTF8

$summary = Build-MarkdownSummary -Rows $resultRows
$summary | Out-File -FilePath $mdPath -Encoding utf8

Write-Host ""
Write-Host "Done."
Write-Host "JSON: $jsonPath"
Write-Host "CSV : $csvPath"
Write-Host "MD  : $mdPath"



