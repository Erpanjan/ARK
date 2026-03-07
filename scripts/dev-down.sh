#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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

require_cmd lsof

export NEOENGINE_PORT="${NEOENGINE_PORT:-8000}"
export CASHFLOW_PORT="${CASHFLOW_PORT:-8001}"
export ADVISOR_PORT="${ADVISOR_PORT:-8002}"
export AI_COMPANION_PORT="${AI_COMPANION_PORT:-8010}"
export FRONTEND_PORT="${FRONTEND_PORT:-3000}"

collect_listener_pids() {
  local port="$1"
  lsof -nP -iTCP:"$port" -sTCP:LISTEN 2>/dev/null | awk 'NR>1 {print $2}' | sort -u || true
}

describe_pid() {
  local pid="$1"
  local cmd
  cmd="$(ps -p "$pid" -o command= 2>/dev/null | head -n 1 || true)"
  if [[ -z "$cmd" ]]; then
    cmd="<unknown>"
  fi
  echo "$cmd"
}

stop_port() {
  local service="$1"
  local port="$2"
  local pids
  local pid
  local attempts

  pids="$(collect_listener_pids "$port")"
  if [[ -z "$pids" ]]; then
    echo "[${service}] port ${port}: no listener found"
    return 0
  fi

  while read -r pid; do
    [[ -z "$pid" ]] && continue
    echo "[${service}] port ${port}: sending TERM to pid=${pid} cmd=$(describe_pid "$pid")"
    kill -TERM "$pid" 2>/dev/null || true
  done <<< "$pids"

  attempts=0
  while [[ "$attempts" -lt 10 ]]; do
    local alive=0
    while read -r pid; do
      [[ -z "$pid" ]] && continue
      if kill -0 "$pid" 2>/dev/null; then
        alive=1
      fi
    done <<< "$pids"
    if [[ "$alive" -eq 0 ]]; then
      break
    fi
    attempts=$((attempts + 1))
    sleep 0.3
  done

  while read -r pid; do
    [[ -z "$pid" ]] && continue
    if kill -0 "$pid" 2>/dev/null; then
      echo "[${service}] port ${port}: sending KILL to pid=${pid} cmd=$(describe_pid "$pid")"
      kill -KILL "$pid" 2>/dev/null || true
    fi
  done <<< "$pids"

  if [[ -n "$(collect_listener_pids "$port")" ]]; then
    echo "[${service}] port ${port}: still occupied after shutdown attempts" >&2
    return 1
  fi

  echo "[${service}] port ${port}: stopped"
  return 0
}

stop_port "frontend" "$FRONTEND_PORT"
stop_port "ai-companion" "$AI_COMPANION_PORT"
stop_port "advisor" "$ADVISOR_PORT"
stop_port "cashflow" "$CASHFLOW_PORT"
stop_port "neoengine" "$NEOENGINE_PORT"

echo "Done."
