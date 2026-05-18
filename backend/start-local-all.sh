#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKEND_DIR="$SCRIPT_DIR"
FRONTEND_DIR="$ROOT_DIR/frontend"
SAM2_DIR="$ROOT_DIR/sam2_service"
LOG_DIR="$ROOT_DIR/logs"
PID_FILE="$ROOT_DIR/.dev-pids"

BACKEND_PORT=8000
FRONTEND_PORT=3000
SAM2_PORT=8001

# 国内源（可通过环境变量覆盖）
PIP_INDEX_URL="${PIP_INDEX_URL:-https://pypi.tuna.tsinghua.edu.cn/simple}"
PIP_TRUSTED_HOST="${PIP_TRUSTED_HOST:-pypi.tuna.tsinghua.edu.cn}"
NPM_REGISTRY="${NPM_REGISTRY:-https://registry.npmmirror.com}"

mkdir -p "$LOG_DIR"

is_port_open() {
  local port="$1"
  lsof -iTCP:"$port" -sTCP:LISTEN -n -P >/dev/null 2>&1
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

kill_port_process() {
  local port="$1"
  local pids
  pids="$(lsof -tiTCP:"$port" -sTCP:LISTEN -n -P || true)"
  if [[ -n "$pids" ]]; then
    echo "[port:$port] 检测到占用，尝试回收进程: $pids"
    echo "$pids" | xargs kill -TERM >/dev/null 2>&1 || true
    if wait_for_port_release "$port" 10 0.5; then
      return 0
    fi

    echo "[port:$port] 进程未及时退出，尝试强制结束"
    echo "$pids" | xargs kill -KILL >/dev/null 2>&1 || true
    wait_for_port_release "$port" 10 0.5 || {
      echo "[port:$port] 端口仍未释放"
      return 1
    }
  fi
}

wait_for_http() {
  local url="$1"
  local retries="${2:-20}"
  local interval="${3:-0.5}"
  local i
  for ((i = 1; i <= retries; i++)); do
    if curl -sS -m 2 "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep "$interval"
  done
  return 1
}

ensure_python_venv() {
  local service_dir="$1"
  local requirements_file="$2"

  if [[ ! -x "$service_dir/.venv/bin/python" ]]; then
    echo "[$service_dir] 未发现 .venv，正在创建..."
    (cd "$service_dir" && python3 -m venv .venv)
  fi

  # 若缺少关键依赖，则自动安装（使用国内源）
  if ! "$service_dir/.venv/bin/python" -c "import fastapi, uvicorn" >/dev/null 2>&1; then
    echo "[$service_dir] 正在安装 Python 依赖（国内源）..."
    (
      cd "$service_dir"
      ./.venv/bin/python -m pip install -U pip \
        -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST"
      ./.venv/bin/python -m pip install -r "$requirements_file" \
        -i "$PIP_INDEX_URL" --trusted-host "$PIP_TRUSTED_HOST"
    )
  fi
}

ensure_frontend_deps() {
  if [[ ! -d "$FRONTEND_DIR/node_modules" ]]; then
    echo "[frontend] 未检测到 node_modules，正在安装依赖（国内源）..."
    (cd "$FRONTEND_DIR" && npm install --registry "$NPM_REGISTRY")
  fi
}

start_sam2() {
  if [[ ! -d "$SAM2_DIR" ]]; then
    echo "[sam2] 未找到目录: $SAM2_DIR，跳过"
    return
  fi

  if is_port_open "$SAM2_PORT"; then
    if wait_for_http "http://localhost:$SAM2_PORT/health" 2 0.2; then
      echo "[sam2] 端口 $SAM2_PORT 已在运行且健康，跳过启动"
      return
    fi
    kill_port_process "$SAM2_PORT"
  fi

  ensure_python_venv "$SAM2_DIR" "$SAM2_DIR/requirements.txt"

  (
    cd "$SAM2_DIR"
    nohup ./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "$SAM2_PORT" \
      > "$LOG_DIR/sam2.log" 2>&1 &
    echo $! > "$LOG_DIR/sam2.pid"
  )

  if wait_for_http "http://localhost:$SAM2_PORT/health" 30 0.5; then
    echo "[sam2] 已启动，日志: $LOG_DIR/sam2.log"
  else
    echo "[sam2] 启动后健康检查失败，请查看日志: $LOG_DIR/sam2.log"
  fi
}

start_backend() {
  if is_port_open "$BACKEND_PORT"; then
    if wait_for_http "http://localhost:$BACKEND_PORT/docs" 2 0.2; then
      echo "[backend] 端口 $BACKEND_PORT 已在运行且健康，跳过启动"
      return
    fi
    kill_port_process "$BACKEND_PORT"
  fi

  ensure_python_venv "$BACKEND_DIR" "$BACKEND_DIR/requirements.txt"

  (
    cd "$BACKEND_DIR"
    SAM2_SERVICE_URL="${SAM2_SERVICE_URL:-http://localhost:$SAM2_PORT}" \
    nohup ./.venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port "$BACKEND_PORT" \
      > "$LOG_DIR/backend.log" 2>&1 &
    echo $! > "$LOG_DIR/backend.pid"
  )

  if wait_for_http "http://localhost:$BACKEND_PORT/docs" 30 0.5; then
    echo "[backend] 已启动，日志: $LOG_DIR/backend.log"
  else
    echo "[backend] 启动后健康检查失败，请查看日志: $LOG_DIR/backend.log"
  fi
}

start_frontend() {
  if is_port_open "$FRONTEND_PORT"; then
    if wait_for_http "http://localhost:$FRONTEND_PORT" 2 0.2; then
      echo "[frontend] 端口 $FRONTEND_PORT 已在运行，跳过启动"
      return
    fi
    kill_port_process "$FRONTEND_PORT"
  fi

  ensure_frontend_deps

  (
    cd "$FRONTEND_DIR"
    nohup npm run dev -- --host 0.0.0.0 --port "$FRONTEND_PORT" \
      > "$LOG_DIR/frontend.log" 2>&1 &
    echo $! > "$LOG_DIR/frontend.pid"
  )

  if wait_for_http "http://localhost:$FRONTEND_PORT" 30 0.5; then
    echo "[frontend] 已启动，日志: $LOG_DIR/frontend.log"
  else
    echo "[frontend] 启动后健康检查失败，请查看日志: $LOG_DIR/frontend.log"
  fi
}

start_sam2
start_backend
start_frontend

{
  echo "sam2_pid=$(cat "$LOG_DIR/sam2.pid" 2>/dev/null || true)"
  echo "backend_pid=$(cat "$LOG_DIR/backend.pid" 2>/dev/null || true)"
  echo "frontend_pid=$(cat "$LOG_DIR/frontend.pid" 2>/dev/null || true)"
  echo "started_at=$(date '+%Y-%m-%d %H:%M:%S')"
} > "$PID_FILE"

echo ""
echo "启动完成"
echo "前端: http://localhost:$FRONTEND_PORT/"
echo "后端: http://localhost:$BACKEND_PORT/docs"
echo "SAM2: http://localhost:$SAM2_PORT/health"
echo "日志目录: $LOG_DIR"
