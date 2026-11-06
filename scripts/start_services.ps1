# scripts/start_services.ps1
$ErrorActionPreference = "Continue"

$baseDir = Split-Path -Parent $PSScriptRoot
$binDir = Join-Path $baseDir ".bin"
$pgBin = Join-Path $binDir "pgsql\bin"
$pgData = Join-Path $binDir "pgsql\data"
$redisDir = Join-Path $binDir "redis"

Write-Host "Starting local PostgreSQL 16..." -ForegroundColor Cyan
& (Join-Path $pgBin "pg_ctl.exe") -D $pgData -l (Join-Path $pgData "pg.log") -o "-p 5432" start

Start-Sleep -Seconds 2

# Check if seatlock database exists, create if not
$dbList = & (Join-Path $pgBin "psql.exe") -U postgres -p 5432 -t -A -c "SELECT 1 FROM pg_database WHERE datname='seatlock'"
if ($dbList -ne "1") {
    Write-Host "Creating 'seatlock' database..." -ForegroundColor Yellow
    & (Join-Path $pgBin "createdb.exe") -U postgres -p 5432 seatlock
}

Write-Host "Starting local Redis..." -ForegroundColor Cyan
$redisProc = Get-Process -Name "redis-server" -ErrorAction SilentlyContinue
if (-not $redisProc) {
    Start-Process -FilePath (Join-Path $redisDir "redis-server.exe") -WindowStyle Hidden
}

Write-Host "PostgreSQL (Port 5432) and Redis (Port 6379) are running!" -ForegroundColor Green
