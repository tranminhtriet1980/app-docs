#Requires -Version 5.1
<#
.SYNOPSIS
  Kéo code mới từ GitHub và build lại Docker (production).

.DESCRIPTION
  Chạy trên máy Docker (ví dụ C:\Docker\app docs).
  Lần đầu: clone repo rồi tạo .env.production — xem DEPLOY_GIT.md

.EXAMPLE
  .\deploy\pull-and-deploy.ps1
  .\deploy\pull-and-deploy.ps1 -Branch main
  .\deploy\pull-and-deploy.ps1 -Service frontend
#>
param(
    [string]$Branch = "main",
    [string]$Service = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

if (-not (Test-Path ".env.production")) {
    Write-Host "Thiếu .env.production — copy từ .env.production.example và sửa." -ForegroundColor Red
    exit 1
}

if (-not (Test-Path ".git")) {
    Write-Host "Thư mục chưa phải git repo. Clone trước:" -ForegroundColor Red
    Write-Host '  git clone https://github.com/tranminhtriet1980/app-docs.git "C:\Docker\app docs"'
    exit 1
}

Write-Host ">>> git fetch origin" -ForegroundColor Cyan
git fetch origin

Write-Host ">>> git checkout $Branch" -ForegroundColor Cyan
git checkout $Branch

Write-Host ">>> git pull origin $Branch" -ForegroundColor Cyan
git pull origin $Branch

$composeArgs = @("-f", "docker-compose.prod.yml", "--env-file", ".env.production", "up", "-d", "--build")
if ($Service) {
    $composeArgs += $Service
}

Write-Host ">>> docker compose $($composeArgs -join ' ')" -ForegroundColor Cyan
& docker compose @composeArgs

Write-Host ""
Write-Host "Deploy xong. Kiểm tra:" -ForegroundColor Green
Write-Host "  .\deploy\up.ps1 ps"
Write-Host "  curl.exe -k https://localhost:2026/health"
