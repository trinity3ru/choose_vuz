# Local dev startup: PostgreSQL -> Alembic -> backend -> parsers -> frontend.
# Usage from repo root:
#   powershell -ExecutionPolicy Bypass -File .\start-dev.ps1
#   powershell -ExecutionPolicy Bypass -File .\start-dev.ps1 -SkipParserWait
#
# Opens backend and frontend in separate PowerShell windows.

param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [int]$DbPort = 5544,
    [string]$DbContainerName = "univer_parser_db",
    [int]$BackendWaitSeconds = 45,
    # Skip parser start (only infra + backend + frontend).
    [switch]$SkipParser,
    # Open frontend while parsers still run in background.
    [switch]$SkipParserWait,
    # Optional: parse one major only, e.g. "09.03.04".
    [string]$MajorCode = "",
    # Max wait for all parsers before starting frontend.
    [int]$ParserWaitMinutes = 120
)

$ErrorActionPreference = "Stop"

$Root = $PSScriptRoot
$BackendDir = Join-Path $Root "backend"
$FrontendDir = Join-Path $Root "frontend"
$PythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"
$AlembicExe = Join-Path $BackendDir ".venv\Scripts\alembic.exe"
$EnvFile = Join-Path $BackendDir ".env"

function Write-Step([string]$Message) {
    Write-Host ""
    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Write-Ok([string]$Message) {
    Write-Host "OK: $Message" -ForegroundColor Green
}

function Write-Warn([string]$Message) {
    Write-Host "WARN: $Message" -ForegroundColor Yellow
}

function Write-Err([string]$Message) {
    Write-Host "ERROR: $Message" -ForegroundColor Red
}

function Test-TcpPortOpen([string]$HostName, [int]$Port) {
    $result = Test-NetConnection -ComputerName $HostName -Port $Port -WarningAction SilentlyContinue
    return [bool]$result.TcpTestSucceeded
}

function Test-BackendHealth([int]$Port) {
    try {
        $response = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/health" -UseBasicParsing -TimeoutSec 3
        return ($response.StatusCode -eq 200)
    }
    catch {
        return $false
    }
}

function Ensure-DockerDatabase {
    Write-Step "Docker PostgreSQL ($DbContainerName, port $DbPort)"

    $dockerCmd = Get-Command docker -ErrorAction SilentlyContinue
    if (-not $dockerCmd) {
        throw "Docker not found in PATH. Install Docker Desktop and restart the terminal."
    }

    $existing = docker ps -a --filter "name=^/${DbContainerName}$" --format "{{.Names}}" 2>$null
    if ($existing -eq $DbContainerName) {
        $status = docker inspect -f "{{.State.Status}}" $DbContainerName 2>$null
        if ($status -ne "running") {
            Write-Host "Container $DbContainerName is $status. Starting..."
            docker start $DbContainerName | Out-Null
        }
        else {
            Write-Ok "Container $DbContainerName is already running"
        }
    }
    else {
        Write-Host "Container not found. Creating $DbContainerName..."
        docker run -d `
            --name $DbContainerName `
            -e POSTGRES_USER=postgres `
            -e POSTGRES_PASSWORD=postgres `
            -e POSTGRES_DB=univer_parser `
            -p "${DbPort}:5432" `
            postgres:16-alpine | Out-Null
    }

    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline) {
        if (Test-TcpPortOpen -HostName "127.0.0.1" -Port $DbPort) {
            Write-Ok "PostgreSQL is ready on 127.0.0.1:$DbPort"
            return
        }
        Start-Sleep -Seconds 1
    }

    throw "PostgreSQL did not respond on port $DbPort in 30 seconds. Check: docker logs $DbContainerName"
}

function Ensure-BackendEnvironment {
    Write-Step "Checking backend environment"

    if (-not (Test-Path $BackendDir)) {
        throw "Backend folder not found: $BackendDir"
    }
    if (-not (Test-Path $PythonExe)) {
        throw "Python venv not found: $PythonExe. Run in backend: python -m venv .venv"
    }
    if (-not (Test-Path $AlembicExe)) {
        throw "Alembic not found: $AlembicExe"
    }
    if (-not (Test-Path $EnvFile)) {
        Write-Warn ".env not found. Copying from .env.example..."
        Copy-Item (Join-Path $BackendDir ".env.example") $EnvFile
    }

    Write-Ok "Backend environment is ready"
}

function Invoke-AlembicUpgrade {
    Write-Step "Running Alembic migrations"
    Push-Location $BackendDir
    try {
        & $AlembicExe upgrade head
        if ($LASTEXITCODE -ne 0) {
            throw "Alembic exited with code $LASTEXITCODE"
        }
        Write-Ok "Migrations applied"
    }
    finally {
        Pop-Location
    }
}

function Start-BackendWindow([int]$Port) {
    Write-Step "Starting backend (uvicorn) in a new window on port $Port"

    $backendCommand = @"
Set-Location -LiteralPath '$BackendDir'
Write-Host 'Backend: http://127.0.0.1:$Port' -ForegroundColor Green
Write-Host 'Swagger: http://127.0.0.1:$Port/docs' -ForegroundColor Green
& '$PythonExe' -m uvicorn app.main:app --host 127.0.0.1 --port $Port
"@

    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-Command",
        $backendCommand
    ) | Out-Null

    Write-Ok "Backend window opened"
}

