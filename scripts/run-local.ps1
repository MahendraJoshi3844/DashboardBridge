<#
.SYNOPSIS
    Start DashboardBridge on this machine, end to end.

.DESCRIPTION
    One command, because starting it by hand needs six environment variables
    and three of them fail silently when wrong.

        pwsh scripts/run-local.ps1

    Then open http://localhost:3000 and sign in with the account it prints.

    What it does, in order:

      1. Makes a **development** licence if there is not one yet, under
         ~/.dashboardbridge-dev. This is not your vendor identity - that one
         you create yourself with `t2pbi-license keygen`, outside any
         repository, and it signs what your customers run. This one is a
         throwaway so the application will start.
      2. Migrates the database (SQLite, in the same folder).
      3. Starts the API, and the web app pointed at it.

    Three things here are not arbitrary and will waste an afternoon if changed:

      * **Port 8010, not 8000.** 8000 is blocked on this machine (WinError
        10013) and the failure looks like the app hanging.
      * **`localhost`, not `127.0.0.1`, for the API URL.** The session cookie
        is `SameSite=Lax`, which compares registrable domains: `localhost:3000`
        and `localhost:8010` are the same site, so the cookie is sent.
        `127.0.0.1` is a *different* site, and every request would be
        anonymous - silently, with a 401 and no explanation.
      * **`BOOTSTRAP_ADMIN_*` only works on an empty database.** Once an
         account exists the variables do nothing, which is deliberate: a value
         left in a compose file must not re-create an administrator somebody
         removed.

.PARAMETER Reset
    Delete the local database and start from an empty deployment.
#>
[CmdletBinding()]
param(
    [switch]$Reset,
    [int]$ApiPort = 8010,
    [int]$WebPort = 3000
)

$ErrorActionPreference = "Stop"
$Repo = Split-Path -Parent $PSScriptRoot
$Home_ = [Environment]::GetFolderPath("UserProfile")
$DevDir = Join-Path $Home_ ".dashboardbridge-dev"
$Email = "you@localhost"
$Password = "dashboardbridge dev login"

New-Item -ItemType Directory -Force -Path $DevDir | Out-Null

$env:PYTHONPATH = "$Repo\packages\contracts\src;$Repo\apps\api;$Repo"

# --- 1. a development licence -------------------------------------------------

$PrivateKey = Join-Path $DevDir "vendor-private.pem"
$PublicKey = Join-Path $DevDir "vendor-public.pem"
$Licence = Join-Path $DevDir "development.lic"

if (-not (Test-Path $PublicKey)) {
    Write-Host "Creating a development licence in $DevDir" -ForegroundColor Cyan
    python -m engines.licensing.cli keygen --out $DevDir | Out-Null
}
if (-not (Test-Path $Licence)) {
    python -m engines.licensing.cli issue `
        --key $PrivateKey `
        --customer "Local development" `
        --days 365 `
        --features convert `
        --seats 10 `
        --out $Licence | Out-Null
}

$env:LICENSE_PUBLIC_KEY = Get-Content $PublicKey -Raw
$env:LICENSE_FILE = $Licence

# --- 2. the database ----------------------------------------------------------

$Database = Join-Path $DevDir "dashboardbridge.db"
if ($Reset -and (Test-Path $Database)) {
    Remove-Item $Database -Force
    Write-Host "Removed the existing database." -ForegroundColor Yellow
}
$env:DATABASE_URL = "sqlite+pysqlite:///" + ($Database -replace '\\', '/')
$env:BOOTSTRAP_ADMIN_EMAIL = $Email
$env:BOOTSTRAP_ADMIN_PASSWORD = $Password
$env:ARTIFACT_STORAGE_DIR = Join-Path $DevDir "artifacts"

Push-Location (Join-Path $Repo "apps\api")
try {
    python -m alembic upgrade head 2>&1 | Select-Object -Last 1
}
finally {
    Pop-Location
}

# --- 3. both halves -----------------------------------------------------------

