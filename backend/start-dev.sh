#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$SCRIPT_DIR"
FRONTEND_DIR="$PROJECT_ROOT/frontend"
LOG_DIR="$PROJECT_ROOT/logs"
PID_FILE="$PROJECT_ROOT/.dev-pids"

BACKEND_PORT=8000
FRONTEND_PORT=3000

mkdir -p "$LOG_DIR"

is_port_open() {
  local port="$1"
  lsof -iTCP:"$port" -sTCP:LISTEN -n -P >/dev/null 2>&1
}

kill_port_process() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN -n -P || true)"
  if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill -TERM >/dev/null 2>&1 || true
    sleep 1
  fi
}

backend_healthy() {
  curl -sS -m 2 "http://localhost:$BACKEND_PORT/docs" >/dev/null 2>&1
}

start_backend() {
  if is_port_open "$BACKEND_PORT"; then
    if backend_healthy; then
      echo "[backend] 端口 $BACKEND_PORT 已在运行且健康，跳过启动"
      return
    fi
    echo "[backend] 端口 $BACKEND_PORT 被占用但服务不健康，尝试回收后重启"
    kill_port_process "$BACKEND_PORT"
  fi

  if [[ ! -x "$BACKEND_DIR/.venv/bin/python" ]]; then
    echo "[backend] 未找到虚拟环境解释器: $BACKEND_DIR/.venv/bin/python"
    echo "[backend] 请先创建并安装依赖"
    exit 1
  fi

  (
    cd "$BACKEND_DIR"
    nohup ./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" \
      > "$LOG_DIR/backend.log" 2>&1 &
    echo $! > "$LOG_DIR/backend.pid"
  )

  sleep 1
  if backend_healthy; then
    echo "[backend] 已启动，日志: $LOG_DIR/backend.log"
  else
    echo "[backend] 启动命令已执行，但健康检查未通过，请查看日志: $LOG_DIR/backend.log"
  fi
}

start_frontend() {
  if is_port_open "$FRONTEND_PORT"; then
    echo "[frontend] 端口 $FRONTEND_PORT 已被占用，跳过启动"
    return
  fi

  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    echo "[frontend] 未检测到 node_modules，正在安装依赖..."
    (cd "$FRONTEND_DIR" && npm install)
  fi

  (
    cd "$FRONTEND_DIR"
    nohup npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT" \
      > "$LOG_DIR/frontend.log" 2>&1 &
    echo $! > "$LOG_DIR/frontend.pid"
  )

  echo "[frontend] 已启动，日志: $LOG_DIR/frontend.log"
}

start_backend
start_frontend

{
  echo "backend_pid=$(cat "$LOG_DIR/backend.pid" 2>/dev/null || true)"
  echo "frontend_pid=$(cat "$LOG_DIR/frontend.pid" 2>/dev/null || true)"
  echo "started_at=$(date '+%Y-%m-%d %H:%M:%S')"
} > "$PID_FILE"

echo ""
echo "启动完成（如端口已占用则跳过对应服务）"
echo "前端: http://localhost:$FRONTEND_PORT/"
echo "后端: http://localhost:$BACKEND_PORT/docs"
echo "日志目录: $LOG_DIR"
