#!/bin/sh
set -eu
cd "$(dirname "$0")/.."

if [ ! -f .env.production ]; then
  echo "Thiếu file .env.production"
  echo "Chạy: cp .env.production.example .env.production && nano .env.production"
  exit 1
fi

docker compose -f docker-compose.prod.yml --env-file .env.production "$@"
