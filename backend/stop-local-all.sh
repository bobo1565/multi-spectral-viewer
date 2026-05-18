#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
LOG_DIR="$ROOT_DIR/logs"
PID_FILE="$ROOT_DIR/.dev-pids"

BACKEND_PORT=8000
FRONTEND_PORT=3000
SAM2_PORT=8001

is_pid_running() {
  local pid="$1"
  [[ -n "$pid" ]] && kill -0 "$pid" >/dev/null 2>&1
}

is_port_open() {
  local port="$1"
  lsof -iTCP:"$port" -sTCP:LISTEN -n -P >/dev/null 2>&1
}

wait_for_pid_exit() {
  local pid="$1"
  local retries="${2:-20}"
  local interval="${3:-0.5}"
  local i
  for ((i = 1; i <= retries; i++)); do
    if ! is_pid_running "$pid"; then
      return 0
    fi
    sleep "$interval"
  done
  return 1
}

wait_for_port_release() {
  local port="$1"
  local retries="${2:-20}"
  local interval="${3:-0.5}"
  local i
  for ((i = 1; i <= retries; i++)); do
    if ! is_port_open "$port"; then
      return 0
    fi
    sleep "$interval"
  done
  return 1
}

stop_pid() {
  local name="$1"
  local pid="$2"

  if ! is_pid_running "$pid"; then
    echo "[$name] PID $pid 不存在或已退出"
    return 0
  fi

  echo "[$name] 停止进程 PID $pid"
  kill -TERM "$pid" >/dev/null 2>&1 || true
  if wait_for_pid_exit "$pid" 10 0.5; then
    return 0
  fi

  echo "[$name] 进程未及时退出，尝试强制结束 PID $pid"
  kill -KILL "$pid" >/dev/null 2>&1 || true
  wait_for_pid_exit "$pid" 10 0.5 || {
    echo "[$name] 无法结束 PID $pid"
    return 1
  }
}

stop_port() {
  local name="$1"
  local port="$2"
  local pids

  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN -n -P || true)"
  if [[ -z "$pids" ]]; then
    echo "[$name] 端口 $port 未占用"
    return 0
  fi

  echo "[$name] 端口 $port 占用进程: $pids"
  echo "$pids" | xargs kill -TERM >/dev/null 2>&1 || true
  if wait_for_port_release "$port" 10 0.5; then
    return 0
  fi

  echo "[$name] 端口 $port 未及时释放，尝试强制结束"
  echo "$pids" | xargs kill -KILL >/dev/null 2>&1 || true
  wait_for_port_release "$port" 10 0.5 || {
    echo "[$name] 端口 $port 仍未释放"
    return 1
  }
}

stop_service() {
  local name="$1"
  local port="$2"
  local pid_file="$3"
  local pid=""

  if [[ -f "$pid_file" ]]; then
    pid="$(cat "$pid_file" 2>/dev/null || true)"
  fi

  if [[ -n "$pid" ]]; then
    stop_pid "$name" "$pid" || true
  fi

  if is_port_open "$port"; then
    stop_port "$name" "$port" || true
  else
    echo "[$name] 已停止"
  fi

  rm -f "$pid_file"
}

stop_service "frontend" "$FRONTEND_PORT" "$LOG_DIR/frontend.pid"
stop_service "backend" "$BACKEND_PORT" "$LOG_DIR/backend.pid"
stop_service "sam2" "$SAM2_PORT" "$LOG_DIR/sam2.pid"

rm -f "$PID_FILE"

echo ""
echo "停止完成"
echo "frontend: http://localhost:$FRONTEND_PORT/"
echo "backend: http://localhost:$BACKEND_PORT/docs"
echo "sam2: http://localhost:$SAM2_PORT/health"
