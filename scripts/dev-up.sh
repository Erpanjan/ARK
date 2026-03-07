#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/.logs"
mkdir -p "$LOG_DIR"

if [[ -f "$ROOT_DIR/.env" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_DIR/.env"
  set +a
fi

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing required command: $1" >&2
    exit 1
  fi
}

require_cmd python3
require_cmd pnpm
require_cmd lsof

export API_SECRET="${API_SECRET:-local-dev-secret}"
export NEO_API_SECRET="${NEO_API_SECRET:-$API_SECRET}"

export LOCAL_DEV="${LOCAL_DEV:-true}"
export HOST="${HOST:-0.0.0.0}"

export NEOENGINE_PORT="${NEOENGINE_PORT:-8000}"
export CASHFLOW_PORT="${CASHFLOW_PORT:-8001}"
export ADVISOR_PORT="${ADVISOR_PORT:-8002}"
export AI_COMPANION_PORT="${AI_COMPANION_PORT:-8010}"
export FRONTEND_PORT="${FRONTEND_PORT:-3000}"

export NEOENGINE_API_URL="${NEOENGINE_API_URL:-http://localhost:${NEOENGINE_PORT}}"
export CASHFLOW_API_URL="${CASHFLOW_API_URL:-http://localhost:${CASHFLOW_PORT}}"
export ADVISOR_SERVICE_URL="${ADVISOR_SERVICE_URL:-http://localhost:${ADVISOR_PORT}}"
export AI_COMPANION_SERVICE_URL="${AI_COMPANION_SERVICE_URL:-http://localhost:${AI_COMPANION_PORT}}"
export ADVISOR_REQUEST_TIMEOUT_SECONDS="${ADVISOR_REQUEST_TIMEOUT_SECONDS:-180}"

resolve_python_bin() {
  local requested="$1"
  if [[ -n "$requested" ]]; then
    echo "$requested"
    return 0
  fi
  if [[ -n "${VIRTUAL_ENV:-}" && -x "${VIRTUAL_ENV}/bin/python" ]]; then
    echo "${VIRTUAL_ENV}/bin/python"
    return 0
  fi
  if [[ -x "$ROOT_DIR/.venv/bin/python" ]]; then
    echo "$ROOT_DIR/.venv/bin/python"
    return 0
  fi
  echo "python3"
}

resolve_cashflow_python_bin() {
  local requested="$1"
  if [[ -n "$requested" ]]; then
    echo "$requested"
    return 0
  fi
  local preferred="/Library/Frameworks/Python.framework/Versions/3.11/bin/python3"
  if [[ -x "$preferred" ]]; then
    echo "$preferred"
    return 0
  fi
  echo "Cashflow runtime check failed: required Python not found at ${preferred}." >&2
  echo "Install Python 3.11 at that path or set CASHFLOW_PYTHON explicitly." >&2
  exit 1
}

check_cashflow_mesa_runtime() {
  local python_bin="$1"
  if ! command -v "$python_bin" >/dev/null 2>&1 && [[ ! -x "$python_bin" ]]; then
    echo "Cashflow runtime check failed: python binary not found: $python_bin" >&2
    exit 1
  fi

  local mesa_version
  if ! mesa_version="$("$python_bin" - <<'PY'
import importlib
try:
    mesa = importlib.import_module("mesa")
except Exception:
    print("")
    raise SystemExit(0)
print(getattr(mesa, "__version__", ""))
PY
)"; then
    mesa_version=""
  fi

  if [[ -z "${mesa_version}" ]]; then
    echo "Cashflow runtime check failed: 'mesa' is not importable for ${python_bin}." >&2
    echo "Install requirements with the same interpreter, e.g.:" >&2
    echo "  ${python_bin} -m pip install -r cashflow-modeling-service/requirements.txt" >&2
    echo "  ${python_bin} -m pip install -r cashflow-modeling-service/api/requirements.txt" >&2
    exit 1
  fi

  local mesa_major
  mesa_major="$(echo "$mesa_version" | cut -d'.' -f1)"
  if [[ "$mesa_major" -lt 3 ]]; then
    echo "Cashflow runtime check failed: Mesa ${mesa_version} detected for ${python_bin} (requires >=3)." >&2
    echo "Install compatible dependencies with the same interpreter:" >&2
    echo "  ${python_bin} -m pip install -r cashflow-modeling-service/requirements.txt" >&2
    echo "  ${python_bin} -m pip install -r cashflow-modeling-service/api/requirements.txt" >&2
    exit 1
  fi
}

check_ai_companion_runtime() {
  local python_bin="$1"
  if ! command -v "$python_bin" >/dev/null 2>&1 && [[ ! -x "$python_bin" ]]; then
    echo "AI companion runtime check failed: python binary not found: $python_bin" >&2
    exit 1
  fi

  local missing
  if ! missing="$("$python_bin" - <<'PY'
required = ["flask", "flask_cors", "google.genai", "openai"]
missing = []
for name in required:
    try:
        __import__(name, fromlist=["*"])
    except Exception:
        missing.append(name)
print(",".join(missing))
PY
)"; then
    missing="flask,flask_cors,google.genai,openai"
  fi

  if [[ -n "$missing" ]]; then
    echo "AI companion runtime check: installing missing modules for ${python_bin}: ${missing}" >&2
    if ! "$python_bin" -m pip install -r "$ROOT_DIR/ai-companion/scripts/requirements.txt" >/dev/null 2>&1; then
      echo "AI companion runtime check failed: automatic install did not succeed." >&2
      echo "Install companion requirements manually with the same interpreter:" >&2
      echo "  ${python_bin} -m pip install -r ai-companion/scripts/requirements.txt" >&2
      exit 1
    fi

    # Re-check after installation to ensure runtime is now valid.
    if ! missing="$("$python_bin" - <<'PY'
