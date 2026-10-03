#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_HOST="${WEB_HOST:-127.0.0.1}"
BACKEND_PORT="${WEB_PORT:-8000}"
FRONTEND_HOST="${VITE_HOST:-127.0.0.1}"
FRONTEND_PORT="${VITE_PORT:-5173}"
BACKEND_URL="http://${BACKEND_HOST}:${BACKEND_PORT}"
FRONTEND_URL="http://${FRONTEND_HOST}:${FRONTEND_PORT}"
BROWSER_URL="${FRONTEND_URL}/?run=$(date +%s)"
LOG_DIR="${TMPDIR:-/tmp}/cloud-diagram-compiler-${USER:-user}"
BACKEND_LOG="${LOG_DIR}/backend.log"
FRONTEND_LOG="${LOG_DIR}/frontend.log"

backend_pid=""
frontend_pid=""
cleaned_up=0

log() {
  printf '[run] %s\n' "$*"
}

fail() {
  printf '[run] ERROR: %s\n' "$*" >&2
  exit 1
}

cleanup() {
  if [[ "$cleaned_up" -eq 1 ]]; then
    return
  fi
  cleaned_up=1

  log "Stopping services..."
  if [[ -n "$frontend_pid" ]] && kill -0 "$frontend_pid" 2>/dev/null; then
    kill "$frontend_pid" 2>/dev/null || true
  fi
  if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill "$backend_pid" 2>/dev/null || true
  fi

  wait "$frontend_pid" 2>/dev/null || true
  wait "$backend_pid" 2>/dev/null || true
  log "Services stopped. Logs: ${LOG_DIR}"
}

trap cleanup EXIT INT TERM

command -v python3.12 >/dev/null 2>&1 || fail "python3.12 is required but was not found on PATH"
command -v npm >/dev/null 2>&1 || fail "npm is required but was not found on PATH"
command -v curl >/dev/null 2>&1 || fail "curl is required but was not found on PATH"
[[ -d "$ROOT_DIR/web/node_modules" ]] || fail "Frontend dependencies are missing. Run: cd web && npm install"

mkdir -p "$LOG_DIR"
: > "$BACKEND_LOG"
: > "$FRONTEND_LOG"

log "Starting backend at ${BACKEND_URL}"
(
  cd "$ROOT_DIR"
  PYTHONPATH="$ROOT_DIR/src${PYTHONPATH:+:${PYTHONPATH}}" \
    python3.12 -m uvicorn cloud_diagram.web.app:app \
    --host "$BACKEND_HOST" \
    --port "$BACKEND_PORT"
) >"$BACKEND_LOG" 2>&1 &
backend_pid=$!

log "Starting frontend at ${FRONTEND_URL}"
(
  cd "$ROOT_DIR/web"
  npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
) >"$FRONTEND_LOG" 2>&1 &
frontend_pid=$!

wait_for_url() {
  local url="$1"
  local name="$2"
  local attempts=0

  while (( attempts < 60 )); do
    if ! kill -0 "$backend_pid" 2>/dev/null && [[ "$name" == "backend" ]]; then
      tail -n 30 "$BACKEND_LOG" >&2 || true
      fail "Backend exited before becoming ready"
    fi
    if ! kill -0 "$frontend_pid" 2>/dev/null && [[ "$name" == "frontend" ]]; then
      tail -n 30 "$FRONTEND_LOG" >&2 || true
      fail "Frontend exited before becoming ready"
    fi

    if curl --silent --show-error --fail --max-time 2 "$url" >/dev/null 2>&1; then
      log "${name^} is ready"
      return 0
    fi

    attempts=$((attempts + 1))
    sleep 1
  done

  tail -n 30 "$([[ "$name" == "backend" ]] && echo "$BACKEND_LOG" || echo "$FRONTEND_LOG")" >&2 || true
  fail "Timed out waiting for ${name} at ${url}"
}

wait_for_url "${BACKEND_URL}/api/health" "backend"
wait_for_url "$FRONTEND_URL" "frontend"

log "Opening ${BROWSER_URL} in the browser"
if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$BROWSER_URL" >/dev/null 2>&1 &
elif command -v gio >/dev/null 2>&1; then
  gio open "$BROWSER_URL" >/dev/null 2>&1 &
else
  log "Could not find xdg-open or gio; open ${FRONTEND_URL} manually"
fi

log "Cloud Diagram Compiler is running. Press Ctrl+C to stop both services."
while kill -0 "$backend_pid" 2>/dev/null && kill -0 "$frontend_pid" 2>/dev/null; do
  sleep 2
done

if ! kill -0 "$backend_pid" 2>/dev/null; then
  tail -n 30 "$BACKEND_LOG" >&2 || true
  fail "Backend stopped unexpectedly"
fi
if ! kill -0 "$frontend_pid" 2>/dev/null; then
  tail -n 30 "$FRONTEND_LOG" >&2 || true
  fail "Frontend stopped unexpectedly"
fi