$apiEnv = @{
    PYTHONPATH              = $env:PYTHONPATH
    LICENSE_PUBLIC_KEY      = $env:LICENSE_PUBLIC_KEY
    LICENSE_FILE            = $env:LICENSE_FILE
    DATABASE_URL            = $env:DATABASE_URL
    BOOTSTRAP_ADMIN_EMAIL   = $env:BOOTSTRAP_ADMIN_EMAIL
    BOOTSTRAP_ADMIN_PASSWORD = $env:BOOTSTRAP_ADMIN_PASSWORD
    ARTIFACT_STORAGE_DIR    = $env:ARTIFACT_STORAGE_DIR
}

$api = Start-Job -Name dbb-api -ScriptBlock {
    param($repo, $port, $vars)
    foreach ($pair in $vars.GetEnumerator()) {
        Set-Item -Path "env:$($pair.Key)" -Value $pair.Value
    }
    Set-Location (Join-Path $repo "apps\api")
    python -m uvicorn app.main:app --port $port --host 127.0.0.1
} -ArgumentList $Repo, $ApiPort, $apiEnv

$web = Start-Job -Name dbb-web -ScriptBlock {
    param($repo, $apiPort, $webPort)
    # `localhost`, deliberately. See the note at the top of this file.
    $env:NEXT_PUBLIC_API_URL = "http://localhost:$apiPort"
    Set-Location (Join-Path $repo "apps\web")
    npx next dev -p $webPort
} -ArgumentList $Repo, $ApiPort, $WebPort

Write-Host ""
Write-Host "Waiting for the API…" -NoNewline
$ready = $false
foreach ($attempt in 1..40) {
    Start-Sleep -Seconds 1
    try {
        Invoke-RestMethod "http://127.0.0.1:$ApiPort/api/v1/health" -TimeoutSec 2 | Out-Null
        $ready = $true
        break
    }
    catch { Write-Host "." -NoNewline }
}
Write-Host ""

if (-not $ready) {
    Write-Host "The API did not answer. Its output:" -ForegroundColor Red
    Receive-Job -Job $api
    Stop-Job $api, $web -ErrorAction SilentlyContinue
    Remove-Job $api, $web -Force -ErrorAction SilentlyContinue
    exit 1
}

Write-Host ""
Write-Host "  DashboardBridge is running." -ForegroundColor Green
Write-Host ""
Write-Host "    Web        http://localhost:$WebPort"
Write-Host "    API        http://localhost:$ApiPort/api/docs"
Write-Host ""
Write-Host "    Sign in    $Email"
Write-Host "               $Password"
Write-Host ""
Write-Host "  A Tableau workbook to try is in testing_content\Superstore.twb."
Write-Host "  Ctrl+C stops both."
Write-Host ""

# Stop when a job has actually *ended*, not when it is merely not yet running.
# `-ne "Running"` is true for `NotStarted` too, so the first version of this
# loop exited immediately - the script printed "running" and then "Stopped" in
# the same breath, having killed a web server that was still starting up.
$Finished = @("Completed", "Failed", "Stopped")

# From here the script only relays two servers' logs, and **uvicorn writes its
# ordinary output to stderr**. Under `$ErrorActionPreference = "Stop"` that
# arrives from `Receive-Job` as a terminating error, so the launcher killed both
# servers the moment the API said "Started server process" - printing "running"
# and "Stopped" one line apart, with the cause rendered in red as though it were
# the failure rather than the trigger.
$ErrorActionPreference = "Continue"

try {
    while ($true) {
        Receive-Job -Job $api, $web
        if ($Finished -contains $api.State -or $Finished -contains $web.State) {
            break
        }
        Start-Sleep -Seconds 1
    }
    Receive-Job -Job $api, $web
    Write-Host "One of the two stopped on its own." -ForegroundColor Red
}
finally {
    Stop-Job $api, $web -ErrorAction SilentlyContinue
    Remove-Job $api, $web -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped." -ForegroundColor Yellow
}
