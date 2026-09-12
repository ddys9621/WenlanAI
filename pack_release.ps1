# WenlanAI Release Packaging Script
# Usage: .\pack_release.ps1

$ErrorActionPreference = "Stop"

# Version (modify as needed)
$VERSION = "1.0.0"
$RELEASE_NAME = "WenlanAI-v$VERSION"
$RELEASE_DIR = "release\$RELEASE_NAME"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  WenlanAI Release Packager" -ForegroundColor Cyan
Write-Host "  Version: $VERSION" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# Clean old release directory
if (Test-Path "release") {
    Write-Host "`n[1/6] Cleaning old release directory..." -ForegroundColor Yellow
    Remove-Item -Recurse -Force "release"
}

# Create release directory structure
Write-Host "`n[2/6] Creating release directory structure..." -ForegroundColor Yellow
New-Item -ItemType Directory -Force -Path $RELEASE_DIR | Out-Null
New-Item -ItemType Directory -Force -Path "$RELEASE_DIR\backend" | Out-Null
New-Item -ItemType Directory -Force -Path "$RELEASE_DIR\frontend" | Out-Null
New-Item -ItemType Directory -Force -Path "$RELEASE_DIR\docs" | Out-Null
New-Item -ItemType Directory -Force -Path "$RELEASE_DIR\secrets" | Out-Null

# Copy root directory files
Write-Host "`n[3/6] Copying root files..." -ForegroundColor Yellow
$rootFiles = @(
    "README.md",
    "LICENSE",
    "Dockerfile",
    "docker-compose.yml",
    "docker-compose.prod.yml",
    ".env.example",
    "deploy.ps1",
    "deploy.sh",
    "config.ini.template"
)
foreach ($file in $rootFiles) {
    if (Test-Path $file) {
        Copy-Item $file "$RELEASE_DIR\" -Force
        Write-Host "  + $file" -ForegroundColor Green
    }
}

# Copy docs
if (Test-Path "docs") {
    Copy-Item -Recurse "docs\*" "$RELEASE_DIR\docs\" -Force
    Write-Host "  + docs\" -ForegroundColor Green
}

# Copy secrets template docs
if (Test-Path "secrets\README.md") {
    Copy-Item "secrets\README.md" "$RELEASE_DIR\secrets\" -Force
    Write-Host "  + secrets\README.md" -ForegroundColor Green
}

# Copy backend files (excluding unnecessary files)
Write-Host "`n[4/6] Copying backend files..." -ForegroundColor Yellow

# Copy backend app directory
Copy-Item -Recurse "backend\app" "$RELEASE_DIR\backend\" -Force
# Remove __pycache__ directories
Get-ChildItem -Path "$RELEASE_DIR\backend" -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

# Copy other necessary backend files
$backendFiles = @(
    "backend\requirements.txt",
    "backend\requirements_utf8.txt",
    "backend\start_app.py",
    "backend\config_loader.py",
    "backend\start_backend.ps1",
    "backend\install_deps.ps1",
    "backend\build_exe.ps1",
    "backend\mumuai.spec",
    "backend\readme.txt"
)
foreach ($file in $backendFiles) {
    if (Test-Path $file) {
        Copy-Item $file "$RELEASE_DIR\backend\" -Force
        Write-Host "  + $file" -ForegroundColor Green
    }
}

# Copy backend scripts directory
if (Test-Path "backend\scripts") {
    New-Item -ItemType Directory -Force -Path "$RELEASE_DIR\backend\scripts" | Out-Null
    Copy-Item -Recurse "backend\scripts\*" "$RELEASE_DIR\backend\scripts\" -Force
    Write-Host "  + backend\scripts\" -ForegroundColor Green
}

# 复制后端docs目录
if (Test-Path "backend\docs") {
    New-Item -ItemType Directory -Force -Path "$RELEASE_DIR\backend\docs" | Out-Null
    Copy-Item -Recurse "backend\docs\*" "$RELEASE_DIR\backend\docs\" -Force
    Write-Host "  + backend\docs\" -ForegroundColor Green
}

# Create empty data and logs directories
$dataDir = "$RELEASE_DIR\backend\data"
$logsDir = "$RELEASE_DIR\backend\logs"
if (-not (Test-Path $dataDir)) {
    New-Item -ItemType Directory -Force -Path $dataDir | Out-Null
}
if (-not (Test-Path $logsDir)) {
    New-Item -ItemType Directory -Force -Path $logsDir | Out-Null
}
New-Item -ItemType File -Force -Path "$dataDir\.gitkeep" | Out-Null
New-Item -ItemType File -Force -Path "$logsDir\.gitkeep" | Out-Null
Write-Host "  + backend\data\" -ForegroundColor Green
Write-Host "  + backend\logs\" -ForegroundColor Green

# 复制前端文件（排除node_modules和构建产物）
Write-Host "`n[5/6] 复制前端文件..." -ForegroundColor Yellow
$frontendFiles = @(
    "frontend\package.json",
    "frontend\package-lock.json",
    "frontend\vite.config.ts",
    "frontend\tsconfig.json",
    "frontend\tsconfig.app.json",
    "frontend\tsconfig.node.json",
    "frontend\eslint.config.js",
    "frontend\index.html",
    "frontend\README.md",
    "frontend\start_frontend.ps1"
)
foreach ($file in $frontendFiles) {
    if (Test-Path $file) {
        Copy-Item $file "$RELEASE_DIR\frontend\" -Force
        Write-Host "  + $file" -ForegroundColor Green
    }
}

# 复制前端src和public目录
Copy-Item -Recurse "frontend\src" "$RELEASE_DIR\frontend\" -Force
Write-Host "  + frontend\src\" -ForegroundColor Green
Copy-Item -Recurse "frontend\public" "$RELEASE_DIR\frontend\" -Force
Write-Host "  + frontend\public\" -ForegroundColor Green

# 创建压缩包
Write-Host "`n[6/6] 创建压缩包..." -ForegroundColor Yellow
$zipPath = "release\$RELEASE_NAME.zip"
if (Test-Path $zipPath) {
    Remove-Item $zipPath -Force
}
Compress-Archive -Path $RELEASE_DIR -DestinationPath $zipPath -CompressionLevel Optimal
Write-Host "  + $zipPath" -ForegroundColor Green

# 计算文件大小
$zipSize = (Get-Item $zipPath).Length / 1MB
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "  Done!" -ForegroundColor Green
Write-Host "  Output: $zipPath" -ForegroundColor Cyan
Write-Host "  Size: $([math]::Round($zipSize, 2)) MB" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

Write-Host "`nNotes:" -ForegroundColor Yellow
Write-Host "1. Users need to download embedding model files" -ForegroundColor White
Write-Host "2. Copy config.ini.template to config.ini and configure" -ForegroundColor White
Write-Host "3. Frontend: run npm install" -ForegroundColor White
Write-Host "4. Backend: run pip install -r requirements.txt" -ForegroundColor White

