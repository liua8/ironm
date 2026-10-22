"""“我的记忆”接口：查看、修改、确认、删除、暂停；只能动自己的记忆。"""

import asyncio
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.memory_store import Change, Item, MemoryBook

T0 = datetime(2026, 10, 20, tzinfo=UTC)


def client(user: str = "42") -> tuple[TestClient, MemoryBook]:
    from mirobody.server.auth import verify_token

    from ironm_agent import web

    book = MemoryBook()
    items = [
        Item("k", "injury", "左膝有旧伤", "我左膝有旧伤", "said", "active", T0, T0),
        Item("p", "schedule", "是上班族", "下班后才能练", "inferred", "pending", T0, T0),
    ]
    asyncio.run(book.apply("42", [Change("insert", item=x) for x in items]))
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: user
    app.dependency_overrides[web.memory_store] = lambda: book
    return TestClient(app), book


def test_list_groups_and_labels() -> None:
    c, _ = client()
    data: dict[str, Any] = c.get("/iron/api/memory").json()
    assert data["paused"] is False and data["categories"]["injury"] == "伤病与身体状况"
    assert {x["id"]: x["origin_label"] for x in data["items"]} == {"k": "你说的", "p": "系统推断"}


def test_edit_confirm_delete_and_pause() -> None:
    c, book = client()
    r = c.put("/iron/api/memory/k", json={"content": "右膝有旧伤"})
    assert r.status_code == 200 and r.json()["origin_label"] == "你改过的"
    assert c.post("/iron/api/memory/p/confirm").json()["status"] == "active"
    assert c.post("/iron/api/memory/p/confirm").status_code == 404  # 已经确认过
    assert c.delete("/iron/api/memory/k").status_code == 200
    assert [x["id"] for x in c.get("/iron/api/memory").json()["items"]] == ["p"]
    assert c.put("/iron/api/memory-settings", json={"paused": True}).json() == {"paused": True}
    assert asyncio.run(book.paused("42"))


def test_bad_input_and_other_peoples_memory() -> None:
    c, _ = client()
    assert c.put("/iron/api/memory/k", json={"content": ""}).status_code == 422
    assert c.put("/iron/api/memory/k", json={"content": "x" * 61}).status_code == 422
    assert c.put("/iron/api/memory/k", json={"content": "x", "status": "active"}).status_code == 422
    other, _ = client(user="7")
    assert other.get("/iron/api/memory").json()["items"] == []
    assert other.delete("/iron/api/memory/k").status_code == 404
    assert other.put("/iron/api/memory/k", json={"content": "改别人的"}).status_code == 404
