#!/usr/bin/env bash
# 本机 PostgreSQL（含 pgvector）：装在项目目录 .pg/ 里，只监听 127.0.0.1:55432
# 用法：scripts/pg.sh install | init | start | stop | status | check
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PG="$ROOT/.pg"
BIN="$PG/env/bin"
DATA="$PG/data"
PORT=55432
DB=mirobody
USER_NAME=ironm

load_env() {
  [ -f "$ROOT/.env" ] || { echo "缺少 .env" >&2; exit 1; }
  set -a; . "$ROOT/.env"; set +a
  [ -n "${PG_PASSWORD:-}" ] || { echo ".env 里没有 PG_PASSWORD" >&2; exit 1; }
}

psql_db() {
  PGPASSWORD="$PG_PASSWORD" "$BIN/psql" -h 127.0.0.1 -p "$PORT" -U "$USER_NAME" -v ON_ERROR_STOP=1 -qtA "$@"
}

case "${1:-}" in
  install)
    MAMBA_ROOT_PREFIX="$PG/mamba" micromamba create -y -q -p "$PG/env" -c conda-forge "postgresql=18" "pgvector=0.8.6"
    ;;
  init)
    load_env
    [ -d "$DATA" ] && { echo "数据目录已存在：${DATA}" >&2; exit 1; }
    pw="$(mktemp)"; trap 'rm -f "$pw"' EXIT
    printf %s "$PG_PASSWORD" > "$pw"
    "$BIN/initdb" -D "$DATA" -U "$USER_NAME" --pwfile="$pw" -A scram-sha-256 -E UTF8 --locale=C >/dev/null
    {
      echo "listen_addresses = '127.0.0.1'"
      echo "port = $PORT"
      echo "unix_socket_directories = '$PG'"
    } >> "$DATA/postgresql.conf"
    "$0" start
    PGPASSWORD="$PG_PASSWORD" "$BIN/createdb" -h 127.0.0.1 -p "$PORT" -U "$USER_NAME" "$DB"
    echo "已初始化：库 ${DB}，端口 ${PORT}"
    ;;
  start)
    "$BIN/pg_ctl" -D "$DATA" -l "$PG/postgres.log" -w start >/dev/null && echo "已启动（端口 ${PORT}）"
    ;;
  stop)
    "$BIN/pg_ctl" -D "$DATA" -w stop >/dev/null && echo "已停止"
    ;;
  status)
    "$BIN/pg_ctl" -D "$DATA" status
    ;;
  check)
    load_env
    psql_db -d "$DB" -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_trgm; CREATE EXTENSION IF NOT EXISTS pgcrypto;"
    psql_db -d "$DB" -c "SELECT extname || ' ' || extversion FROM pg_extension WHERE extname IN ('vector','pg_trgm','pgcrypto') ORDER BY extname;"
    ;;
  *)
    echo "用法：$0 install | init | start | stop | status | check" >&2; exit 2
    ;;
esac
