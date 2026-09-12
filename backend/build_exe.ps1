# build_exe.ps1 - WenlanAI Auto Build Script
# Usage: Run .\build_exe.ps1 in backend directory

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  WenlanAI Auto Build Script" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Record start time
$startTime = Get-Date

# Step 1: Clean old frontend build files
Write-Host "[1/5] Cleaning old frontend files..." -ForegroundColor Yellow
if (Test-Path "static/assets") {
    $oldFiles = Get-ChildItem -Path "static/assets" -File
    if ($oldFiles.Count -gt 0) {
        Remove-Item -Path "static/assets/*" -Recurse -Force -ErrorAction SilentlyContinue
        Write-Host "  Done: Cleaned $($oldFiles.Count) old files" -ForegroundColor Green
    } else {
        Write-Host "  Done: assets directory is empty" -ForegroundColor Green
    }
} else {
    Write-Host "  Done: assets directory not found, skip" -ForegroundColor Green
}

# Step 2: Rebuild frontend
Write-Host ""
Write-Host "[2/5] Building frontend..." -ForegroundColor Yellow
$frontendPath = Join-Path $PSScriptRoot "..\frontend"
if (Test-Path $frontendPath) {
    Push-Location $frontendPath
    try {
        npm run build
        if ($LASTEXITCODE -ne 0) {
            throw "Frontend build failed"
        }
        Write-Host "  Done: Frontend build complete" -ForegroundColor Green
    } finally {
        Pop-Location
    }
} else {
    throw "Frontend directory not found: $frontendPath"
}

# Step 3: Clean old package directories
Write-Host ""
Write-Host "[3/5] Cleaning old package directories..." -ForegroundColor Yellow
if (Test-Path "dist") {
    Remove-Item -Path "dist" -Recurse -Force
    Write-Host "  Done: Cleaned dist/" -ForegroundColor Green
} else {
    Write-Host "  Done: dist directory not found, skip" -ForegroundColor Green
}

if (Test-Path "build") {
    Remove-Item -Path "build" -Recurse -Force
    Write-Host "  Done: Cleaned build/" -ForegroundColor Green
} else {
    Write-Host "  Done: build directory not found, skip" -ForegroundColor Green
}

# Step 4: Run PyInstaller
Write-Host ""
Write-Host "[4/5] Running PyInstaller..." -ForegroundColor Yellow
Write-Host "  (This may take a few minutes...)" -ForegroundColor Gray
pyinstaller mumuai.spec --clean
if ($LASTEXITCODE -ne 0) {
    throw "PyInstaller failed"
}
Write-Host "  Done: PyInstaller complete" -ForegroundColor Green

# Step 5: Complete
$endTime = Get-Date
$duration = $endTime - $startTime

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "[5/5] Build Complete!" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  Output: dist\WenlanAI\" -ForegroundColor White
Write-Host "  Executable: dist\WenlanAI\WenlanAI.exe" -ForegroundColor White
Write-Host "  Duration: $($duration.Minutes)m $($duration.Seconds)s" -ForegroundColor White
Write-Host ""
