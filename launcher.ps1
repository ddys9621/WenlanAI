# HH小说创作 - One-click Launcher
# Build frontend -> Start pywebview desktop app (single process, no terminal)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$frontendDir = Join-Path $scriptDir "frontend"
$backendDir  = Join-Path $scriptDir "backend"
$staticDir   = Join-Path $backendDir "static"
$indexFile   = Join-Path $staticDir "index.html"

function Print-Step($msg) { Write-Host "`n== $msg ==" -ForegroundColor Cyan }
function Print-Ok($msg)   { Write-Host "[OK] $msg" -ForegroundColor Green }
function Print-Err($msg)  { Write-Host "[ERROR] $msg" -ForegroundColor Red }

Clear-Host
Write-Host "HH小说创作 Launcher" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green

# Step 1: Check Node.js and Python
Print-Step "Check Environment"
$missing = @()
if (-not (Get-Command "node" -ErrorAction SilentlyContinue)) { $missing += "Node.js" }
if (-not (Get-Command "python" -ErrorAction SilentlyContinue)) { $missing += "Python" }
if ($missing.Count -gt 0) {
    Print-Err ("Missing: " + ($missing -join ", "))
    pause
    exit 1
}
Print-Ok "Environment OK"

# Step 2: Prepare backend Python environment
Print-Step "Prepare Backend"
$venvDir = Join-Path $backendDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$installDeps = Join-Path $backendDir "install_deps.ps1"

if (-not (Test-Path $venvPython)) {
    Write-Host "Creating backend virtual environment..."
    python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Print-Err "Failed to create backend virtual environment"
        pause
        exit 1
    }
}

$requiredModules = @(
    "webview",
    "fastapi",
    "uvicorn",
    "sqlalchemy",
    "aiosqlite",
    "pydantic_settings",
    "openai",
    "anthropic",
    "httpx",
    "dotenv",
    "mcp",
    "chromadb",
    "transformers",
    "sentence_transformers"
)
$moduleList = ($requiredModules | ForEach-Object { "'$_'" }) -join ","
$checkCode = "import importlib.util, sys; mods=[$moduleList]; missing=[m for m in mods if importlib.util.find_spec(m) is None]; print(','.join(missing)); sys.exit(1 if missing else 0)"
$missingModules = (& $venvPython -c $checkCode 2>$null)
$needBackendInstall = $LASTEXITCODE -ne 0

if ($needBackendInstall) {
    if ($missingModules) {
        Write-Host ("Missing backend modules: " + $missingModules) -ForegroundColor Yellow
    }
    Write-Host "Installing backend dependencies..."
    if (-not (Test-Path $installDeps)) {
        Print-Err "Missing backend/install_deps.ps1"
        pause
        exit 1
    }

    Set-Location $backendDir
    & powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File $installDeps
    if ($LASTEXITCODE -ne 0) {
        Print-Err "Backend dependency installation failed"
        pause
        exit 1
    }
    Set-Location $scriptDir

    $missingModules = (& $venvPython -c $checkCode 2>$null)
    if ($LASTEXITCODE -ne 0) {
        Print-Err ("Backend dependency check failed: " + $missingModules)
        pause
        exit 1
    }
}

Print-Ok "Backend environment OK"

# Step 3: Build frontend
Print-Step "Build Frontend"

if (-not (Test-Path (Join-Path $frontendDir "node_modules"))) {
    Write-Host "Installing frontend dependencies..."
    Set-Location $frontendDir
    npm install
    if ($LASTEXITCODE -ne 0) {
        Print-Err "npm install failed"
        pause
        exit 1
    }
}

$needBuild = $true
if (Test-Path $indexFile) {
    $srcDir = Join-Path $frontendDir "src"
    $srcMtime = (Get-ChildItem -Path $srcDir -Recurse | Sort-Object LastWriteTime -Descending | Select-Object -First 1).LastWriteTime
    $buildMtime = (Get-Item $indexFile).LastWriteTime
    if ($srcMtime -lt $buildMtime) {
        Print-Ok "Frontend is up-to-date, skipping build"
        $needBuild = $false
    }
}

if ($needBuild) {
    Write-Host "Building frontend..."
    Set-Location $frontendDir
    npm run build
    if ($LASTEXITCODE -ne 0) {
        Print-Err "Frontend build failed"
        pause
        exit 1
    }
    Print-Ok "Frontend build complete"
}

Set-Location $scriptDir

# Step 4: Start app (use pythonw to avoid keeping a terminal window)
Print-Step "Starting App"
Set-Location $backendDir

$venvPythonW = Join-Path $backendDir ".venv\Scripts\pythonw.exe"
$venvPython  = Join-Path $backendDir ".venv\Scripts\python.exe"
$startScript = Join-Path $backendDir "start_app.py"
$logDir = Join-Path $backendDir "logs"
$startupOut = Join-Path $logDir "launcher-startup.out.log"
$startupErr = Join-Path $logDir "launcher-startup.err.log"
$startupFatal = Join-Path $logDir "startup_error.log"

if (-not (Test-Path $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

Remove-Item $startupOut, $startupErr, $startupFatal -Force -ErrorAction SilentlyContinue

function Show-StartupFailure($proc) {
    Print-Err "App process exited immediately. Startup failed."
    if ($proc -and $null -ne $proc.ExitCode) {
        Write-Host ("Exit code: " + $proc.ExitCode) -ForegroundColor Yellow
    }

    if (Test-Path $startupErr) {
        $errText = (Get-Content $startupErr -Raw).Trim()
        if ($errText) {
            Write-Host "`n--- launcher-startup.err.log ---" -ForegroundColor Yellow
            Write-Host $errText
        }
    }

    if (Test-Path $startupFatal) {
        $fatalText = (Get-Content $startupFatal -Raw).Trim()
        if ($fatalText) {
            Write-Host "`n--- startup_error.log ---" -ForegroundColor Yellow
            Write-Host $fatalText
        }
    }

    Write-Host "`nCheck logs:" -ForegroundColor Yellow
    Write-Host "  $startupErr"
    Write-Host "  $startupFatal"
    pause
    exit 1
}

$proc = $null

if (Test-Path $venvPython) {
    Print-Ok "Launching app..."
    $proc = Start-Process -FilePath $venvPython -ArgumentList $startScript -WorkingDirectory $backendDir -WindowStyle Hidden -RedirectStandardOutput $startupOut -RedirectStandardError $startupErr -PassThru
} elseif (Test-Path $venvPythonW) {
    Print-Ok "Launching app (windowless)..."
    $proc = Start-Process -FilePath $venvPythonW -ArgumentList $startScript -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru
} else {
    $python = Get-Command "python" -ErrorAction SilentlyContinue
    if ($python) {
        $proc = Start-Process -FilePath "python" -ArgumentList $startScript -WorkingDirectory $backendDir -WindowStyle Hidden -RedirectStandardOutput $startupOut -RedirectStandardError $startupErr -PassThru
    } else {
        $pythonW = Get-Command "pythonw" -ErrorAction SilentlyContinue
        if ($pythonW) {
            $proc = Start-Process -FilePath "pythonw" -ArgumentList $startScript -WorkingDirectory $backendDir -WindowStyle Hidden -PassThru
        } else {
            Print-Err "Python executable not found"
            pause
            exit 1
        }
    }
}

Start-Sleep 6
if ($proc -and $proc.HasExited) {
    Show-StartupFailure $proc
}

Write-Host ""
Print-Ok "App is still running. The app window should appear shortly."
Write-Host "This terminal will close in 3 seconds..." -ForegroundColor Gray
Start-Sleep 3
