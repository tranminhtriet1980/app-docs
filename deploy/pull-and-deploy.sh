#!/bin/sh
# Kéo code từ GitHub và build lại Docker production.
# Usage: ./deploy/pull-and-deploy.sh [branch] [service]
set -eu
cd "$(dirname "$0")/.."

BRANCH="${1:-main}"
SERVICE="${2:-}"

if [ ! -f .env.production ]; then
  echo "Thiếu .env.production"
  exit 1
fi

if [ ! -d .git ]; then
  echo "Chưa phải git repo — clone trước."
  exit 1
fi

git fetch origin
git checkout "$BRANCH"
git pull origin "$BRANCH"

if [ -n "$SERVICE" ]; then
  docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build "$SERVICE"
else
  docker compose -f docker-compose.prod.yml --env-file .env.production up -d --build
fi

echo "Deploy xong. curl -k https://localhost:2026/health"
