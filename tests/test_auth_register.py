"""注册和登录（spec [2026-11-03] §155）：重设密码要验证码；没配发信时不改；登录页能注册、找回密码、用验证码登录。
不连数据库、不发邮件。"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from mirobody.user import user_service as us
from mirobody.user.auth.email import DummyEmailCodeValidator


class Sent:
    def __init__(self, ok_code: str) -> None:
        self.ok = ok_code

    async def verify(self, to_email: str, code: str, service: str = "") -> str | None:
        return None if code == self.ok else "Invalid code."


class Users:
    """假的 mirobody 用户服务：只有找回密码用到的几样。"""

    def __init__(self, validator: Any, mail: bool) -> None:
        self._email_validator = validator
        self.mail = mail

    def sends_mail(self) -> bool:
        return self.mail

    def requires_second_factor(self, *_: Any) -> bool:  # mirobody 放在 app.state 上的就是这个方法
        return False

    async def _generate_auth_response(self, uid: int, email: str, how: str, request: Any) -> Any:
        return us.json_response_with_code(data={"access_token": f"t{uid}"})


class Req:
    method = "POST"

    def __init__(self, body: dict[str, Any], users: Users | None) -> None:
        from types import SimpleNamespace

        self.body = body
        self.state = SimpleNamespace(start_time=None, user_id=None)
        state = SimpleNamespace()
        if users is not None:
            state.requires_second_factor = users.requires_second_factor
        self.app = SimpleNamespace(state=state)

    async def json(self) -> dict[str, Any]:
        return self.body


def _call(
    users: Users | None, body: dict[str, Any], monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]
) -> tuple[dict[str, Any], list[Any]]:
    from ironm_agent import web_password

    seen: list[Any] = []

    async def query(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        seen.append((sql, params))
        return rows

    monkeypatch.setattr(web_password, "_query", query)
    resp = asyncio.run(web_password.password_reset(Req(body, users)))  # type: ignore[arg-type]
    return json.loads(resp.body), seen


def test_reset_needs_mail_and_the_right_code(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"email": "A@x.com", "code": "123456", "password": "newpass88"}
    got, seen = _call(Users(DummyEmailCodeValidator({}), mail=False), body, monkeypatch, [{"id": 5}])
    assert got["code"] == -7 and not seen  # 没配发信：不改
    got, seen = _call(None, body, monkeypatch, [{"id": 5}])
    assert got["code"] == -7 and not seen  # 取不到 mirobody 的用户服务：也不改
    users = Users(Sent("123456"), mail=True)
    got, seen = _call(users, {**body, "code": "000000"}, monkeypatch, [{"id": 5}])
    assert got["code"] == -6 and not seen  # 验证码不对：不改
    got, seen = _call(users, {**body, "password": "short"}, monkeypatch, [{"id": 5}])
    assert got["code"] == -3 and not seen
    got, seen = _call(users, body, monkeypatch, [{"id": 5}])
    assert got["data"]["access_token"] == "t5"
    sql, params = seen[0]
    assert "crypt(:password, gen_salt('bf', 12))" in sql and params == {
        "email": "a@x.com",
        "password": "newpass88",
    }
    got, _ = _call(users, body, monkeypatch, [])
    assert got["code"] == -6  # 没有这个账号：和验证码不对一样的回答


def test_reset_lives_in_iron_m_and_mirobody_is_untouched() -> None:
    """§168：并入 mirobody 不改它的逻辑——找回密码挂在 iron-m 的路由上，mirobody 的用户服务里没有。"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ironm_agent.web import router

    app = FastAPI()
    app.include_router(router)
    body = {"email": "a@x.com", "code": "123456", "password": "newpass88"}
    got = TestClient(app).post("/password/reset", json=body).json()
    assert got["code"] == -7  # 挂上了；这个测试应用里没有 mirobody 的用户服务，所以如实说发不了信
    src = (Path(us.__file__)).read_text(encoding="utf-8")
    assert "password_reset_handler" not in src and "iron-m 修改" not in src


def test_auth_options_says_whether_mail_works(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from ironm_agent import web, web_user_models

    app = FastAPI()
    app.include_router(web.router)
    c = TestClient(app)
    monkeypatch.setattr(web_user_models, "mail_ready", lambda: False)
    assert c.get("/iron/api/auth/options").json() == {"mail": False}
    monkeypatch.setattr(web_user_models, "mail_ready", lambda: True)
    assert c.get("/iron/api/auth/options").json() == {"mail": True}


def test_login_page_wiring() -> None:
    src = (Path(__file__).resolve().parents[1] / "ironm_agent" / "web" / "app.js").read_text(
        encoding="utf-8"
    )
    page = src[src.index("const AUTH_ERRORS") : src.index("// ---- 训练记录器")]
    for path in (
        '"/password/login"',
        '"/password/register"',
        '"/password/reset"',
        '"/email/verify"',
        '"/email/login"',
        '"/iron/api/auth/options"',
    ):
        assert path in page, path
    assert (
        "邮件服务还没配好，暂时不能注册。" in page
        and "两次输的密码不一样" in page
        and "这个邮箱已经注册过，直接登录" in page
    )
    assert "you@mirobody.ai" not in page and "111111" not in page  # 不再预填演示账号


def _pw_client(monkeypatch: pytest.MonkeyPatch, row: dict[str, Any] | None) -> tuple[Any, list[Any]]:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from mirobody.server.auth import verify_token

    from ironm_agent import web_password

    seen: list[Any] = []

    async def query(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        seen.append((sql, params))
        if sql.lstrip().startswith("UPDATE"):
            return [{"id": 5}]
        return [row] if row is not None else []

    monkeypatch.setattr(web_password, "_query", query)
    app = FastAPI()
    app.include_router(web_password.router)
    app.dependency_overrides[verify_token] = lambda: "5"
    return TestClient(app), seen


def test_set_password_for_a_code_only_account(monkeypatch: pytest.MonkeyPatch) -> None:
    """§174：以前用验证码建的账号没有密码，登录后直接设一个。"""
    c, seen = _pw_client(monkeypatch, {"has": False, "ok": False})
    assert c.get("/iron/api/auth/password").json() == {"has_password": False}
    r = c.put("/iron/api/auth/password", json={"password": "short"})
    assert r.status_code == 422 and r.json()["detail"] == "密码至少 8 位"
    assert not any(s.lstrip().startswith("UPDATE") for s, _ in seen)
    r = c.put("/iron/api/auth/password", json={"password": "newpass88"})
    assert r.json() == {"has_password": True}
    sql, params = seen[-1]
    assert "crypt(:password, gen_salt('bf', 12))" in sql and params == {"id": 5, "password": "newpass88"}


def test_change_password_needs_the_current_one(monkeypatch: pytest.MonkeyPatch) -> None:
    c, seen = _pw_client(monkeypatch, {"has": True, "ok": False})
    r = c.put("/iron/api/auth/password", json={"password": "newpass88", "current": "wrong"})
    assert r.status_code == 422 and r.json()["detail"] == "原来的密码不对"
    assert not any(s.lstrip().startswith("UPDATE") for s, _ in seen)  # 旧密码不对：不改
    c, seen = _pw_client(monkeypatch, {"has": True, "ok": True})
    assert c.put("/iron/api/auth/password", json={"password": "newpass88", "current": "oldpass88"}).json() == {"has_password": True}
    assert seen[0][1] == {"id": 5, "current": "oldpass88"}  # 旧密码交给数据库核对
