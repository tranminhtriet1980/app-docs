#!/bin/sh
# Tạo chứng chỉ self-signed cho TLS_MODE=custom (hoặc copy vào deploy/certs/)
set -eu

DOMAIN="${1:-localhost}"
DAYS="${2:-825}"
OUT_DIR="$(cd "$(dirname "$0")" && pwd)/certs"

mkdir -p "$OUT_DIR"

openssl req -x509 -nodes -newkey rsa:4096 \
  -keyout "$OUT_DIR/privkey.pem" \
  -out "$OUT_DIR/fullchain.pem" \
  -days "$DAYS" \
  -subj "/CN=${DOMAIN}/O=ImmiPath/C=VN"

echo "Created:"
echo "  $OUT_DIR/fullchain.pem"
echo "  $OUT_DIR/privkey.pem"
echo ""
echo "Set in .env.production:"
echo "  TLS_MODE=custom"
echo "  DOMAIN=${DOMAIN}"
