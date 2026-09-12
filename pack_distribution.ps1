param(
    [string]$Version = (Get-Date -Format 'yyyy.MM.dd-HHmm'),
    [switch]$SkipFrontendBuild,
    [switch]$IncludeVenv,
    [switch]$IncludeEmbedding
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$ProjectRoot = Split-Path -Parent $PSCommandPath
$FrontendDir = Join-Path $ProjectRoot 'frontend'
$BackendDir = Join-Path $ProjectRoot 'backend'
$ReleaseRoot = Join-Path $ProjectRoot 'release'
$PackageName = "WenlanAI-runtime-v$Version"
$OutputDir = Join-Path $ReleaseRoot $PackageName
$ZipPath = Join-Path $ReleaseRoot "$PackageName.zip"

function Write-Step {
    param([string]$Message)
    Write-Host "`n== $Message ==" -ForegroundColor Cyan
}

function Write-Ok {
    param([string]$Message)
    Write-Host "[OK] $Message" -ForegroundColor Green
}

function Write-Warn {
    param([string]$Message)
    Write-Host "[WARN] $Message" -ForegroundColor Yellow
}

function Assert-PathExists {
    param(
        [string]$Path,
        [string]$Description
    )

    if (-not (Test-Path $Path)) {
        throw "$Description not found: $Path"
    }
}

function Ensure-Directory {
    param([string]$Path)
    New-Item -ItemType Directory -Force -Path $Path | Out-Null
}

function Copy-TreeClean {
    param(
        [string]$Source,
        [string]$Destination
    )

    if (-not (Test-Path $Source)) {
        return
    }

    Copy-Item -Path $Source -Destination $Destination -Recurse -Force
}

function Remove-UnwantedFiles {
    param([string]$Root)

    if (-not (Test-Path $Root)) {
        return
    }

    Get-ChildItem -Path $Root -Recurse -Directory -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @('__pycache__', '.pytest_cache', 'node_modules', '.mypy_cache', '.ruff_cache') } |
        Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

    Get-ChildItem -Path $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in @('.pyc', '.pyo') -or $_.Name -like '*.log' } |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

Assert-PathExists $FrontendDir 'frontend directory'
Assert-PathExists $BackendDir 'backend directory'
Assert-PathExists (Join-Path $BackendDir 'app') 'backend/app directory'

Write-Host '========================================' -ForegroundColor Cyan
Write-Host ' WenlanAI distribution packer' -ForegroundColor Cyan
Write-Host " Version: $Version" -ForegroundColor Cyan
Write-Host " Output:  $OutputDir" -ForegroundColor Cyan
Write-Host '========================================' -ForegroundColor Cyan

if (-not $SkipFrontendBuild) {
    Write-Step 'Build frontend static assets'
    Push-Location $FrontendDir
    try {
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) {
            throw 'Frontend build failed.'
        }
    }
    finally {
        Pop-Location
    }
    Write-Ok 'Frontend build completed.'
}
else {
    Write-Step 'Skip frontend build'
    Write-Ok 'Using existing backend/static.'
}

Assert-PathExists (Join-Path $BackendDir 'static\index.html') 'backend/static build output'

Write-Step 'Clean old release output'
if (Test-Path $OutputDir) {
    Remove-Item -Recurse -Force $OutputDir
}
if (Test-Path $ZipPath) {
    Remove-Item -Force $ZipPath
}
Ensure-Directory $ReleaseRoot
Ensure-Directory $OutputDir
Ensure-Directory (Join-Path $OutputDir 'backend')
Ensure-Directory (Join-Path $OutputDir 'backend\data')
Ensure-Directory (Join-Path $OutputDir 'backend\data\chroma_db')
Ensure-Directory (Join-Path $OutputDir 'backend\logs')
Write-Ok 'Release directory created.'

Write-Step 'Copy runtime files'

$RootFiles = @(
    'README.md',
    'LICENSE',
    'config.ini.template'
)

