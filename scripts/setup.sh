#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────
# AI Runtime OS - 一键环境准备（macOS / Linux）
#
#   bash scripts/setup.sh                 # 常规安装
#   bash scripts/setup.sh --locked        # 用锁定版本精确复现
#   bash scripts/setup.sh --skip-frontend
#
# 可重复执行：已存在的 venv / .env / node_modules 不会被动
# ─────────────────────────────────────────────────────────────
set -euo pipefail

SKIP_BACKEND=0
SKIP_FRONTEND=0
LOCKED=0

for arg in "$@"; do
  case "$arg" in
    --skip-backend)  SKIP_BACKEND=1 ;;
    --skip-frontend) SKIP_FRONTEND=1 ;;
    --locked)        LOCKED=1 ;;
    -h|--help)
      sed -n '2,10p' "$0"; exit 0 ;;
    *) echo "未知参数: $arg（用 --help 看用法）" >&2; exit 1 ;;
  esac
done

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend"

cyan()  { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
ok()    { printf '    \033[32mOK\033[0m  %s\n' "$1"; }
warn()  { printf '    \033[33m!!\033[0m  %s\n' "$1"; }
die()   { printf '\033[31m错误: %s\033[0m\n' "$1" >&2; exit 1; }

echo "AI Runtime OS 环境准备"
echo "仓库: $ROOT"

# ── 后端 ──────────────────────────────────────────────────────
if [ "$SKIP_BACKEND" -eq 0 ]; then
  cyan "检查 Python"
  command -v python3 >/dev/null 2>&1 || die "未找到 python3，请先安装 Python 3.11+"
  PY_VER="$(python3 -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])')"
  python3 -c 'import sys;sys.exit(0 if sys.version_info[:2]>=(3,11) else 1)' \
    || die "Python $PY_VER 版本过低，需要 3.11+（实测 3.13 可用）"
  ok "Python $PY_VER"

  cyan "准备虚拟环境 backend/.venv"
  if [ -x "$BACKEND/.venv/bin/python" ]; then
    ok "已存在，复用"
  else
    python3 -m venv "$BACKEND/.venv"
    ok "已创建"
  fi
  VENV_PY="$BACKEND/.venv/bin/python"

  cyan "安装 Python 依赖"
  "$VENV_PY" -m pip install --upgrade pip -q
  REQ="requirements.txt"
  [ "$LOCKED" -eq 1 ] && REQ="requirements.lock.txt"
  echo "    使用 $REQ"
  "$VENV_PY" -m pip install -r "$BACKEND/$REQ"
  ok "依赖安装完成"

  cyan "准备 backend/.env"
  if [ -f "$BACKEND/.env" ]; then
    ok "已存在，未改动"
  else
    cp "$BACKEND/.env.example" "$BACKEND/.env"
    ok "已从 .env.example 生成"
    warn "记得填 OPENAI_API_KEY / OPENAI_BASE_URL，上线前换掉 SECRET_KEY"
  fi
fi

# ── 前端 ──────────────────────────────────────────────────────
if [ "$SKIP_FRONTEND" -eq 0 ]; then
  cyan "检查 Node.js"
  command -v node >/dev/null 2>&1 || die "未找到 node，请先安装 Node 18+（实测 22 可用）"
  NODE_VER="$(node -v)"
  NODE_MAJOR="${NODE_VER#v}"; NODE_MAJOR="${NODE_MAJOR%%.*}"
  [ "$NODE_MAJOR" -ge 18 ] || die "Node $NODE_VER 版本过低，需要 18+"
  ok "Node $NODE_VER"

  cyan "安装前端依赖"
  cd "$FRONTEND"
  npm install
  ok "node_modules 就绪"
  cd "$ROOT"
fi

cat <<'EOF'

-------------------------------------------------------------
环境就绪。接下来：

  1) 灌种子数据（只执行一次，脚本无去重保护）：
       cd backend
       .venv/bin/python -m app.seed

  2) 启动后端（DEBUG=true 时启动会自动建表）：
       cd backend
       .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8002 --reload

  3) 另开一个终端启动前端：
       cd frontend
       npm run dev

  Swagger: http://127.0.0.1:8002/docs    应用: http://localhost:5176
-------------------------------------------------------------
EOF
