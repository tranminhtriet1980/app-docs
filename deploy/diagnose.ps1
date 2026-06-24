#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Test-Path ".env.production")) {
    Write-Host "Thieu .env.production" -ForegroundColor Red
    exit 1
}

$dc = @("compose", "-f", "docker-compose.prod.yml", "--env-file", ".env.production")

Write-Host "`n=== docker compose ps ===" -ForegroundColor Cyan
docker @dc ps

Write-Host "`n=== backend (80 dong cuoi) ===" -ForegroundColor Cyan
docker @dc logs backend --tail 80

Write-Host "`n=== caddy (80 dong cuoi) ===" -ForegroundColor Cyan
docker @dc logs caddy --tail 80

Write-Host "`n=== postgres (20 dong cuoi) ===" -ForegroundColor Cyan
docker @dc logs postgres --tail 20

Write-Host "`n=== test backend trong mang docker ===" -ForegroundColor Cyan
docker @dc exec backend python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health').read().decode())" 2>&1

Write-Host "`n=== file Caddyfile ton tai? ===" -ForegroundColor Cyan
if (Test-Path "deploy\Caddyfile") { Write-Host "OK: deploy\Caddyfile" -ForegroundColor Green }
else { Write-Host "THIEU deploy\Caddyfile" -ForegroundColor Red }

Write-Host "`nNeu backend loi mat khau DB: docker compose ... down -v  (XOA DB cu) roi up lai" -ForegroundColor Yellow
