#!/usr/bin/env bash
# 在自己电脑上跑 IronM（spec [2026-10-23] §177）：一条命令装好、起来，浏览器打开网页版。
#
#   scripts/start.sh               第一次：装环境和数据库、生成 .env、下配图、启动；以后：直接启动
#   scripts/start.sh --no-images   不下配图（以后再跑 scripts/fetch_images.py 补）
#
# 换端口：IRONM_PORT=18200 IRONM_PG_PORT=55500 scripts/start.sh（默认 18090、55432，都只听本机）
# 按 Ctrl+C 停：服务和这次起的数据库一起停。
# 只用项目目录：Python 环境在 .venv/，数据库和 micromamba 在 .pg/，图片在 data/，不往系统里装、不用 sudo。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PORT="${IRONM_PORT:-18090}"
export IRONM_PG_PORT="${IRONM_PG_PORT:-55432}"
IMAGES=1
for a in "$@"; do
  case "$a" in
    --no-images) IMAGES=0 ;;
    -h|--help) sed -n '2,9p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "不认识的参数：$a（只有 --no-images）" >&2; exit 2 ;;
  esac
done

say() { printf '\n== %s\n' "$*"; }

# ---- 1. uv（装 Python 和依赖用）----
if ! command -v uv >/dev/null 2>&1; then
  cat >&2 <<'EOF'
还没装 uv（用来装 Python 和依赖）。先在终端里跑这一行，装好后重新打开终端，再跑 scripts/start.sh：

  curl -LsSf https://astral.sh/uv/install.sh | sh

（说明：https://docs.astral.sh/uv/getting-started/installation/）
EOF
  exit 1
fi

case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) PLATFORM=osx-arm64 ;;
  Darwin-x86_64) PLATFORM=osx-64 ;;
  Linux-x86_64) PLATFORM=linux-64 ;;
  Linux-aarch64|Linux-arm64) PLATFORM=linux-aarch64 ;;
  *) echo "暂时只支持 Mac 和 Linux（这台是 $(uname -s) $(uname -m)）" >&2; exit 1 ;;
esac

# 两个大数据文件走 git-lfs；没装 git-lfs 克隆下来的只是几行占位文字，mirobody 会报"数据坏了"
LFS_MISSING=0
for f in vendor/mirobody/mirobody/res/loinc/fhir_loinc_bundle.tar.gz vendor/mirobody/mirobody/res/genomics/cpic-v1.60.0.json.gz; do
  if [ ! -f "$f" ] || head -c 40 "$f" | grep -q "git-lfs"; then LFS_MISSING=1; fi
done
if [ "$LFS_MISSING" = 1 ]; then
  if git lfs version >/dev/null 2>&1 && [ -d .git ]; then
    say "取 git-lfs 里的数据文件"
    git lfs pull
  else
    cat >&2 <<'EOF'
代码里有两个大数据文件要用 git-lfs 取，现在拿到的只是占位文字。先装 git-lfs，再在这个目录里跑：

  git lfs install && git lfs pull

装 git-lfs：Mac 上 brew install git-lfs；Linux 上用系统的包管理器装 git-lfs（说明：https://git-lfs.com）。
不是用 git clone、而是下载压缩包的，改用 git clone 重新拿代码。
EOF
    exit 1
  fi
fi

# ---- 2. Python 环境 ----
say "Python 环境"
uv sync --frozen

# ---- 3. .env：数据库密码和两把密钥，第一次随机生成，已有的不动 ----
if [ ! -f .env ]; then
  say "生成 .env（数据库密码和密钥，只在这台电脑上）"
  umask 077
  {
    echo "# 第一次运行 scripts/start.sh 时生成（§177）。别发给别人；删了会登不上、加密的设置读不出来。"
    echo "PG_PASSWORD=$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(16))')"
    echo "JWT_KEY=$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(32))')"
    echo "CONFIG_ENCRYPTION_KEY=$(.venv/bin/python -c 'import secrets; print(secrets.token_hex(16))')"
    echo
    echo "# 可选：联网查资料（https://tavily.com）；发信（注册、找回密码发验证码），格式见 .env.example"
  } > .env
  umask 022
  echo "已写好 .env（只有你能读）"
