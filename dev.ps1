# 1 lenh: Backend + Frontend
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

Write-Host ""
Write-Host "  Immigration AI" -ForegroundColor Cyan
Write-Host "  Backend (8000) + Frontend (3000)" -ForegroundColor Gray
Write-Host ""

if (-not (Test-Path "backend\.venv\Scripts\python.exe")) {
    Write-Host "Chua cai dat. Chay: npm run setup" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path "frontend\node_modules")) {
    Write-Host "Chua cai frontend. Chay: npm run setup" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path "frontend\.env.local")) {
    Copy-Item "frontend\.env.local.example" "frontend\.env.local" -ErrorAction SilentlyContinue
}

if (-not (Test-Path "node_modules")) {
    npm install --silent
}

Write-Host "  Mo trinh duyet: http://localhost:3000" -ForegroundColor Green
Write-Host "  Dang nhap: demo@test.com / demo123" -ForegroundColor Gray
Write-Host "  Ctrl+C de dung" -ForegroundColor Gray
Write-Host ""

npm start
