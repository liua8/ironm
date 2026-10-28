"""夯：个人的从夯到拉榜单（spec [2026-10-23] §60）。不连数据库。"""

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.exercises import library
from ironm_agent.meals import Macros, Meal, MealBook
from ironm_agent.tier import CATEGORY_NAMES, TIERS, TierBook, row_id


def client(user: str = "42") -> tuple[TestClient, TierBook, MealBook]:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more, web_tier

    tiers, meals = TierBook(), MealBook()
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: user
    app.dependency_overrides[web_tier.tier_store] = lambda: tiers
    app.dependency_overrides[web_more.meal_store] = lambda: meals
    return TestClient(app), tiers, meals


def _tiers(board: dict[str, Any]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for x in board["items"]:
        out.setdefault(x["tier"] or "-", []).append(x["name"])
    return out


def test_categories_and_five_tiers() -> None:
    assert [n for _, n in TIERS] == ["夯", "顶级", "人上人", "NPC", "拉"]
    assert set(CATEGORY_NAMES) == {
        f"move:{p}" for p in ("胸", "背", "肩", "手臂", "核心", "腿臀")
    } | {"supplement", "food"}


def test_move_board_lists_the_library_moves_of_that_part() -> None:
    c, _, _ = client()
    got = c.get("/iron/api/tier", params={"category": "move:胸"}).json()
    names = [x["name"] for x in got["items"]]
    assert names == [x.name for x in library().exercises if x.part == "胸"]
    assert all(x["tier"] == "" for x in got["items"]) and not got["custom"]
    assert [t["name"] for t in got["tiers"]] == ["夯", "顶级", "人上人", "NPC", "拉"]
    assert c.get("/iron/api/tier", params={"category": "move:脚"}).status_code == 422


def test_set_move_tier_and_back_to_unranked() -> None:
    c, tiers, _ = client()
    bench = next(x for x in library().exercises if x.name == "杠铃卧推")
    got = c.put(
        "/iron/api/tier", json={"category": "move:胸", "key": bench.id, "tier": "hang"}
    ).json()
    assert "杠铃卧推" in _tiers(got)["hang"]
    got = c.put(
        "/iron/api/tier", json={"category": "move:胸", "key": bench.id, "tier": "la"}
    ).json()
    assert "杠铃卧推" in _tiers(got)["la"] and "杠铃卧推" not in _tiers(got).get("hang", [])
    got = c.put("/iron/api/tier", json={"category": "move:胸", "key": bench.id, "tier": ""}).json()
    assert "杠铃卧推" in _tiers(got)["-"] and not tiers.data["42"]
    # 别的部位的动作、不存在的档都不行
    squat = next(x for x in library().exercises if x.name == "杠铃深蹲")
    assert (
        c.put(
            "/iron/api/tier", json={"category": "move:胸", "key": squat.id, "tier": "hang"}
        ).status_code
        == 422
    )
    assert (
        c.put(
            "/iron/api/tier", json={"category": "move:胸", "key": bench.id, "tier": "best"}
        ).status_code
        == 422
    )


def test_custom_items_add_rank_delete() -> None:
    c, _, _ = client()
    got = c.post(
        "/iron/api/tier/items", json={"category": "supplement", "name": " 乳清 蛋白粉 "}
    ).json()
    key = got["key"]
    assert got["custom"] and [x["name"] for x in got["items"]] == ["乳清 蛋白粉"]
    again = c.post(
        "/iron/api/tier/items", json={"category": "supplement", "name": "乳清 蛋白粉"}
    ).json()
    assert len(again["items"]) == 1  # 不重复加
    got = c.put("/iron/api/tier", json={"category": "supplement", "key": key, "tier": "top"}).json()
    assert _tiers(got) == {"top": ["乳清 蛋白粉"]}
    got = c.request(
        "DELETE", "/iron/api/tier/items", params={"category": "supplement", "key": key}
    ).json()
    assert got["items"] == []
    assert (
        c.request(
            "DELETE", "/iron/api/tier/items", params={"category": "supplement", "key": key}
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"category": "food", "name": "   "}, "不能为空"),
        ({"category": "food", "name": "很" * 31}, "最多 30"),
        ({"category": "move:胸", "name": "自创动作"}, "动作库"),
        ({"category": "drink", "name": "可乐"}, "没有这个类别"),
    ],
)
def test_bad_items_are_rejected(body: dict[str, str], message: str) -> None:
    c, _, _ = client()
    got = c.post("/iron/api/tier/items", json=body)
    assert got.status_code == 422 and message in got.json()["detail"]


