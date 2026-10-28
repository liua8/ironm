"""夯拉榜：所有人可见、能添加、按评分排名（spec [2026-10-23] §60、§66）。不连数据库。"""

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.exercises import library
from ironm_agent.meals import Macros, Meal, MealBook
from ironm_agent.tier import CATEGORY_NAMES, TIERS, Item, TierBook, shrunk, similar

BENCH = next(x for x in library().exercises if x.name == "杠铃卧推")


def client(
    user: str = "42", tiers: TierBook | None = None
) -> tuple[TestClient, TierBook, MealBook]:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more, web_tier

    tiers, meals = tiers or TierBook(), MealBook()
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: user
    app.dependency_overrides[web_tier.tier_store] = lambda: tiers
    app.dependency_overrides[web_more.meal_store] = lambda: meals
    return TestClient(app), tiers, meals


def vote(c: TestClient, key: str, tier: str, category: str = "move:胸") -> dict[str, Any]:
    r = c.put("/iron/api/tier", json={"category": category, "key": key, "tier": tier})
    assert r.status_code == 200, r.text
    return r.json()


def item(board: dict[str, Any], key: str) -> dict[str, Any]:
    return next(x for x in board["items"] if x["key"] == key)


def test_categories_and_five_tiers() -> None:
    assert [n for _, n in TIERS] == ["夯", "顶级", "人上人", "NPC", "拉"]
    assert set(CATEGORY_NAMES) == {
        f"move:{p}" for p in ("胸", "背", "肩", "手臂", "核心", "腿臀")
    } | {"supplement", "food"}


def test_move_board_lists_the_library_moves_of_that_part() -> None:
    c, _, _ = client()
    got = c.get("/iron/api/tier", params={"category": "move:胸"}).json()
    assert {x["name"] for x in got["items"]} == {
        x.name for x in library().exercises if x.part == "胸"
    }
    assert all(x["tier"] == "" and x["votes"] == 0 for x in got["items"]) and not got["custom"]
    assert got["min_votes"] == 3
    assert c.get("/iron/api/tier", params={"category": "move:脚"}).status_code == 422


def test_votes_from_everyone_make_the_community_tier() -> None:
    tiers = TierBook()
    a, b, d = (client(u, tiers)[0] for u in ("1", "2", "3"))
    vote(a, BENCH.id, "hang")
    got = vote(b, BENCH.id, "top")
    x = item(got, BENCH.id)
    # 两票：平均 4.5，还在待评（不到 3 票不进五档）
    assert x["votes"] == 2 and x["mean"] == 4.5 and x["tier"] == "" and x["mine"] == "top"
    x = item(vote(d, BENCH.id, "elite"), BENCH.id)
    assert x["votes"] == 3 and x["mean"] == 4.0 and x["tier"] == "top"
    assert x["counts"] == {"hang": 1, "top": 1, "elite": 1, "npc": 0, "la": 0}
    seen = item(
        client("9", tiers)[0].get("/iron/api/tier", params={"category": "move:胸"}).json(), BENCH.id
    )
    assert seen["votes"] == 3 and seen["mine"] == ""  # 别人看得到汇总，自己没投


def test_change_and_withdraw_vote_count_once() -> None:
    tiers = TierBook()
    a = client("1", tiers)[0]
    vote(a, BENCH.id, "hang")
    x = item(vote(a, BENCH.id, "la"), BENCH.id)
    assert x["votes"] == 1 and x["mean"] == 1.0 and x["mine"] == "la"
    x = item(vote(a, BENCH.id, ""), BENCH.id)
    assert x["votes"] == 0 and x["mean"] is None and x["mine"] == ""


