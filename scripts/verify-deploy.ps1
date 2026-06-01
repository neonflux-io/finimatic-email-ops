param(
    [Parameter(Mandatory = $true)]
    [string]$BackendUrl,

    [Parameter(Mandatory = $false)]
    [string]$FrontendUrl,

    [Parameter(Mandatory = $false)]
    [string]$SupabaseUrl = "https://hpamfbjawuyztqowtrth.supabase.co"
)

$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

function Normalize-Origin {
    param([string]$Url)
    return $Url.Trim().TrimEnd("/")
}

function Add-Check {
    param(
        [string]$Name,
        [bool]$Passed,
        [string]$Detail
    )

    $script:Results += [pscustomobject]@{
        check = $Name
        passed = $Passed
        detail = $Detail
    }
}

$Results = @()
$Backend = Normalize-Origin $BackendUrl
$Frontend = if ($FrontendUrl) { Normalize-Origin $FrontendUrl } else { "" }
$Supabase = Normalize-Origin $SupabaseUrl

try {
    $health = Invoke-RestMethod -Method Get -Uri "$Backend/api/health" -TimeoutSec 20
    Add-Check "backend_health" ($health.status -eq "ok") "GET $Backend/api/health returned status=$($health.status)"
} catch {
    Add-Check "backend_health" $false $_.Exception.Message
}

try {
    $settingsResponse = Invoke-WebRequest -Method Get -Uri "$Backend/api/settings" -TimeoutSec 20
    $settingsText = [string]$settingsResponse.Content
    $containsSecretPrefix = $settingsText -match "gsk_|AIza|rnd_|vcp_|gAAAA"
    Add-Check "settings_no_raw_secret_prefixes" (-not $containsSecretPrefix) "GET /api/settings completed with HTTP $($settingsResponse.StatusCode)"
} catch {
    Add-Check "settings_no_raw_secret_prefixes" $false $_.Exception.Message
}

if ($Frontend) {
    try {
        $front = Invoke-WebRequest -Method Get -Uri $Frontend -TimeoutSec 20
        $hasRoot = ([string]$front.Content) -match 'id="root"'
        Add-Check "frontend_loads" (($front.StatusCode -ge 200) -and ($front.StatusCode -lt 400) -and $hasRoot) "GET $Frontend returned HTTP $($front.StatusCode)"
    } catch {
        Add-Check "frontend_loads" $false $_.Exception.Message
    }

    try {
        $cors = Invoke-WebRequest -Method Options -Uri "$Backend/api/health" -Headers @{
            Origin = $Frontend
            "Access-Control-Request-Method" = "GET"
        } -TimeoutSec 20
        $allowOrigin = $cors.Headers["Access-Control-Allow-Origin"]
        Add-Check "cors_allows_frontend" ($allowOrigin -eq $Frontend) "Access-Control-Allow-Origin=$allowOrigin"
    } catch {
        Add-Check "cors_allows_frontend" $false $_.Exception.Message
    }
} else {
    Add-Check "frontend_loads" $false "Skipped: pass -FrontendUrl after Vercel deploy"
    Add-Check "cors_allows_frontend" $false "Skipped: pass -FrontendUrl after Vercel deploy"
}

try {
    $supabaseRest = Invoke-WebRequest -Method Get -Uri "$Supabase/rest/v1/" -TimeoutSec 20
    Add-Check "supabase_api_reachable" (($supabaseRest.StatusCode -ge 200) -and ($supabaseRest.StatusCode -lt 500)) "GET $Supabase/rest/v1/ returned HTTP $($supabaseRest.StatusCode)"
} catch {
    $status = $null
    if ($_.Exception.Response) {
        $status = [int]$_.Exception.Response.StatusCode
    }
    $reachable = $status -in @(401, 403, 404)
    Add-Check "supabase_api_reachable" $reachable "GET $Supabase/rest/v1/ returned HTTP $status"
}

$Results | Format-Table -AutoSize

$failed = @($Results | Where-Object { -not $_.passed })
if ($failed.Count -gt 0) {
    Write-Error "Deployment verification failed: $($failed.Count) check(s) failed."
    exit 1
}

Write-Host "Deployment verification passed."
