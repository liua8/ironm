"""账号与隐私（spec [2026-10-23] §180）：导出我的数据、注销账号。"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent import web_account

TABLES = [
    {"t": "ironm_meal", "c": "id", "d": "text"},
    {"t": "ironm_meal", "c": "user_id", "d": "text"},
    {"t": "ironm_meal", "c": "day", "d": "date"},
    {"t": "ironm_meal", "c": "content", "d": "text"},
    {"t": "ironm_meal", "c": "photo", "d": "text"},
    {"t": "ironm_meal", "c": "photo_mime", "d": "text"},
    {"t": "ironm_profile", "c": "user_id", "d": "text"},
    {"t": "ironm_profile", "c": "height_cm", "d": "double precision"},
    {"t": "ironm_user_model", "c": "user_id", "d": "text"},
    {"t": "ironm_user_model", "c": "content", "d": "text"},
    {"t": "ironm_turn_trace", "c": "user_id", "d": "text"},
]


def _client(
    monkeypatch: pytest.MonkeyPatch, email: str = "me@x.com", svc: Any = "svc"
) -> tuple[TestClient, list[Any], list[Any]]:
    from mirobody.server.auth import verify_token
    from mirobody.user import user as mu

    seen: list[Any] = []
    closed: list[Any] = []

    async def query(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
        seen.append((sql, params))
        if "information_schema" in sql:
            return TABLES
        if sql.startswith("DELETE"):
            return [{"?": 1}, {"?": 1}]
        if "ironm_meal" in sql:
            return [{"id": "m1", "user_id": "5", "content": '{"name": "米饭"}'}]
        if "ironm_profile" in sql:
            return [{"user_id": "5", "height_cm": 172.0}]
        return []

    async def get_user(**kw: Any) -> dict[str, Any] | None:
        return {"id": kw["user_id"], "email": email}

    async def del_user(pool: Any, uid: int) -> str | None:
        closed.append(uid)
        return None

    monkeypatch.setattr(web_account, "_query", query)
    monkeypatch.setattr(mu, "get_user", get_user)
    monkeypatch.setattr(mu, "del_user", del_user)
    monkeypatch.setattr(
        web_account, "_users", lambda r: None if svc is None else SimpleNamespace(_db_pool="pool")
    )
    app = FastAPI()
    app.include_router(web_account.router)
    app.dependency_overrides[verify_token] = lambda: "5"
    return TestClient(app), seen, closed


def test_export_is_mine_decrypted_without_keys_photos_or_traces(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, seen, _ = _client(monkeypatch)
    r = client.get("/iron/api/export")
    assert r.status_code == 200
    assert 'attachment; filename="ironm-' in r.headers["content-disposition"]
    body = r.json()
    assert body["data"] == {
        "meal": [{"id": "m1", "user_id": "5", "content": {"name": "米饭"}}],
        "profile": [{"user_id": "5", "height_cm": 172.0}],
    }
    selects = [(s, p) for s, p in seen if s.startswith("SELECT") and "information_schema" not in s]
    assert all(p == {"uid": "5"} and "WHERE user_id = :uid" in s for s, p in selects)
    meal = next(s for s, _ in selects if "ironm_meal" in s)
    assert 'decrypt_content("content")' in meal and "photo" not in meal
    assert not any("ironm_user_model" in s or "ironm_turn_trace" in s for s, _ in selects)
    assert (
        any("模型密钥" in x for x in body["not_included"])
        and "/api/user/data-export" in body["health_records"]
    )


def test_delete_needs_the_account_email(monkeypatch: pytest.MonkeyPatch) -> None:
    client, seen, closed = _client(monkeypatch)
    r = client.post("/iron/api/account/delete", json={"confirm": "other@x.com"})
    assert r.status_code == 422 and "邮箱" in r.json()["detail"]
    assert not any(s.startswith("DELETE") for s, _ in seen) and closed == []


def test_delete_removes_my_rows_in_every_table_then_closes_the_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, seen, closed = _client(monkeypatch)
    r = client.post("/iron/api/account/delete", json={"confirm": " Me@X.com "})
    assert r.status_code == 200 and r.json() == {"ok": True, "deleted_rows": 8}
    deletes = [(s, p) for s, p in seen if s.startswith("DELETE")]
    assert {s.split('"')[1] for s, _ in deletes} == {
        "ironm_meal",
        "ironm_profile",
        "ironm_user_model",
        "ironm_turn_trace",
    }
    assert all(p == {"uid": "5"} and "WHERE user_id = :uid" in s for s, p in deletes)
    assert closed == [5]


def test_delete_does_nothing_when_the_account_service_is_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, seen, closed = _client(monkeypatch, svc=None)
    r = client.post("/iron/api/account/delete", json={"confirm": "me@x.com"})
    assert r.status_code == 503
    assert not any(s.startswith("DELETE") for s, _ in seen) and closed == []


def test_web_pages_and_app_text_match() -> None:
    """隐私政策、用户协议不登录能看、注册时能点开、「我」里有一组；App 的文字和网页一字不差。"""
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    js = (root / "ironm_agent" / "web" / "app.js").read_text(encoding="utf-8")
    ts = (root / "app" / "src" / "features" / "me" / "legal.ts").read_text(encoding="utf-8")
    assert 'const legal = { "#privacy": "privacy", "#terms": "terms" }[location.hash];' in js
    assert "注册即表示你同意" in js and 'href: "#terms"' in js and 'href: "#privacy"' in js
    for row in (
        '"导出我的数据"',
        '"隐私政策", "", "#privacy"',
        '"用户协议", "", "#terms"',
        '"注销账号"',
    ):
        assert row in js, row
    assert (
        '"/iron/api/export"' in js
        and '"/api/user/data-export"' in js
        and '"/iron/api/account/delete"' in js
    )

    def body(src: str) -> str:
        start = src.index("privacy: [")
        return src[start : src.index("\n};", start)]

    assert body(js) == body(ts)
    assert (
        'LEGAL_DATE = "' in js
        and js.split('LEGAL_DATE = "')[1][:10] == ts.split('LEGAL_DATE = "')[1][:10]
    )
