# ─────────────────────────────────────────────────────────────
# AI Runtime OS - one-click bootstrap for Windows
#
#   pwsh -File scripts\setup.ps1
#   pwsh -File scripts\setup.ps1 -SkipFrontend
#   pwsh -File scripts\setup.ps1 -Locked      # use exact pinned versions
#
# Safe to re-run: existing venv / .env / node_modules are kept.
# ─────────────────────────────────────────────────────────────
param(
    [switch]$SkipBackend,
    [switch]$SkipFrontend,
    [switch]$Locked
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$backend = Join-Path $root "backend"
$frontend = Join-Path $root "frontend"

function Write-Step($msg) { Write-Host "`n==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "    OK  $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "    !!  $msg" -ForegroundColor Yellow }

Write-Host "AI Runtime OS bootstrap" -ForegroundColor White
Write-Host "repo: $root"

# ---------- backend ----------
if (-not $SkipBackend) {
    Write-Step "Checking Python"

    $py = $null
    foreach ($cand in @("python", "py")) {
        try {
            $ver = & $cand -c "import sys;print('%d.%d'%sys.version_info[:2])" 2>$null
            if ($LASTEXITCODE -eq 0 -and $ver) { $py = $cand; break }
        } catch { }
    }
    if (-not $py) { throw "Python not found in PATH. Install Python 3.11+ first: https://python.org" }

    $verStr = & $py -c "import sys;print('%d.%d.%d'%sys.version_info[:3])"
    $major, $minor = $verStr.Split(".")[0..1] | ForEach-Object { [int]$_ }
    if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 11)) {
        throw "Python $verStr is too old. This project needs 3.11+ (tested on 3.13)."
    }
    Write-Ok "Python $verStr"

    Write-Step "Preparing virtualenv (backend/.venv)"
    $venvPy = Join-Path $backend ".venv\Scripts\python.exe"
    if (Test-Path $venvPy) {
        Write-Ok "venv already exists, reusing"
    } else {
        Push-Location $backend
        & $py -m venv .venv
        Pop-Location
        if (-not (Test-Path $venvPy)) { throw "Failed to create venv at $venvPy" }
        Write-Ok "venv created"
    }

    Write-Step "Installing Python dependencies"
    Push-Location $backend
    & $venvPy -m pip install --upgrade pip --quiet
    $reqFile = if ($Locked) { "requirements.lock.txt" } else { "requirements.txt" }
    Write-Host "    using $reqFile"
    & $venvPy -m pip install -r $reqFile
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "pip install failed" }
    Write-Ok "dependencies installed"
    Pop-Location

    Write-Step "Preparing backend/.env"
    $envFile = Join-Path $backend ".env"
    if (Test-Path $envFile) {
        Write-Ok ".env already exists, left untouched"
    } else {
        Copy-Item (Join-Path $backend ".env.example") $envFile
        Write-Ok ".env created from .env.example"
        Write-Warn2 "Fill in OPENAI_API_KEY / OPENAI_BASE_URL, and replace SECRET_KEY before going live."
    }
}

# ---------- frontend ----------
if (-not $SkipFrontend) {
    Write-Step "Checking Node.js"
    try { $nodeVer = (& node -v).Trim() } catch { throw "Node.js not found. Install Node 18+ (tested on 22)." }
    $nodeMajor = [int]($nodeVer.TrimStart("v").Split(".")[0])
    if ($nodeMajor -lt 18) { throw "Node $nodeVer is too old, need 18+." }
    Write-Ok "Node $nodeVer"

    Write-Step "Installing frontend dependencies"
    Push-Location $frontend
    if (Test-Path "node_modules") {
        Write-Ok "node_modules exists, running npm install to sync"
    }
    npm install
    if ($LASTEXITCODE -ne 0) { Pop-Location; throw "npm install failed" }
    Write-Ok "node_modules ready"
    Pop-Location
}

# ---------- done ----------
Write-Host "`n-------------------------------------------------------------" -ForegroundColor White
Write-Host "Environment ready. Next steps:" -ForegroundColor White
Write-Host ""
Write-Host "  1) Seed roles/permissions (run ONCE, it has no dedup guard):"
Write-Host "       cd backend"
Write-Host "       .venv\Scripts\python.exe -m app.seed"
Write-Host ""
Write-Host "  2) Start backend (tables are auto-created on startup when DEBUG=true):"
Write-Host "       cd backend"
Write-Host "       .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8002 --reload"
Write-Host ""
Write-Host "  3) Start frontend in another terminal:"
Write-Host "       cd frontend"
Write-Host "       npm run dev"
Write-Host ""
Write-Host "  Docs: http://127.0.0.1:8002/docs   App: http://localhost:5176" -ForegroundColor White
Write-Host "-------------------------------------------------------------" -ForegroundColor White
