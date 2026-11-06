#!/usr/bin/env bash
# 配置发信邮箱（注册、验证码登录、找回密码要发验证码，spec §155、§174）。
# 一问一答：选邮箱、填地址、粘贴授权码（输入时不显示）。写进本机 .env（不进仓库），原来的发信配置先去掉。
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ENV="$ROOT/.env"
[ -f "$ENV" ] || { echo "缺少 $ENV" >&2; exit 1; }

# 用法：setup_mail.sh [1-4 邮箱类型] [发信地址]；不带参数就一项项问
pick="${1:-}"; USER_ADDR="${2:-}"
if [ -z "$pick" ]; then
echo "用哪个邮箱发验证码？"
echo "  1) QQ 邮箱      smtp.qq.com"
echo "  2) 163 邮箱     smtp.163.com"
echo "  3) 腾讯企业邮   smtp.exmail.qq.com"
echo "  4) 其他（自己填服务器）"
printf "选 1-4："
read -r pick
fi
case "$pick" in
  1) HOST=smtp.qq.com ;;
  2) HOST=smtp.163.com ;;
  3) HOST=smtp.exmail.qq.com ;;
  4) printf "SMTP 服务器地址："; read -r HOST ;;
  *) echo "没选对，退出" >&2; exit 1 ;;
esac
PORT=465
if [ "$pick" = "4" ]; then printf "端口（465 用 SSL，587 用 STARTTLS，直接回车用 465）："; read -r p; PORT="${p:-465}"; fi

if [ -z "$USER_ADDR" ]; then printf "发信邮箱地址："; read -r USER_ADDR; fi
echo "发信邮箱：${USER_ADDR}（${HOST}:${PORT}）"
case "$USER_ADDR" in *@*) ;; *) echo "邮箱地址不对，退出" >&2; exit 1 ;; esac

printf "授权码（在邮箱设置里开启 SMTP 后生成，不是登录密码；输入时不显示）："
read -rs PASS
echo
[ -n "$PASS" ] || { echo "授权码是空的，退出" >&2; exit 1; }

cp "$ENV" "$ENV.bak-mail"
grep -vE '^(EMAIL_SMTP_HOST|EMAIL_SMTP_PORT|EMAIL_SMTP_USER|EMAIL_SMTP_PASS|EMAIL_FROM|EMAIL_FROM_NAME)=' "$ENV.bak-mail" > "$ENV"
{
  echo ""
  echo "# 发信（scripts/setup_mail.sh 写入）"
  echo "EMAIL_SMTP_HOST=$HOST"
  echo "EMAIL_SMTP_PORT=$PORT"
  echo "EMAIL_SMTP_USER=$USER_ADDR"
  echo "EMAIL_SMTP_PASS='$PASS'"
  echo "EMAIL_FROM=$USER_ADDR"
  echo "EMAIL_FROM_NAME=IronM"
} >> "$ENV"
chmod 600 "$ENV" "$ENV.bak-mail"
unset PASS

# 试一下能不能登录 SMTP（只登录，不发信）
set -a; . "$ENV"; set +a
python3 - <<'PY' && echo "✓ SMTP 登录成功，已写进 .env（原来的备份在 .env.bak-mail）" || echo "✗ SMTP 登录没成功：检查授权码、邮箱是否开启了 SMTP；配置已写进 .env，改好后重新运行本脚本"
import os, smtplib, sys
host, port = os.environ["EMAIL_SMTP_HOST"], int(os.environ["EMAIL_SMTP_PORT"])
try:
    if port == 465:
        s = smtplib.SMTP_SSL(host, port, timeout=15)
    else:
        s = smtplib.SMTP(host, port, timeout=15); s.starttls()
    s.login(os.environ["EMAIL_SMTP_USER"], os.environ["EMAIL_SMTP_PASS"]); s.quit()
except Exception as e:
    print(f"  原因：{type(e).__name__}", file=sys.stderr); sys.exit(1)
PY