def test_within_a_tier_fewer_votes_rank_lower() -> None:
    assert shrunk(5.0, 3) < shrunk(4.8, 20)  # 3 个满分不压过 20 人的 4.8
    tiers = TierBook()
    moves = [x.id for x in library().exercises if x.part == "胸"][:2]
    for u in range(1, 4):
        vote(client(str(u), tiers)[0], moves[0], "hang")
    for u in range(1, 11):
        vote(client(str(u), tiers)[0], moves[1], "hang" if u > 1 else "top")
    got = client("9", tiers)[0].get("/iron/api/tier", params={"category": "move:胸"}).json()
    ranked = [x["key"] for x in got["items"] if x["tier"] == "hang"]
    assert ranked == [moves[1], moves[0]]  # 10 票 4.9 排在 3 票 5.0 前面


def test_add_items_merges_same_name_and_asks_for_similar() -> None:
    tiers = TierBook()
    a, b = client("1", tiers)[0], client("2", tiers)[0]
    got = a.post(
        "/iron/api/tier/items", json={"category": "supplement", "name": "乳清蛋白粉"}
    ).json()
    key = got["key"]
    assert key and [x["name"] for x in got["items"]] == ["乳清蛋白粉"]
    same = b.post(
        "/iron/api/tier/items", json={"category": "supplement", "name": " 乳清 蛋白粉 "}
    ).json()
    assert same["key"] == key and len(same["items"]) == 1  # 空格不同：用已有的
    near = b.post(
        "/iron/api/tier/items", json={"category": "supplement", "name": "乳清蛋白"}
    ).json()
    assert near["key"] is None and [x["name"] for x in near["similar"]] == ["乳清蛋白粉"]
    assert len(near["items"]) == 1  # 没确认就不新建
    forced = b.post(
        "/iron/api/tier/items", json={"category": "supplement", "name": "乳清蛋白", "force": True}
    ).json()
    assert forced["key"] and len(forced["items"]) == 2
    vote(b, key, "top", "supplement")
    assert (
        item(a.get("/iron/api/tier", params={"category": "supplement"}).json(), key)["votes"] == 1
    )


def test_daily_add_limit_counts_both_categories() -> None:
    a, tiers, _ = client("1")
    for i in range(10):
        cat = "food" if i % 2 else "supplement"
        r = a.post(
            "/iron/api/tier/items",
            json={"category": cat, "name": f"条目{chr(0x4E00 + i * 37)}{i}", "force": True},
        )
        assert r.status_code == 200, r.text
    r = a.post("/iron/api/tier/items", json={"category": "food", "name": "第十一个", "force": True})
    assert r.status_code == 422 and "每天最多添加 10 个" in r.json()["detail"]
    old = Item("food", "c:昨天的", "昨天的", "2", datetime.now().astimezone() - timedelta(days=1))
    asyncio.run(tiers.add(old))
    b = client("2", tiers)[0]
    assert (
        b.post(
            "/iron/api/tier/items", json={"category": "food", "name": "今天的", "force": True}
        ).status_code
        == 200
    )


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ({"category": "food", "name": "   "}, "名字不能为空"),
        ({"category": "food", "name": "很" * 31}, "名字最多 30 个字"),
        ({"category": "move:胸", "name": "自创卧推"}, "动作类的条目来自动作库"),
        ({"category": "drink", "name": "可乐"}, "没有这个类别"),
    ],
)
def test_bad_items_are_rejected(body: dict[str, str], message: str) -> None:
    c, _, _ = client()
    r = c.post("/iron/api/tier/items", json=body)
    assert r.status_code == 422 and message in r.json()["detail"]


def test_bad_votes_are_rejected() -> None:
    c, _, _ = client()
    for body in (
        {"category": "move:胸", "key": "no-such-move", "tier": "hang"},
        {"category": "move:胸", "key": BENCH.id, "tier": "best"},
        {"category": "food", "key": "c:没加过", "tier": "hang"},
    ):
        assert c.put("/iron/api/tier", json=body).status_code == 422


