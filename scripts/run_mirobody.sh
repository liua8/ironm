#!/usr/bin/env bash
# 本机启动 mirobody 开发服务（网页 + 接口 + 后台任务），地址 http://127.0.0.1:18090
# 必须在 vendor/mirobody 目录下启动，才能提供它自带的网页（frontend/）
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/.env" ] || { echo "缺少 .env" >&2; exit 1; }
set -a; . "$ROOT/.env"; set +a

export PG_URL="postgres://ironm:${PG_PASSWORD}@127.0.0.1:55432/mirobody"
export SEED_DEMO_DATA=true   # 演示账号 you@mirobody.ai，验证码 111111（mirobody 自带配置）

cd "$ROOT/vendor/mirobody"
# 和 mirobody dev 相同，另外挂上 iron-m 的页面与接口（/iron/）
exec "$ROOT/.venv/bin/python" -m ironm_agent.server --host 127.0.0.1 --port 18090
