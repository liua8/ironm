"""本机启动：和 `mirobody dev` 相同（同一份开发配置、同一个数据库），另外挂上 iron-m 的页面与接口。

mirobody 的 Server.start 接受额外的接口路由，所以不需要改 mirobody 源码。
必须在 vendor/mirobody 目录下运行，mirobody 自带的网页（frontend/）才能照常提供。
用法：PG_URL=... python -m ironm_agent.server [--host 127.0.0.1] [--port 18090]
本机额外的配置（不进仓库，比如自测用的登录账号）放在 IRONM_EXTRA_CONFIG 指向的 YAML 里，叠在开发配置之上。

并入 mirobody（spec §168）：python -m ironm_agent.server --config mirobody线上的配置.yaml [更多.yaml] --port 18100
用 mirobody 线上同样的配置文件（同一个数据库、同一套密钥和发信），不套开发配置，相当于 `mirobody serve`
再挂上 iron-m 的接口、网页和问答 Agent。--host/--port 只改这个进程监听哪里。
"""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(prog="ironm_agent.server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=18090)
    parser.add_argument("--config", nargs="+", default=None,
                        help="并入 mirobody：用它线上的配置文件，不套开发配置（§168）")  # fmt: skip
    args = parser.parse_args()
    if args.config:
        serve_with(args.config, args.host, args.port)
        return

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
    files: list[str | io.StringIO] = [io.StringIO(overlay)]
    extra = os.environ.get("IRONM_EXTRA_CONFIG", "")
    if extra:
        path = (
            Path(extra)
            if Path(extra).is_absolute()
            else Path(__file__).resolve().parents[1] / extra
        )
        if not path.is_file():
            sys.exit(f"IRONM_EXTRA_CONFIG 指向的文件不存在：{path}")
        files.append(str(path))
    print(f"AI 健身管家（iron-m，mirobody 底座）— http://{args.host}:{args.port}/iron/")
    asyncio.run(Server.start(yaml_files=files, fastapi_routers=[router]))


def serve_with(configs: list[str], host: str, port: int) -> None:
    """并入 mirobody（§168）：和 `mirobody serve 配置…` 一样启动，只多挂 iron-m 的路由，另外监听自己的端口。"""
    from mirobody.server import Server

    from ironm_agent.web import router

    missing = [c for c in configs if not Path(c).is_file()]
    if missing:
        sys.exit(f"配置文件不存在：{'、'.join(missing)}")
    listen = io.StringIO(f"HTTP_HOST: {json.dumps(host)}\nHTTP_PORT: {port}\nHTTP_SERVER_NAME: iron-m\n")
    print(f"AI 健身管家（iron-m，并入 mirobody）— http://{host}:{port}/iron/")
    asyncio.run(Server.start(yaml_files=[*configs, listen], fastapi_routers=[router]))


if __name__ == "__main__":
    main()
