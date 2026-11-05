"""并入 mirobody 的启动（spec §168）：用 mirobody 线上的配置文件、挂上 iron-m 的路由，不套开发配置。"""

from __future__ import annotations

import io
import sys
from pathlib import Path
from typing import Any

import pytest


def test_serve_with_uses_mirobody_configs_and_iron_m_router(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from mirobody.server import Server

    from ironm_agent import server
    from ironm_agent.web import router

    cfg = tmp_path / "prod.yaml"
    cfg.write_text("PRODUCTION: true\n", encoding="utf-8")
    seen: dict[str, Any] = {}

    async def start(yaml_files: list[Any], fastapi_routers: list[Any]) -> None:
        seen.update(files=yaml_files, routers=fastapi_routers)

    monkeypatch.setattr(Server, "start", start)
    monkeypatch.setattr(sys, "argv", ["ironm_agent.server", "--config", str(cfg), "--port", "18100"])
    server.main()
    files = seen["files"]
    assert files[0] == str(cfg) and isinstance(files[-1], io.StringIO)
    listen = files[-1].getvalue()
    assert "HTTP_PORT: 18100" in listen and "PRODUCTION" not in listen and "PG_" not in listen  # 不套开发配置
    assert seen["routers"] == [router]


def test_serve_with_stops_on_missing_config(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import server

    monkeypatch.setattr(sys, "argv", ["ironm_agent.server", "--config", "/no/such.yaml"])
    with pytest.raises(SystemExit, match="配置文件不存在"):
        server.main()
