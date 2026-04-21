#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

docker compose down
docker compose up -d --force-recreate --remove-orphans --build

echo "http://127.0.0.1:3002  (API http://127.0.0.1:8000/health)"
