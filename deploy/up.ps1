#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Test-Path ".env.production")) {
    Write-Host "Thiếu file .env.production"
    Write-Host "Chạy: copy .env.production.example .env.production"
    exit 1
}

$argsList = @("-f", "docker-compose.prod.yml", "--env-file", ".env.production") + $args
& docker compose @argsList
