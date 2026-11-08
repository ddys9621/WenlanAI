# Install Python dependencies in batches to reduce timeout risk.
# Usage: run this script from anywhere. It always targets backend/.venv.

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$backendDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$venvDir = Join-Path $backendDir ".venv"
$venvPython = Join-Path $venvDir "Scripts\python.exe"
$constraintsFile = Join-Path $venvDir "constraints.txt"

function Run-Step($title, $packages, $timeoutSec) {
    Write-Host ""
    Write-Host $title -ForegroundColor Cyan
    & $venvPython -m pip install --default-timeout=$timeoutSec -c $constraintsFile @packages
    if ($LASTEXITCODE -ne 0) {
        throw "Install failed: $title"
    }
}

Set-Location $backendDir

Write-Host "Installing Python dependencies..." -ForegroundColor Green

if (-not (Test-Path $venvPython)) {
    Write-Host ""
    Write-Host "[0/8] Create Python virtual environment" -ForegroundColor Cyan
    python -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        throw "Failed to create Python virtual environment"
    }
}

Get-Content (Join-Path $backendDir "requirements.txt") -Encoding UTF8 |
    ForEach-Object { (($_ -replace '#.*', '') -replace '\[[^\]]*\]', '').Trim() } |
    Where-Object { $_ } |
    Set-Content -Path $constraintsFile -Encoding ASCII

Write-Host ""
Write-Host "[1/8] Upgrade pip" -ForegroundColor Cyan
& $venvPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) {
    throw "Failed to upgrade pip"
}

Run-Step "[2/8] Install web framework" @(
    "fastapi==0.121.0",
    "uvicorn[standard]==0.38.0",
    "python-multipart==0.0.20"
) 100

Run-Step "[3/8] Install database drivers" @(
    "sqlalchemy==2.0.25",
    "aiosqlite==0.20.0"
) 100

Run-Step "[4/8] Install validation and AI clients" @(
    "pydantic==2.12.4",
    "pydantic-settings==2.11.0",
    "openai==2.7.0",
    "anthropic==0.72.0"
) 100

Run-Step "[5/8] Install tools and desktop window" @(
    "httpx==0.28.1",
    "python-dotenv==1.0.0",
    "json-repair==0.59.10",
    "mcp==1.21.0",
    "pywebview==5.3.2"
) 100

Run-Step "[6/8] Install NumPy" @(
    "numpy==1.26.4"
) 100

Run-Step "[7/8] Install ChromaDB" @(
    "chromadb==1.3.2"
) 200

Run-Step "[8/8] Install Transformers" @(
    "transformers==4.57.1",
    "sentence-transformers==5.1.2"
) 200

Write-Host ""
Write-Host "All dependencies installed. Restart the launcher." -ForegroundColor Green
