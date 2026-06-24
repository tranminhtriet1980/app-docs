# Tạo chứng chỉ self-signed cho TLS_MODE=custom
param(
    [string]$Domain = "localhost",
    [int]$Days = 825
)

$OutDir = Join-Path $PSScriptRoot "certs"
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$key = Join-Path $OutDir "privkey.pem"
$cert = Join-Path $OutDir "fullchain.pem"

openssl req -x509 -nodes -newkey rsa:4096 `
    -keyout $key `
    -out $cert `
    -days $Days `
    -subj "/CN=$Domain/O=ImmiPath/C=VN"

Write-Host "Created:"
Write-Host "  $cert"
Write-Host "  $key"
Write-Host ""
Write-Host "Set in .env.production:"
Write-Host "  TLS_MODE=custom"
Write-Host "  DOMAIN=$Domain"
