#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")"

# Optional: override if you publish the API on another host/port.
: "${BACKEND_HEALTH_URL:=http://127.0.0.1:8000/health}"
: "${BACKEND_HEALTH_INTERVAL:=2}"
: "${BACKEND_HEALTH_RETRIES:=45}"
: "${POSTGRES_USER:=crm_user}"
: "${POSTGRES_DB:=crm_db}"

if [ -f .env ] && [ -r .env ]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

docker compose down

echo "==> Starting Postgres and Redis…"
docker compose up -d db redis

echo "==> Waiting for Postgres (pg_isready)…"
ok_pg=0
for _ in $(seq 1 60); do
  if docker compose exec -T db pg_isready -q -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" 2>/dev/null; then
    ok_pg=1
    break
  fi
  sleep 1
done
if [ "${ok_pg}" != 1 ]; then
  echo "Timeout: Postgres did not become ready. Try: docker compose logs db --tail=80"
  exit 1
fi

echo "==> Running Alembic before backend (avoids crash-loop when schema lags code)…"
docker compose run --build --rm --no-deps backend alembic upgrade head

echo "==> Starting full stack…"
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
for _ in $(seq 1 "${BACKEND_HEALTH_RETRIES}"); do
  if _http_probe "${BACKEND_HEALTH_URL}"; then
    ok=1
    break
  fi
  sleep "${BACKEND_HEALTH_INTERVAL}"
done
if [ "${ok}" != 1 ]; then
  echo ""
  echo "Timeout: backend did not respond at ${BACKEND_HEALTH_URL}"
  echo "Container status:"
  docker compose ps backend 2>/dev/null || true
  echo ""
  echo "Alembic revision in DB (run on host for diagnosis):"
  echo "  docker compose run --rm --no-deps backend alembic current"
  echo ""
  echo "Last 120 lines from backend (full command):"
  echo "  docker compose logs backend --tail=120"
  echo ""
  docker compose logs backend --tail=120 2>/dev/null || true
  exit 1
fi

echo "==> Done. Open http://127.0.0.1:3002"
echo "    Logs: docker compose logs backend --tail=80"
