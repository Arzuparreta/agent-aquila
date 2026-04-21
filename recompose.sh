#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

docker compose down
docker compose up -d --force-recreate --remove-orphans --build

echo "Waiting for backend to be running..."
for _ in {1..60}; do
  if [ "$(docker compose ps -q backend | xargs -r docker inspect -f '{{.State.Running}}' 2>/dev/null || true)" = "true" ]; then
    break
  fi
  sleep 1
done

echo "Running database migrations (alembic upgrade head)..."
docker compose exec -T backend alembic upgrade head

echo "http://127.0.0.1:3002  (API http://127.0.0.1:8000/health)"