required = ["flask", "flask_cors", "google.genai", "openai"]
missing = []
for name in required:
    try:
        __import__(name, fromlist=["*"])
    except Exception:
        missing.append(name)
print(",".join(missing))
PY
)"; then
      missing="flask,flask_cors,google.genai,openai"
    fi
    if [[ -n "$missing" ]]; then
      echo "AI companion runtime check failed after install attempt: still missing ${missing}" >&2
      exit 1
    fi
    echo "AI companion runtime check: dependencies ready." >&2
  fi
}

NEOENGINE_PYTHON="$(resolve_python_bin "${NEOENGINE_PYTHON:-}")"
CASHFLOW_PYTHON="$(resolve_cashflow_python_bin "${CASHFLOW_PYTHON:-}")"
ADVISOR_PYTHON="$(resolve_python_bin "${ADVISOR_PYTHON:-}")"

check_cashflow_mesa_runtime "$CASHFLOW_PYTHON"
check_ai_companion_runtime "$ADVISOR_PYTHON"
echo "Using CASHFLOW_PYTHON=${CASHFLOW_PYTHON}"

PIDS=()
PORT_CONFLICTS=()

check_port_free() {
  local service="$1"
  local port="$2"
  local listeners
  local pid_list
  local details

  listeners="$(lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null || true)"
  if [[ -z "$listeners" ]]; then
    return 0
  fi

  details="$(echo "$listeners" | awk 'NR>1 {printf "  - pid=%s cmd=%s user=%s\n", $2, $1, $3}')"
  pid_list="$(echo "$listeners" | awk 'NR>1 {print $2}' | sort -u | paste -sd ' ' -)"
  if [[ -z "$pid_list" ]]; then
    pid_list="<pid>"
  fi

  PORT_CONFLICTS+=(
    "Port ${port} is already in use (expected service: ${service}).
${details}  Suggested command: kill -TERM ${pid_list}"
  )
}

preflight_ports() {
  check_port_free "frontend" "$FRONTEND_PORT"
  check_port_free "advisor" "$ADVISOR_PORT"
  check_port_free "cashflow" "$CASHFLOW_PORT"
  check_port_free "neoengine" "$NEOENGINE_PORT"
  check_port_free "ai-companion" "$AI_COMPANION_PORT"

  if [[ "${#PORT_CONFLICTS[@]}" -gt 0 ]]; then
    echo "Port preflight failed. Resolve conflicts before starting services:" >&2
    for msg in "${PORT_CONFLICTS[@]}"; do
      echo >&2
      echo "$msg" >&2
    done
    echo >&2
    echo "Tip: run ./scripts/dev-down.sh to stop known local app services." >&2
    exit 1
  fi
}

start_service() {
  local name="$1"
  local workdir="$2"
  local logfile="$LOG_DIR/${name}.log"
  shift 2

  (
    cd "$workdir"
    "$@"
  ) >"$logfile" 2>&1 &

  local pid=$!
  PIDS+=("$pid")
  echo "Started ${name} (pid=${pid}) -> ${logfile}"
}

cleanup() {
  trap - INT TERM EXIT
  for pid in "${PIDS[@]:-}"; do
    if kill -0 "$pid" >/dev/null 2>&1; then
      kill "$pid" >/dev/null 2>&1 || true
    fi
  done
  wait || true
}

trap cleanup INT TERM EXIT

preflight_ports

start_service "neoengine" "$ROOT_DIR/neoengine-service/api" env PORT="$NEOENGINE_PORT" HOST="$HOST" LOCAL_DEV="$LOCAL_DEV" "$NEOENGINE_PYTHON" app.py
start_service "cashflow" "$ROOT_DIR/cashflow-modeling-service/api" env PORT="$CASHFLOW_PORT" "$CASHFLOW_PYTHON" app.py
start_service "advisor" "$ROOT_DIR/solution-agent-service" env ADVISOR_PORT="$ADVISOR_PORT" "$ADVISOR_PYTHON" app.py
start_service "ai-companion" "$ROOT_DIR/ai-companion/scripts" env AI_COMPANION_PORT="$AI_COMPANION_PORT" "$ADVISOR_PYTHON" app.py
start_service "frontend" "$ROOT_DIR/frontend" env PORT="$FRONTEND_PORT" pnpm dev

echo
echo "All services started."
echo "Frontend: http://localhost:${FRONTEND_PORT}"
echo "Advisor:  http://localhost:${ADVISOR_PORT}/health"
echo "Cashflow: http://localhost:${CASHFLOW_PORT}/health"
echo "Neo:      http://localhost:${NEOENGINE_PORT}/health"
echo "Companion:http://localhost:${AI_COMPANION_PORT}/health"
echo "Press Ctrl+C to stop all services."

set +e

wait_any() {
  # Bash 3.2 (default on macOS) does not support `wait -n`.
  while true; do
    for pid in "${PIDS[@]}"; do
      if ! kill -0 "$pid" >/dev/null 2>&1; then
        wait "$pid"
        return $?
      fi
    done
    sleep 1
  done
}

if wait -n "${PIDS[@]}" 2>/dev/null; then
  status=0
else
  status=$?
  # Exit code 2 here indicates unsupported `wait -n`; fallback to portable loop.
  if [[ "$status" -eq 2 ]]; then
    wait_any
    status=$?
  fi
fi
set -e

echo "A service exited (status=${status}). Stopping all services..." >&2
exit "$status"
