# scripts/setup_services.ps1
$ErrorActionPreference = "Stop"

$baseDir = Split-Path -Parent $PSScriptRoot
$binDir = Join-Path $baseDir ".bin"
$pgDir = Join-Path $binDir "pgsql"
$redisDir = Join-Path $binDir "redis"

New-Item -ItemType Directory -Force -Path $binDir | Out-Null

# --- 1. SETUP POSTGRESQL ---
if (-not (Test-Path (Join-Path $pgDir "bin\postgres.exe"))) {
    Write-Host "[1/4] Downloading Portable PostgreSQL 16..." -ForegroundColor Cyan
    $pgZip = Join-Path $binDir "pgsql.zip"
    Invoke-WebRequest -Uri "https://get.enterprisedb.com/postgresql/postgresql-16.3-1-windows-x64-binaries.zip" -OutFile $pgZip
    
    Write-Host "[2/4] Extracting PostgreSQL..." -ForegroundColor Cyan
    Expand-Archive -Path $pgZip -DestinationPath $binDir -Force
    Remove-Item $pgZip -Force
}

$pgBin = Join-Path $pgDir "bin"
$pgData = Join-Path $pgDir "data"

if (-not (Test-Path (Join-Path $pgData "PG_VERSION"))) {
    Write-Host "[3/4] Initializing PostgreSQL cluster..." -ForegroundColor Cyan
    & (Join-Path $pgBin "initdb.exe") -D $pgData -U postgres -A trust --encoding=UTF8
}

# --- 2. SETUP REDIS ---
if (-not (Test-Path (Join-Path $redisDir "redis-server.exe"))) {
    Write-Host "[4/4] Downloading Portable Redis..." -ForegroundColor Cyan
    $redisZip = Join-Path $binDir "redis.zip"
    Invoke-WebRequest -Uri "https://github.com/tporadowski/redis/releases/download/v5.0.14.1/Redis-x64-5.0.14.1.zip" -OutFile $redisZip
    
    New-Item -ItemType Directory -Force -Path $redisDir | Out-Null
    Expand-Archive -Path $redisZip -DestinationPath $redisDir -Force
    Remove-Item $redisZip -Force
}

Write-Host "Services successfully set up in $binDir!" -ForegroundColor Green
