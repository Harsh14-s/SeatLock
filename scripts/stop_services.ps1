# scripts/stop_services.ps1
$ErrorActionPreference = "SilentlyContinue"

$baseDir = Split-Path -Parent $PSScriptRoot
$binDir = Join-Path $baseDir ".bin"
$pgBin = Join-Path $binDir "pgsql\bin"
$pgData = Join-Path $binDir "pgsql\data"

Write-Host "🛑 Stopping local PostgreSQL..." -ForegroundColor Yellow
& (Join-Path $pgBin "pg_ctl.exe") -D $pgData stop

Write-Host "🛑 Stopping local Redis..." -ForegroundColor Yellow
Stop-Process -Name "redis-server" -Force

Write-Host "✅ All services stopped." -ForegroundColor Green
