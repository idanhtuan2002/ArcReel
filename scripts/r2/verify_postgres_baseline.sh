#!/usr/bin/env bash
set -Eeuo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$REPO"

R2_PG_PORT="${R2_PG_PORT:-55433}"
R2_BACKEND_PORT="${R2_BACKEND_PORT:-12419}"
PG_CONTAINER="${R2_PG_CONTAINER:-r2-m0-postgres}"
PG_USER="${R2_PG_USER:-arcreel}"
PG_PASSWORD="${R2_PG_PASSWORD:-r2-m0-local-only}"
PG_DB="${R2_PG_DB:-arcreel_r2_m0}"
PG_LABEL="com.content-production-os.r2-m0=1"

RUN_DIR="${R2_M0_RUN_DIR:-${HOME}/content-production-os-r2-m0-runtime}"
DATA_DIR="${RUN_DIR}/data"
LOG_DIR="${RUN_DIR}/logs"
BACKEND_LOG="${RUN_DIR}/backend.log"
BACKEND_PID=""

log(){ printf '[%s] %s\n' "$(date -Is)" "$*"; }
die(){ printf 'ERROR: %s\n' "$*" >&2; exit 1; }

cleanup() {
  set +e
  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID" 2>/dev/null
    wait "$BACKEND_PID" 2>/dev/null
  fi
  if docker inspect "$PG_CONTAINER" >/dev/null 2>&1; then
    LABEL="$(docker inspect -f '{{ index .Config.Labels "com.content-production-os.r2-m0" }}' "$PG_CONTAINER" 2>/dev/null)"
    if [[ "$LABEL" == "1" ]]; then
      docker rm -f "$PG_CONTAINER" >/dev/null 2>&1
    fi
  fi
}
trap cleanup EXIT

port_in_use() {
  local port="$1"
  ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)$port$"
}

start_backend() {
  : > "$BACKEND_LOG"
  DATABASE_URL="$DATABASE_URL" \
  ARCREEL_DATA_DIR="$DATA_DIR" \
  ARCREEL_LOG_DIR="$LOG_DIR" \
  ARCREEL_LOG_FILE_DISABLED=1 \
  AUTH_PASSWORD="r2-m0-local-only" \
  uv run uvicorn server.app:app \
    --host 127.0.0.1 \
    --port "$R2_BACKEND_PORT" \
    >"$BACKEND_LOG" 2>&1 &
  BACKEND_PID=$!
}

wait_backend() {
  local i
  for i in $(seq 1 60); do
    if curl -fsS "http://127.0.0.1:${R2_BACKEND_PORT}/health" \
      > "${RUN_DIR}/health.json" 2>/dev/null; then
      python - "${RUN_DIR}/health.json" <<'PY'
import json, sys
data = json.load(open(sys.argv[1], encoding="utf-8"))
if data.get("status") != "ok":
    raise SystemExit(f"unexpected health payload: {data}")
PY
      return 0
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      echo "===== backend log =====" >&2
      cat "$BACKEND_LOG" >&2
      return 1
    fi
    sleep 1
  done
  echo "===== backend log (timeout) =====" >&2
  cat "$BACKEND_LOG" >&2
  return 1
}

stop_backend() {
  if [[ -n "${BACKEND_PID:-}" ]] && kill -0 "$BACKEND_PID" 2>/dev/null; then
    kill "$BACKEND_PID"
    wait "$BACKEND_PID" || true
  fi
  BACKEND_PID=""
}

command -v docker >/dev/null || die "docker missing"
command -v uv >/dev/null || die "uv missing"
command -v curl >/dev/null || die "curl missing"
command -v ss >/dev/null || die "ss missing"

mkdir -p "$DATA_DIR" "$LOG_DIR"

if port_in_use "$R2_PG_PORT"; then
  die "PostgreSQL verification port already in use: $R2_PG_PORT"
fi
if port_in_use "$R2_BACKEND_PORT"; then
  die "Backend verification port already in use: $R2_BACKEND_PORT"
fi

if docker inspect "$PG_CONTAINER" >/dev/null 2>&1; then
  EXISTING_LABEL="$(docker inspect -f '{{ index .Config.Labels "com.content-production-os.r2-m0" }}' "$PG_CONTAINER" 2>/dev/null)"
  [[ "$EXISTING_LABEL" == "1" ]] || \
    die "Container $PG_CONTAINER exists but is not owned by R2-M0"
  docker rm -f "$PG_CONTAINER" >/dev/null
fi

log "Starting isolated PostgreSQL 16"
docker run -d --rm \
  --name "$PG_CONTAINER" \
  --label "$PG_LABEL" \
  -e POSTGRES_USER="$PG_USER" \
  -e POSTGRES_PASSWORD="$PG_PASSWORD" \
  -e POSTGRES_DB="$PG_DB" \
  -p "127.0.0.1:${R2_PG_PORT}:5432" \
  postgres:16-alpine >/dev/null

for _ in $(seq 1 60); do
  if docker exec "$PG_CONTAINER" pg_isready -U "$PG_USER" -d "$PG_DB" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$PG_CONTAINER" pg_isready -U "$PG_USER" -d "$PG_DB" >/dev/null 2>&1 \
  || die "PostgreSQL did not become ready"

DATABASE_URL="postgresql+asyncpg://${PG_USER}:${PG_PASSWORD}@127.0.0.1:${R2_PG_PORT}/${PG_DB}"
export DATABASE_URL

log "Running Alembic PostgreSQL migration"
uv run alembic upgrade head

CURRENT="$(uv run alembic current)"
HEADS="$(uv run alembic heads)"
printf '%s\n' "$CURRENT" > "${RUN_DIR}/alembic-current.txt"
printf '%s\n' "$HEADS" > "${RUN_DIR}/alembic-heads.txt"

HEAD_REV="$(printf '%s\n' "$HEADS" | awk 'NF {print $1; exit}')"
[[ -n "$HEAD_REV" ]] || die "Could not determine Alembic head"
printf '%s\n' "$CURRENT" | grep -q "$HEAD_REV" \
  || die "Alembic current is not at head: current=$CURRENT head=$HEAD_REV"
log "Alembic head verified: $HEAD_REV"

log "Starting backend against isolated PostgreSQL"
start_backend
wait_backend || die "Backend initial health failed"
log "backend initial health: PASS"

log "Restarting backend against same PostgreSQL and data directory"
stop_backend
sleep 1
start_backend
wait_backend || die "Backend restart health failed"
log "backend restart health: PASS"

echo
echo "===== HEALTH ====="
cat "${RUN_DIR}/health.json"
echo
echo "===== ALEMBIC CURRENT ====="
cat "${RUN_DIR}/alembic-current.txt"
echo
echo "===== ALEMBIC HEADS ====="
cat "${RUN_DIR}/alembic-heads.txt"
echo
echo "R2-M0 PostgreSQL baseline verification: PASS"