def test_ranking_unknown_custom_item_or_deleting_a_move_is_refused() -> None:
    c, _, _ = client()
    assert (
        c.put(
            "/iron/api/tier", json={"category": "food", "key": "c:鸡胸肉", "tier": "hang"}
        ).status_code
        == 422
    )
    bench = next(x for x in library().exercises if x.part == "胸")
    assert (
        c.request(
            "DELETE", "/iron/api/tier/items", params={"category": "move:胸", "key": bench.id}
        ).status_code
        == 422
    )


def test_only_own_board_is_seen() -> None:
    c, tiers, _ = client("42")
    c.post("/iron/api/tier/items", json={"category": "food", "name": "鸡胸肉"})
    other, _, _ = client("7")
    other.app.dependency_overrides[
        __import__("ironm_agent.web_tier", fromlist=["x"]).tier_store
    ] = lambda: tiers  # type: ignore[attr-defined]
    assert other.get("/iron/api/tier", params={"category": "food"}).json()["items"] == []
    # 行编号由人、类别、条目算出，不含原文
    rid = row_id("42", "food", "c:鸡胸肉")
    assert "鸡胸肉" not in rid and len(rid) == 32


def test_food_suggest_lists_frequent_meals_not_on_the_board() -> None:
    c, _, meals = client()
    today = date.today()
    m = Macros(kcal=500, protein_g=30, carbs_g=50, fat_g=10)
    for i, name in enumerate(
        ["鸡胸肉沙拉", "鸡胸肉沙拉", "牛肉面", "鸡胸肉沙拉", "牛肉面", "燕麦"]
    ):
        asyncio.run(meals.add("42", today - timedelta(days=i), Meal(name=name, macros=m)))
    asyncio.run(meals.add("42", today - timedelta(days=40), Meal(name="很久以前的", macros=m)))
    asyncio.run(meals.add("7", today, Meal(name="别人的", macros=m)))
    c.post("/iron/api/tier/items", json={"category": "food", "name": "燕麦"})
    assert c.get("/iron/api/tier/food-suggest").json()["names"] == ["鸡胸肉沙拉", "牛肉面"]


def test_logs_do_not_carry_item_names(caplog: pytest.LogCaptureFixture) -> None:
    c, _, _ = client()
    with caplog.at_level(logging.DEBUG):
        c.post("/iron/api/tier/items", json={"category": "food", "name": "秘密的夜宵"})
    assert "秘密的夜宵" not in caplog.text


def test_db_version_encrypts_item_names(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import tier

    seen: list[tuple[str, dict[str, Any]]] = []

    async def fake(sql: str, params: dict[str, Any], log_sql: bool = True) -> list[dict[str, Any]]:
        seen.append((sql, params))
        return []

    monkeypatch.setattr("mirobody.utils.db.execute_query", fake)
    store = tier.PgTier()
    asyncio.run(store.put("42", tier.Row("food", "c:秘密的夜宵", "秘密的夜宵", "la")))
    sql, params = next((s, p) for s, p in seen if s.lstrip().startswith("INSERT"))
    assert "encrypt_content(:content)" in sql and "秘密的夜宵" not in sql
    assert "秘密的夜宵" not in params["id"] and set(params) == {
        "id",
        "uid",
        "cat",
        "tier",
        "content",
    }