foreach ($File in $RootFiles) {
    $Source = Join-Path $ProjectRoot $File
    if (Test-Path $Source) {
        Copy-Item -Path $Source -Destination $OutputDir -Force
        Write-Ok "Copied $File"
    }
}

$BackendFiles = @(
    'start_app.py',
    'config_loader.py',
    'requirements.txt',
    'requirements_utf8.txt',
    'readme.txt',
    '.env.example'
)

foreach ($File in $BackendFiles) {
    $Source = Join-Path $BackendDir $File
    if (Test-Path $Source) {
        Copy-Item -Path $Source -Destination (Join-Path $OutputDir 'backend') -Force
        Write-Ok "Copied backend/$File"
    }
}

Copy-TreeClean -Source (Join-Path $BackendDir 'app') -Destination (Join-Path $OutputDir 'backend')
Write-Ok 'Copied backend/app'

Copy-TreeClean -Source (Join-Path $BackendDir 'static') -Destination (Join-Path $OutputDir 'backend')
Write-Ok 'Copied backend/static'

$EmbeddingDir = Join-Path $BackendDir 'embedding'
if ($IncludeEmbedding -and (Test-Path $EmbeddingDir)) {
    Copy-TreeClean -Source $EmbeddingDir -Destination (Join-Path $OutputDir 'backend')
    Write-Ok 'Copied backend/embedding'
}
elseif ($IncludeEmbedding) {
    Write-Warn 'backend/embedding not found. First run may need model preparation.'
}
else {
    Write-Warn 'Skip backend/embedding by default. Use -IncludeEmbedding if you need offline vector models in the package.'
}

if ($IncludeVenv -and (Test-Path (Join-Path $BackendDir '.venv'))) {
    Copy-TreeClean -Source (Join-Path $BackendDir '.venv') -Destination (Join-Path $OutputDir 'backend')
    Write-Ok 'Copied backend/.venv'
}

New-Item -ItemType File -Force -Path (Join-Path $OutputDir 'backend\data\.gitkeep') | Out-Null
New-Item -ItemType File -Force -Path (Join-Path $OutputDir 'backend\data\chroma_db\.gitkeep') | Out-Null
New-Item -ItemType File -Force -Path (Join-Path $OutputDir 'backend\logs\.gitkeep') | Out-Null

Remove-UnwantedFiles -Root $OutputDir

Write-Step 'Generate launcher scripts'

$LauncherScript = @'
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$backendDir = Join-Path $scriptDir 'backend'
$configTemplate = Join-Path $scriptDir 'config.ini.template'
$configPath = Join-Path $scriptDir 'config.ini'
$startScript = Join-Path $backendDir 'start_app.py'

function Info([string]$Message) { Write-Host "[INFO] $Message" -ForegroundColor Cyan }
function Ok([string]$Message) { Write-Host "[OK] $Message" -ForegroundColor Green }
function Fail([string]$Message) { Write-Host "[ERROR] $Message" -ForegroundColor Red }

if (-not (Test-Path $backendDir)) {
    Fail 'Missing backend directory.'
    exit 1
}

if (-not (Test-Path $startScript)) {
    Fail 'Missing backend/start_app.py.'
    exit 1
}

if (-not (Test-Path $configPath) -and (Test-Path $configTemplate)) {
    Copy-Item -Path $configTemplate -Destination $configPath -Force
    Info 'Generated config.ini from config.ini.template.'
}

$pythonCandidates = @(
    (Join-Path $backendDir '.venv\Scripts\pythonw.exe'),
    (Join-Path $backendDir '.venv\Scripts\python.exe')
)

$pythonExe = $pythonCandidates | Where-Object { Test-Path $_ } | Select-Object -First 1

if (-not $pythonExe) {
    $pythonw = Get-Command pythonw -ErrorAction SilentlyContinue
    if ($pythonw) {
        $pythonExe = $pythonw.Source
    }
}

if (-not $pythonExe) {
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $pythonExe = $python.Source
    }
}

if (-not $pythonExe) {
    Fail 'Python runtime not found. Run install_deps.ps1 first.'
    exit 1
}

