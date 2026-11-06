"""用自己的模型（spec [2026-11-03] §153）：密钥加密存、只给末四位；自定义地址不许内网；测试连接分开报；
拍照记一餐、饮食推荐、认器械用他自己的模型，出错时提示去测试、不换回默认。不连网络、不连数据库。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent import user_models as um
from ironm_agent.llm import Reply, ToolCall
from tests.conftest import model_is, real_own_config

KEY = "sk-test-1234567890abcd"


def _client(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, um.ModelBook]:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more, web_user_models

    book = um.ModelBook()
    monkeypatch.setattr(web_more, "user_model_store", lambda: book)
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web_user_models.model_store] = lambda: book
    return TestClient(app), book


def test_save_read_delete_never_returns_key(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    c, book = _client(monkeypatch)
    got = c.get("/iron/api/my-model").json()
    assert (
        got["model"] is None
        and got["presets"]["deepseek"]["base_url"] == "https://api.deepseek.com"
    )
    with caplog.at_level(logging.INFO):
        saved = c.put(
            "/iron/api/my-model",
            json={"provider": "qwen", "api_key": KEY, "chat_model": "qwen-plus"},
        ).json()
    assert saved["model"]["key_tail"] == "abcd" and KEY not in str(saved) and KEY not in caplog.text
    assert book.rows["42"].base_url == um.PRESETS["qwen"].base_url  # 预设的地址用预设的
    assert KEY not in c.get("/iron/api/my-model").text
    # 改模型不重填密钥：沿用存着的
    c.put("/iron/api/my-model", json={"provider": "qwen", "chat_model": "qwen-max"})
    assert book.rows["42"].api_key == KEY and book.rows["42"].chat_model == "qwen-max"
    assert c.delete("/iron/api/my-model").json() == {"model": None} and "42" not in book.rows
    assert (
        c.put("/iron/api/my-model", json={"provider": "qwen", "chat_model": "x"}).status_code == 422
    )  # 没密钥


def test_custom_address_must_be_public_https(monkeypatch: pytest.MonkeyPatch) -> None:
    for bad in (
        "http://api.example.com/v1",
        "https://127.0.0.1/v1",
        "https://localhost/v1",
        "https://10.0.0.8/v1",
        "ftp://x",
    ):
        with pytest.raises(um.BadAddress):
            um.check_url("custom", bad)
    monkeypatch.setattr(um.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("8.8.8.8", 443))])
    assert um.check_url("custom", "https://api.example.com/v1/") == "https://api.example.com/v1"
    c, _ = _client(monkeypatch)
    monkeypatch.setattr(
        um.socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", ("192.168.1.2", 443))]
    )
    r = c.put(
        "/iron/api/my-model",
        json={
            "provider": "custom",
            "base_url": "https://evil.example/v1",
            "api_key": KEY,
            "chat_model": "m",
        },
    )
    assert r.status_code == 422 and "内网" in r.json()["detail"]


def test_user_config_routes_every_stage() -> None:
    m = um.UserModel(
        provider="deepseek",
        base_url="https://api.deepseek.com",
        api_key=KEY,
        chat_model="deepseek-flash",
        vision_model="",
    )
    cfg = um.config_for(m)
    assert {
        cfg.route(s).model for s in ("route", "expert", "compose", "memory", "coach", "vision")
    } == {"deepseek-flash"}
    assert cfg.route("expert").extra_body == {"thinking": {"type": "disabled"}}
    own = real_own_config()
    got = asyncio.run(own("42", _Store(m)))  # type: ignore[operator]
    assert got is not None and got[1] == {um.KEY_ENV: KEY}  # 用他自己的密钥
    assert asyncio.run(own("7", _Store(None))) is None  # type: ignore[operator]  # 没填就没有模型，不拿服务器的顶上（§167）


class _Store:
    def __init__(self, m: um.UserModel | None) -> None:
        self.m = m

    async def get(self, user_id: str) -> um.UserModel | None:
        return self.m


class _Err(Exception):
    def __init__(self, code: int) -> None:
        self.status_code = code


def test_connection_reports_each_part(monkeypatch: pytest.MonkeyPatch) -> None:
    m = um.UserModel(
        provider="qwen",
        base_url="https://x",
        api_key=KEY,
        chat_model="qwen-plus",
        vision_model="qwen-vl-plus",
    )
    seen: list[str] = []

    # 和真的 _request 一样带回用量（§165）
    async def ok(route: Any, key: str, messages: Any, tools: Any, json_mode: bool = False) -> tuple[Reply, tuple[int, int]]:
        seen.append(route.model)
        if tools:
            return Reply("", (ToolCall("1", "ping", {"ok": True}),)), (1, 1)
        return Reply("红色" if isinstance(messages[0]["content"], list) else "ok"), (1, 1)

    monkeypatch.setattr(um, "_request", ok)
    got = asyncio.run(um.test_connection(m))
    assert (
        got == {"chat": {"ok": True}, "tools": {"ok": True}, "vision": {"ok": True}}
        and seen[-1] == "qwen-vl-plus"
    )

    async def no_tools(route: Any, key: str, messages: Any, tools: Any, json_mode: bool = False) -> tuple[Reply, tuple[int, int]]:
        return Reply("看不到图片" if isinstance(messages[0]["content"], list) else "ok"), (1, 1)

    monkeypatch.setattr(um, "_request", no_tools)
    got = asyncio.run(um.test_connection(m))
    assert (
        got["chat"]["ok"]
        and not got["tools"]["ok"]
        and "调用工具" in got["tools"]["why"]
        and not got["vision"]["ok"]
    )

    async def bad_key(*a: Any) -> tuple[Reply, tuple[int, int]]:
        raise _Err(401)

    monkeypatch.setattr(um, "_request", bad_key)
    got = asyncio.run(um.test_connection(m))
    assert got["chat"] == {"ok": False, "why": "密钥不对或没有权限"} and KEY not in str(got)


def test_own_model_failure_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import machines as mc
    from ironm_agent.llm import ModelUnavailable

    class Broken:
        async def chat(self, *a: Any, **k: Any) -> Reply:
            raise ModelUnavailable("APIStatusError")

    c, _ = _client(monkeypatch)

    model_is(monkeypatch, Broken())
    r = c.post(
        "/iron/api/machines/recognize", files={"photo": ("a.jpg", b"\xff\xd8x", "image/jpeg")}
    ).json()
    assert r["status"] == "failed" and r["message"] == um.OWN_FAILED
    assert mc.looker(Broken()) is not None  # type: ignore[arg-type]


def test_page_wiring() -> None:
    src = (Path(__file__).resolve().parents[1] / "ironm_agent" / "web" / "app.js").read_text(
        encoding="utf-8"
    )
    assert 'row("coach", "模型和 API", "可以用自己的模型", modelSheet)' in src
    sheet = src[src.index("async function modelSheet()") : src.index("// 搭子记得的事")]
    assert (
        'type: "password"' in sheet
        and "测试连接" in sheet
        and "删除这个模型" in sheet
        and "默认模型" not in sheet  # 没有默认模型了（§167）
        and "key_tail" in sheet
    )
