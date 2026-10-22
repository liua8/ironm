"""本机启动：和 `mirobody dev` 相同（同一份开发配置、同一个数据库），另外挂上 iron-m 的页面与接口。

mirobody 的 Server.start 接受额外的接口路由，所以不需要改 mirobody 源码。
必须在 vendor/mirobody 目录下运行，mirobody 自带的网页（frontend/）才能照常提供。
用法：PG_URL=... python -m ironm_agent.server [--host 127.0.0.1] [--port 18090]
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="ironm_agent.server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18090)
    args = parser.parse_args()

    from mirobody.cli import _DEV_CONFIG, _pg_from_url  # 与 mirobody dev 用同一份开发配置
    from mirobody.server import Server

    from ironm_agent.web import router

    pg_url = os.environ.get("PG_URL") or os.environ.get("DATABASE_URL")
    if not pg_url:
        sys.exit("需要 PG_URL（postgres://user:pw@host:port/db）")
    for name in ("JWT_KEY", "CONFIG_ENCRYPTION_KEY"):
        if not os.environ.get(name):
            sys.exit(f"需要在 .env 里设置 {name}")
    pg = _pg_from_url(pg_url)
    overlay = _DEV_CONFIG.format(
        host=json.dumps(args.host),
        port=args.port,
        jwt_key=os.environ["JWT_KEY"],
        config_key=os.environ["CONFIG_ENCRYPTION_KEY"],
        **{key: json.dumps(value, ensure_ascii=False) for key, value in pg.items()},
    )
    print(f"iron-m（mirobody 底座）— http://{args.host}:{args.port}/iron/")
    asyncio.run(Server.start(yaml_files=[io.StringIO(overlay)], fastapi_routers=[router]))


if __name__ == "__main__":
    main()