Push-Location $backendDir
try {
    $exeName = [System.IO.Path]::GetFileName($pythonExe).ToLowerInvariant()
    if ($exeName -eq 'pythonw.exe') {
        Start-Process -FilePath $pythonExe -ArgumentList @($startScript) -WorkingDirectory $backendDir
        Ok 'Application started in background.'
        Start-Sleep -Seconds 2
    }
    else {
        Info 'Starting application...'
        & $pythonExe $startScript
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}
'@

$StartScript = @'
$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$launcher = Join-Path $scriptDir 'launcher.ps1'
& powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File $launcher
exit $LASTEXITCODE
'@

$BatScript = @'
@echo off
powershell -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
if %errorlevel% neq 0 (
    echo.
    echo Launch failed. Check the error above.
    pause
)
'@

$InstallScript = @'
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$scriptDir = if ($PSScriptRoot) { $PSScriptRoot } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$backendDir = Join-Path $scriptDir 'backend'
$venvDir = Join-Path $backendDir '.venv'
$venvPython = Join-Path $venvDir 'Scripts\python.exe'

function Step([string]$Message) { Write-Host "`n== $Message ==" -ForegroundColor Cyan }
function Ok([string]$Message) { Write-Host "[OK] $Message" -ForegroundColor Green }

$systemPython = Get-Command python -ErrorAction SilentlyContinue
if (-not $systemPython) {
    throw 'System Python not found. Install Python 3.10+ and add it to PATH.'
}

Push-Location $backendDir
try {
    if (-not (Test-Path $venvPython)) {
        Step 'Create virtual environment'
        & $systemPython.Source -m venv .venv
        Ok 'Virtual environment created.'
    }

    Step 'Upgrade pip'
    & $venvPython -m pip install --upgrade pip

    if (Test-Path 'requirements.txt') {
        Step 'Install requirements.txt'
        & $venvPython -m pip install -r requirements.txt
    }

    if (Test-Path 'requirements_utf8.txt') {
        Step 'Install requirements_utf8.txt'
        & $venvPython -m pip install -r requirements_utf8.txt
    }

    if (-not (Test-Path '.env') -and (Test-Path '.env.example')) {
        Copy-Item -Path '.env.example' -Destination '.env' -Force
        Ok 'Generated backend/.env from backend/.env.example'
    }

    Ok 'Dependency installation completed.'
    Write-Host 'You can now run start.bat or start.ps1.' -ForegroundColor Yellow
}
finally {
    Pop-Location
}
'@

$DistReadme = @'
WenlanAI distribution package
================================

First use:
1. Run install_deps.ps1
2. Edit config.ini if needed
3. Optionally copy backend/.env.example to backend/.env and adjust values

Start:
- double click start.bat
- or run start.ps1

Included:
- backend/app runtime code
- backend/static built frontend files
- launcher.ps1 / start.ps1 / start.bat

Optional:
- backend/embedding only when pack_distribution.ps1 is run with -IncludeEmbedding

Not included:
- frontend source code
- tests, docs, node_modules, build cache
- your private config, database and secrets
'@

Set-Content -Path (Join-Path $OutputDir 'launcher.ps1') -Value $LauncherScript -Encoding UTF8
Set-Content -Path (Join-Path $OutputDir 'start.ps1') -Value $StartScript -Encoding UTF8
Set-Content -Path (Join-Path $OutputDir 'start.bat') -Value $BatScript -Encoding ASCII
Set-Content -Path (Join-Path $OutputDir 'install_deps.ps1') -Value $InstallScript -Encoding UTF8
Set-Content -Path (Join-Path $OutputDir 'README_DIST.txt') -Value $DistReadme -Encoding UTF8
Write-Ok 'Launcher scripts generated.'

Write-Step 'Create zip package'
Compress-Archive -Path $OutputDir -DestinationPath $ZipPath -Force
Write-Ok "Zip created: $ZipPath"

Write-Host "`nPackaging complete." -ForegroundColor Green
Write-Host "  Folder: $OutputDir" -ForegroundColor White
Write-Host "  Zip:    $ZipPath" -ForegroundColor White
