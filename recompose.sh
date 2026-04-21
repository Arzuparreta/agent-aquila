#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Optional: override if you publish the API on another host/port.
: "${BACKEND_HEALTH_URL:=http://127.0.0.1:8000/health}"

docker compose down
docker compose up -d --force-recreate --remove-orphans --build

echo "==> Waiting for API (${BACKEND_HEALTH_URL})…"
_http_probe() {
  if command -v curl >/dev/null 2>&1; then
    curl -sf "$1" >/dev/null
  elif command -v wget >/dev/null 2>&1; then
    wget -q -O /dev/null "$1"
  else
    echo "Install curl or wget to wait for health checks, or hit the API once it is up."
    return 1
  fi
}

ok=0
for _ in $(seq 1 45); do
  if _http_probe "${BACKEND_HEALTH_URL}"; then
    ok=1
    break
  fi
  sleep 2
done
if [ "${ok}" != 1 ]; then
  echo "Timeout: backend did not become healthy. Check: docker compose logs backend --tail=120"
  exit 1
fi

echo "==> Applying Alembic migrations (idempotent; same as backend startup)…"
docker compose exec -T backend alembic upgrade head

echo "==> Done. Open http://127.0.0.1:3002"
echo "    Logs: docker compose logs backend --tail=80"