fi

# ---- 4. 数据库（PostgreSQL 18 + pgvector，装在 .pg/）----
if [ ! -x .pg/env/bin/pg_ctl ]; then
  MICROMAMBA="$(command -v micromamba || true)"
  if [ -z "$MICROMAMBA" ]; then
    say "下载 micromamba（只放在 .pg/bin，用来装数据库）"
    mkdir -p .pg/bin
    curl -fsSL "https://micro.mamba.pm/api/micromamba/${PLATFORM}/latest" | tar -xj -C .pg bin/micromamba
    MICROMAMBA="$ROOT/.pg/bin/micromamba"
  fi
  say "安装数据库（第一次要几分钟）"
  MICROMAMBA="$MICROMAMBA" scripts/pg.sh install
fi

STARTED_PG=0
if [ ! -d .pg/data ]; then
  say "初始化数据库"
  scripts/pg.sh init
  STARTED_PG=1
elif ! .pg/env/bin/pg_ctl -D .pg/data status >/dev/null 2>&1; then
  scripts/pg.sh start
  STARTED_PG=1
fi
PGOPTIONS="-c client_min_messages=warning" scripts/pg.sh check >/dev/null

stop_pg() { [ "$STARTED_PG" = 1 ] && "$ROOT/scripts/pg.sh" stop || true; }
trap stop_pg EXIT

# ---- 5. 配图 ----
if [ "$IMAGES" = 1 ] && [ ! -f data/.images-done ]; then
  say "下载配图（动作、食物、排行榜，第一次要几分钟；不想等可以 Ctrl+C 后加 --no-images 再跑）"
  .venv/bin/python scripts/fetch_images.py
  .venv/bin/python scripts/make_exercise_gifs.py >/dev/null 2>&1 || echo "动作动图没合成，不影响使用"
  touch data/.images-done
fi

# ---- 6. 启动 ----
set -a; . ./.env; set +a
export PG_URL="postgres://ironm:${PG_PASSWORD}@127.0.0.1:${IRONM_PG_PORT}/mirobody"
# 不要 mirobody 预置的演示账号和固定验证码；.env 里自己指了别的（开发用）就照它的
export IRONM_EXTRA_CONFIG="${IRONM_EXTRA_CONFIG:-config/selfhost.yaml}"
URL="http://127.0.0.1:${PORT}/iron/"
say "启动 IronM（下面是服务的日志，起好后会再提示打开哪个网址）"
cd vendor/mirobody   # mirobody 自带的网页按这个目录找
"$ROOT/.venv/bin/python" -m ironm_agent.server --host 127.0.0.1 --port "$PORT" &
SERVER=$!
stop_all() { kill "$SERVER" 2>/dev/null || true; wait "$SERVER" 2>/dev/null || true; stop_pg; }
trap stop_all EXIT
trap 'exit 130' INT TERM
for _ in $(seq 1 180); do
  kill -0 "$SERVER" 2>/dev/null || { echo "服务没起来，看上面的日志" >&2; exit 1; }
  curl -fsS -o /dev/null "$URL" 2>/dev/null && break
  sleep 1
done
cat <<EOF

========================================================================
IronM 起好了。用浏览器打开：${URL}
  （上面 mirobody 日志里说的 /setup 不用管，模型在 IronM 的「我」里填）
  第一次先注册（邮箱就是登录名），再到「我 → 模型和 API」填你自己的模型密钥，就能问 IronM。
  数据只存在这台电脑的 .pg/ 里；问的话和照片会发给你填的模型服务商。
  停：在这个窗口按 Ctrl+C。
========================================================================
EOF
wait "$SERVER"
