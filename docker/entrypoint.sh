#!/usr/bin/env bash
# 容器里的启动脚本（spec §185）。
#   init   以 root 跑一次：第一次生成数据库密码和两把密钥（存在数据卷，以后照用），把数据卷交给 ironm 用户
#   serve  以 ironm 用户跑：读密钥、后台补配图、启动 IronM
set -euo pipefail
PG_SECRET=/secrets/pg/pg_password
JWT_SECRET=/secrets/keys/jwt_key
CONFIG_SECRET=/secrets/keys/config_key

case "${1:-serve}" in
init)
  umask 077
  for f in "$PG_SECRET" "$JWT_SECRET" "$CONFIG_SECRET"; do
    if [ ! -s "$f" ]; then
      python -c 'import secrets; print(secrets.token_hex(32))' > "$f.tmp"
      mv "$f.tmp" "$f"
      echo "生成了 $(basename "$f")（只在数据卷里）"
    fi
  done
  # 数据库容器换成 postgres 用户后还要读一次密码文件；这个卷只挂给数据库、IronM 和这里
  chmod 644 "$PG_SECRET"
  chown ironm:ironm "$JWT_SECRET" "$CONFIG_SECRET"
  chown -R ironm:ironm /data /app/vendor/mirobody/.theta
  ;;

serve)
  for f in "$PG_SECRET" "$JWT_SECRET" "$CONFIG_SECRET"; do
    [ -s "$f" ] || { echo "缺少 $f：要先跑 init（docker compose up 会自动跑）" >&2; exit 1; }
  done
  # .env 里写了空值的可选设置当作没写
  for name in EMAIL_SMTP_HOST EMAIL_SMTP_PORT EMAIL_SMTP_USER EMAIL_SMTP_PASS EMAIL_FROM EMAIL_FROM_NAME \
      TAVILY_API_KEY IRONM_ADMINS HTTP_PROXY HTTPS_PROXY; do
    [ -n "${!name:-}" ] || unset "$name"
  done
  JWT_KEY="$(cat "$JWT_SECRET")"
  CONFIG_ENCRYPTION_KEY="$(cat "$CONFIG_SECRET")"
  PG_URL="postgres://ironm:$(cat "$PG_SECRET")@pg:5432/mirobody"
  export JWT_KEY CONFIG_ENCRYPTION_KEY PG_URL
  # 不要 mirobody 预置的演示账号和固定验证码（同 §177）
  export IRONM_EXTRA_CONFIG=config/selfhost.yaml SEED_DEMO_DATA=false
  export IRONM_DATA_DIR=/data

  if [ "${IRONM_IMAGES:-1}" = 1 ]; then
    # 每次启动都补一次：只下还没有的（第一次全下；没下到的、更新后清单里新加的，下次启动再补），不影响先用
    (
      python scripts/fetch_images.py > /tmp/fetch-images.log 2>&1 || true
      grep -m 1 "^配图" /tmp/fetch-images.log || tail -n 3 /tmp/fetch-images.log
      # 动作图有变化才重新合成动图
      now="$(ls /data/exercise-images 2>/dev/null | grep -vc '\.gif$' || true)"   # 不算合成出来的动图本身
      if [ "$now" != "$(cat /data/.gifs-made 2>/dev/null || true)" ]; then
        python scripts/make_exercise_gifs.py >/dev/null 2>&1 && echo "$now" > /data/.gifs-made \
          || echo "动作动图没合成，不影响使用"
      fi
    ) &
  fi

  echo "IronM 起来后用浏览器打开：http://127.0.0.1:${IRONM_PORT:-18090}/iron/"
  cd /app/vendor/mirobody   # mirobody 自带的网页按这个目录找
  exec python -m ironm_agent.server --host 0.0.0.0 --port 18090
  ;;

*)
  exec "$@"
  ;;
esac
