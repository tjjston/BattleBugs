#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

echo "==> Taking down old container..."
docker compose down

echo "==> Building new image (no cache)..."
docker compose build --no-cache

echo "==> Running database migrations..."
docker compose run --rm web flask db upgrade

echo "==> Starting container..."
docker compose up -d

echo "==> Tailing logs (Ctrl-C to stop following)..."
docker compose logs -f