def test_three_reports_hide_an_item_for_everyone() -> None:
    tiers = TierBook()
    a = client("1", tiers)[0]
    key = a.post("/iron/api/tier/items", json={"category": "food", "name": "奇怪的东西"}).json()[
        "key"
    ]
    vote(a, key, "la", "food")
    body = {"category": "food", "key": key}
    for _ in range(2):
        assert (
            len(a.post("/iron/api/tier/report", json=body).json()["items"]) == 1
        )  # 同一人两次只算一次
    client("2", tiers)[0].post("/iron/api/tier/report", json=body)
    gone = client("3", tiers)[0].post("/iron/api/tier/report", json=body).json()
    assert gone["items"] == []
    assert (
        client("4", tiers)[0].get("/iron/api/tier", params={"category": "food"}).json()["items"]
        == []
    )
    again = a.post("/iron/api/tier/items", json={"category": "food", "name": "奇怪的东西"})
    assert again.status_code == 422 and "隐藏" in again.json()["detail"]
    assert (
        a.post("/iron/api/tier/report", json={"category": "move:胸", "key": BENCH.id}).status_code
        == 422
    )


def test_responses_never_name_voters_or_adders() -> None:
    tiers = TierBook()
    a = client("voter-secret-1", tiers)[0]
    key = a.post("/iron/api/tier/items", json={"category": "food", "name": "燕麦"}).json()["key"]
    got = vote(a, key, "hang", "food")
    assert "voter-secret-1" not in str(got)
    assert set(got["items"][0]) == {
        "key",
        "name",
        "votes",
        "mean",
        "score",
        "tier",
        "counts",
        "mine",
    }


def test_similar_matches_contained_or_close_names() -> None:
    now = datetime.now().astimezone()
    items = [Item("food", "c:" + n, n, "1", now) for n in ("鸡胸肉", "牛肉面", "燕麦片")]
    assert [x.name for x in similar("鸡胸", items)] == ["鸡胸肉"]
    assert [x.name for x in similar("燕麦 片", items)] == ["燕麦片"]
    assert similar("可乐", items) == []


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


def test_logs_do_not_carry_item_names_or_voters(caplog: pytest.LogCaptureFixture) -> None:
    c, _, _ = client("voter-secret-2")
    with caplog.at_level(logging.DEBUG):
        key = c.post(
            "/iron/api/tier/items", json={"category": "food", "name": "秘密的夜宵"}
        ).json()["key"]
        vote(c, key, "hang", "food")
        c.post("/iron/api/tier/report", json={"category": "food", "key": key})
    assert "秘密的夜宵" not in caplog.text and "voter-secret-2" not in caplog.text


def test_db_version_writes_votes_without_names(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import tier

    seen: list[tuple[str, dict[str, Any]]] = []

    async def fake(sql: str, params: dict[str, Any], log_sql: bool = True) -> list[dict[str, Any]]:
        seen.append((sql, params))
        return []

    monkeypatch.setattr("mirobody.utils.db.execute_query", fake)
    store = tier.PgTier()
    asyncio.run(store.vote("42", "food", "c:燕麦", "hang"))
    asyncio.run(store.vote("42", "food", "c:燕麦", ""))
    writes = [s for s, _ in seen if s.lstrip().startswith(("INSERT", "DELETE"))]
    assert "ON CONFLICT (user_id, category, key)" in writes[0] and writes[1].startswith("DELETE")
    assert all(not s.lstrip().startswith("CREATE") or "ironm_tier_" in s for s, _ in seen)


def test_nav_has_tier_tab_and_avatar_into_personal_center() -> None:
    """§65：底部第四个是夯，个人中心从右上角头像进；页面里不再让人去「我的」。"""
    from pathlib import Path

    web = Path(__file__).resolve().parents[1] / "ironm_agent" / "web"
    html, js = (web / "index.html").read_text(), (web / "app.js").read_text()
    assert 'href="#tier" data-tab="tier"' in html and 'data-tab="me"' not in html
    assert 'id="avatar" href="#me"' in html
    assert "「我的」" not in js and "#me/profile" not in js and "#me/data" not in js
    assert "const tierHref = (cat, mine = false) => `#tier/" in js