function Wait-BackendReady([int]$Port, [int]$TimeoutSeconds) {
    Write-Step "Waiting for backend /health (up to $TimeoutSeconds sec)"

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-BackendHealth -Port $Port) {
            Write-Ok "Backend is ready: http://127.0.0.1:$Port/health"
            return
        }
        Start-Sleep -Seconds 1
    }

    throw "Backend did not respond in $TimeoutSeconds sec. Check the backend window."
}

function Start-FrontendWindow([int]$Port) {
    Write-Step "Starting frontend (Vite) in a new window on port $Port"

    if (-not (Test-Path $FrontendDir)) {
        throw "Frontend folder not found: $FrontendDir"
    }

    $npmCmd = Get-Command npm -ErrorAction SilentlyContinue
    if (-not $npmCmd) {
        throw "npm not found in PATH. Install Node.js LTS."
    }

    $frontendCommand = @"
Set-Location -LiteralPath '$FrontendDir'
Write-Host 'Frontend: http://localhost:$Port' -ForegroundColor Green
npm run dev
"@

    Start-Process powershell -ArgumentList @(
        "-NoExit",
        "-NoProfile",
        "-Command",
        $frontendCommand
    ) | Out-Null

    Write-Ok "Frontend window opened"
}

function Get-ParserStatus([int]$Port) {
    return Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v1/parser/status" -Method Get
}

function Start-AllParsers([int]$Port, [string]$MajorCode) {
    Write-Step "Starting all parsers (POST /api/v1/parser/start)"

    $uri = "http://127.0.0.1:$Port/api/v1/parser/start"
    try {
        if ($MajorCode) {
            $body = @{ major_code = $MajorCode } | ConvertTo-Json -Compress
            $response = Invoke-RestMethod -Uri $uri -Method Post -Body $body -ContentType "application/json"
            Write-Ok "Parser started for major $MajorCode"
        }
        else {
            $response = Invoke-RestMethod -Uri $uri -Method Post
            Write-Ok "Parser started for all universities"
        }
        if ($response.major_code) {
            Write-Host "  major_code: $($response.major_code)"
        }
    }
    catch {
        $httpStatus = $null
        if ($_.Exception.Response) {
            $httpStatus = [int]$_.Exception.Response.StatusCode
        }
        if ($httpStatus -eq 409) {
            Write-Warn "Parser is already running - will wait for completion"
            return
        }
        throw
    }
}

function Wait-ParserComplete([int]$Port, [int]$TimeoutMinutes) {
    Write-Step "Waiting for parsers (up to $TimeoutMinutes min)"

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    while ((Get-Date) -lt $deadline) {
        $status = Get-ParserStatus -Port $Port
        if (-not $status.is_running) {
            if ($status.last_snapshot) {
                $snap = $status.last_snapshot
                Write-Ok "Parser finished: status=$($snap.status), applicants=$($snap.applicants_count)"
                if ($snap.error_log) {
                    Write-Warn "Parser errors: $($snap.error_log)"
                }
            }
            else {
                Write-Ok "Parser finished (no snapshots in DB yet)"
            }
            return
        }

        $applicants = 0
        $snapStatus = "n/a"
        if ($status.last_snapshot) {
            $applicants = $status.last_snapshot.applicants_count
            $snapStatus = $status.last_snapshot.status
        }
        Write-Host "  parsing... snapshot=$snapStatus, applicants=$applicants"
        Start-Sleep -Seconds 10
    }

    throw "Parser did not finish in $TimeoutMinutes minutes. Use -SkipParserWait or check backend logs."
}

try {
    Write-Host "Univercity_parser - dev startup" -ForegroundColor White

    Ensure-BackendEnvironment
    Ensure-DockerDatabase
    Invoke-AlembicUpgrade

    if (Test-BackendHealth -Port $BackendPort) {
        Write-Ok "Backend already running on port $BackendPort - skipping new window"
    }
    else {
        if (Test-TcpPortOpen -HostName "127.0.0.1" -Port $BackendPort) {
            throw "Port $BackendPort is busy but /health is not OK. Free the port or use -BackendPort."
        }
        Start-BackendWindow -Port $BackendPort
        Wait-BackendReady -Port $BackendPort -TimeoutSeconds $BackendWaitSeconds
    }

    if (-not $SkipParser) {
        Start-AllParsers -Port $BackendPort -MajorCode $MajorCode
        if (-not $SkipParserWait) {
            Wait-ParserComplete -Port $BackendPort -TimeoutMinutes $ParserWaitMinutes
        }
        else {
            Write-Warn "Frontend will open now; refresh page when parser finishes"
        }
    }

    Start-FrontendWindow -Port $FrontendPort

    Write-Host ""
    Write-Host "Done." -ForegroundColor Green
    Write-Host "  Backend:  http://127.0.0.1:$BackendPort"
    Write-Host "  Frontend: http://localhost:$FrontendPort"
    if (-not $SkipParser) {
        Write-Host "  Parser status: http://127.0.0.1:$BackendPort/api/v1/parser/status"
    }
    Write-Host ""
    Write-Host "Stop DB: docker stop $DbContainerName"
}
catch {
    Write-Err $_.Exception.Message
    exit 1
}
