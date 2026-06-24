#!/bin/sh
set -eu

DOMAIN="${DOMAIN:-localhost}"
ACME_EMAIL="${ACME_EMAIL:-}"
TLS_MODE="${TLS_MODE:-internal}"
HTTPS_PORT="${HTTPS_PORT:-443}"

TLS_BLOCK=""
case "$TLS_MODE" in
  internal)
    TLS_BLOCK="tls internal"
    ;;
  custom)
    if [ ! -f /certs/fullchain.pem ] || [ ! -f /certs/privkey.pem ]; then
      echo "TLS_MODE=custom requires /certs/fullchain.pem and /certs/privkey.pem" >&2
      exit 1
    fi
    TLS_BLOCK="tls /certs/fullchain.pem /certs/privkey.pem"
    ;;
  auto)
    if [ -n "$ACME_EMAIL" ]; then
      TLS_BLOCK=""
    else
      echo "TLS_MODE=auto requires ACME_EMAIL" >&2
      exit 1
    fi
    ;;
  *)
    echo "Unknown TLS_MODE: $TLS_MODE (use internal, auto, or custom)" >&2
    exit 1
    ;;
esac

GLOBAL_OPTS=""
if [ -n "$ACME_EMAIL" ] && [ "$TLS_MODE" = "auto" ]; then
  GLOBAL_OPTS="email ${ACME_EMAIL}"
fi

cat > /etc/caddy/Caddyfile.generated <<EOF
{
  ${GLOBAL_OPTS}
  admin off
}

${DOMAIN}:${HTTPS_PORT} {
  ${TLS_BLOCK}

  @api path /api/*
  handle @api {
    reverse_proxy backend:8000
  }

  @backend_misc path /health /docs /docs/* /openapi.json /redoc /redoc/*
  handle @backend_misc {
    reverse_proxy backend:8000
  }

  handle {
    reverse_proxy frontend:3000
  }
}
EOF

echo "=== Caddy config (${TLS_MODE}, ${DOMAIN}:${HTTPS_PORT}) ==="
cat /etc/caddy/Caddyfile.generated

exec caddy run --config /etc/caddy/Caddyfile.generated --adapter caddyfile
