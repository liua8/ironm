"""夯榜改成排行榜（spec [2026-10-23] §72）：六个榜、前 10、名次变化、评论、热搜、§66 投票照用。不连数据库。"""

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.exercises import library
from ironm_agent.rank import BOARD_NAMES, RankBook, hot, ranked, record_search, week_of
from ironm_agent.tier import Item, TierBook

BENCH = next(x for x in library().exercises if x.name == "杠铃卧推")


def client(
    user: str = "42", tiers: TierBook | None = None, rank: RankBook | None = None
) -> tuple[TestClient, TierBook, RankBook]:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_rank, web_tier

    tiers, rank = tiers or TierBook(), rank or RankBook()
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: user
    app.dependency_overrides[web_tier.tier_store] = lambda: tiers
    app.dependency_overrides[web_rank.rank_store] = lambda: rank
    return TestClient(app), tiers, rank


def as_user(tiers: TierBook, rank: RankBook, user: str) -> TestClient:
    return client(user, tiers, rank)[0]


def vote(c: TestClient, board: str, key: str, tier: str) -> dict[str, Any]:
    r = c.put("/iron/api/rank/vote", json={"board": board, "key": key, "tier": tier})
    assert r.status_code == 200, r.text
    return r.json()


def board(c: TestClient, name: str, **kw: str) -> dict[str, Any]:
    r = c.get("/iron/api/rank/board", params={"board": name, **kw})
    assert r.status_code == 200, r.text
    return r.json()


def row(b: dict[str, Any], name: str) -> dict[str, Any]:
    return next(x for x in b["items"] if x["name"] == name)


def votes_for(tiers: TierBook, rank: RankBook, board_: str, key: str, tiers_: list[str]) -> None:
    for i, t in enumerate(tiers_):
        vote(as_user(tiers, rank, f"u{i}"), board_, key, t)


def test_six_boards_and_starter_entries() -> None:
    assert list(BOARD_NAMES.values()) == [
        "动作榜",
        "训练计划榜",
        "健身餐榜",
        "补剂榜",
        "蛋白粉榜",
        "器材榜",
    ]
    c, _, _ = client()
    got = c.get("/iron/api/rank").json()
    assert [x["board"] for x in got["boards"]] == list(BOARD_NAMES)
    for name in ("meal", "supplement", "protein", "gear"):  # 开榜就有起步条目，都还没票
        items = board(c, name)["items"]
        assert len(items) >= 8 and all(x["votes"] == 0 and x["rank"] is None for x in items)
    assert "分离乳清" in {x["name"] for x in board(c, "protein")["items"]}
    assert {x["name"] for x in board(c, "move")["items"]} >= {x.name for x in library().exercises}
    for gone in ("food", "fat", "gain"):  # §80 减脂餐、增肌餐合并成健身餐
        assert c.get("/iron/api/rank/board", params={"board": gone}).status_code == 422


def test_three_votes_put_an_entry_on_the_board_ranked_by_shrunk_score() -> None:
    c, tiers, rank = client()
    votes_for(tiers, rank, "gear", "c:可调哑铃", ["hang", "hang", "top"])
    votes_for(tiers, rank, "gear", "c:弹力带", ["top", "top", "top", "top", "top"])
    votes_for(tiers, rank, "gear", "c:跳绳", ["hang", "hang"])
    b = board(c, "gear")
    dumbbell, band, rope = row(b, "可调哑铃"), row(b, "弹力带"), row(b, "跳绳")
    assert dumbbell["rank"] == 1 and band["rank"] == 2 and rope["rank"] is None  # 不到 3 票待评
    assert dumbbell["tier"] == "hang" and dumbbell["mean"] == 4.7 and band["tier"] == "top"
    assert b["min_votes"] == 3 and b["people"] == 5
    top = next(x for x in c.get("/iron/api/rank").json()["boards"] if x["board"] == "gear")["top"]
    assert [x["name"] for x in top] == ["可调哑铃", "弹力带"]  # 首页只列上榜的，最多 10 个


def test_vote_change_and_withdraw() -> None:
    c, _, _ = client()
    got = vote(c, "protein", "c:分离乳清", "top")
    assert got["item"]["mine"] == "top" and got["item"]["counts"]["top"] == 1
    got = vote(c, "protein", "c:分离乳清", "la")
    assert got["item"]["mine"] == "la" and got["item"]["votes"] == 1
    got = vote(c, "protein", "c:分离乳清", "")
    assert got["item"]["mine"] == "" and got["item"]["votes"] == 0
    bad = c.put("/iron/api/rank/vote", json={"board": "protein", "key": "c:分离乳清", "tier": "x"})
    assert bad.status_code == 422
    nope = c.put("/iron/api/rank/vote", json={"board": "protein", "key": "c:不存在", "tier": "top"})
    assert nope.status_code == 422


def test_every_board_takes_additions_same_name_is_not_duplicated() -> None:
    c, tiers, _ = client()
    for name in BOARD_NAMES:
        r = c.post(
            "/iron/api/rank/items", json={"board": name, "name": f"测试条目{name}", "force": True}
        )
        if name == "plan":  # 训练计划只来自方案库（§80）
            assert r.status_code == 422 and "不能添加" in r.text
            continue
        assert r.status_code == 200 and r.json()["key"], r.text
    again = c.post("/iron/api/rank/items", json={"board": "gear", "name": " 可调 哑铃 "}).json()
    assert again == {"key": "c:可调哑铃", "similar": []}  # 同名的用已有的
    near = c.post("/iron/api/rank/items", json={"board": "gear", "name": "可调哑铃套装"}).json()
    assert near["key"] is None and near["similar"][0]["name"] == "可调哑铃"
    added = c.post(
        "/iron/api/rank/items", json={"board": "move", "name": "壶铃摇摆变式", "force": True}
    )
    assert added.json()["key"].startswith("c:") and "壶铃摇摆变式" not in {
        x.name for x in library().exercises
    }
    assert asyncio.run(tiers.items("move"))  # 动作榜加的只在榜上，不进动作库


def test_new_on_board_sort_uses_added_time() -> None:
    c, _, _ = client()
    c.post("/iron/api/rank/items", json={"board": "meal", "name": "牛油果虾仁碗", "force": True})
    b = board(c, "meal")
    assert row(b, "牛油果虾仁碗")["added"] and not row(b, "番茄龙利鱼")["added"]


def test_comments_like_sort_delete_report_and_daily_limit() -> None:
    c, tiers, rank = client()
    key = "c:可调哑铃"
    got = c.post(
        "/iron/api/rank/comments", json={"board": "gear", "key": key, "text": "家里练够用"}
    ).json()
    mine = got["comments"][0]
    assert mine["mine"] and mine["nick"] and "user_id" not in mine and got["item"]["key"] == key
    other = as_user(tiers, rank, "u2")
    other.post("/iron/api/rank/comments", json={"board": "gear", "key": key, "text": "换重量快"})
    theirs = next(
        x
        for x in c.get("/iron/api/rank/item", params={"board": "gear", "key": key}).json()[
            "comments"
        ]
        if not x["mine"]
    )
    assert (
        c.post(f"/iron/api/rank/comments/{theirs['id']}/like", json={"on": True}).status_code == 200
    )
    listed = c.get("/iron/api/rank/item", params={"board": "gear", "key": key}).json()["comments"]
    assert listed[0]["id"] == theirs["id"] and listed[0]["likes"] == 1 and listed[0]["liked"]
    c.post(f"/iron/api/rank/comments/{theirs['id']}/like", json={"on": False})
    assert (
        c.get("/iron/api/rank/item", params={"board": "gear", "key": key}).json()["comments"][0][
            "likes"
        ]
        == 0
    )
    assert c.delete(f"/iron/api/rank/comments/{theirs['id']}").status_code == 422  # 只能删自己的
    assert c.delete(f"/iron/api/rank/comments/{mine['id']}").status_code == 200
    for u in ("a", "b", "c"):
        as_user(tiers, rank, u).post(f"/iron/api/rank/comments/{theirs['id']}/report")
    assert (
        c.get("/iron/api/rank/item", params={"board": "gear", "key": key}).json()["comments"] == []
    )
    long = c.post("/iron/api/rank/comments", json={"board": "gear", "key": key, "text": "长" * 201})
    assert long.status_code == 422
    for i in range(30):  # 删掉的那条不算
        c.post("/iron/api/rank/comments", json={"board": "gear", "key": key, "text": f"第{i}条"})
    over = c.post("/iron/api/rank/comments", json={"board": "gear", "key": key, "text": "再来一条"})
    assert over.status_code == 422 and "30" in over.json()["detail"]


def test_banned_words_and_claims_on_supplements_are_not_posted() -> None:
    c, _, _ = client()
    for text in ("加微信 abc123", "联系 13812345678", "傻逼"):
        r = c.post("/iron/api/rank/comments", json={"board": "gear", "key": "c:跳绳", "text": text})
        assert r.status_code == 422
    claim = c.post(
        "/iron/api/rank/comments", json={"board": "supplement", "key": "c:镁", "text": "能治失眠"}
    )
    assert claim.status_code == 422 and "疗效" in claim.json()["detail"]
    ok = c.post(
        "/iron/api/rank/comments", json={"board": "gear", "key": "c:跳绳", "text": "能治懒"}
    )
    assert ok.status_code == 200  # 只有补剂、蛋白粉不写疗效
    b = board(c, "supplement")
    assert b["no_claims"] and "不代表平台观点" in b["disclaimer"]


def test_nick_shown_instead_of_account() -> None:
    c, _, _ = client()
    nick = c.get("/iron/api/rank/nick").json()["nick"]
    assert nick and nick == c.get("/iron/api/rank/nick").json()["nick"]  # 随机给一个，之后不变
    assert c.put("/iron/api/rank/nick", json={"nick": "深蹲爱好者"}).json() == {
        "nick": "深蹲爱好者"
    }
    assert c.put("/iron/api/rank/nick", json={"nick": "a"}).status_code == 422
    assert c.put("/iron/api/rank/nick", json={"nick": "加微信看看"}).status_code == 422
    got = c.post(
        "/iron/api/rank/comments", json={"board": "gear", "key": "c:跳绳", "text": "好"}
    ).json()
    first = got["comments"][0]
    assert first["nick"] == "深蹲爱好者" and "42" not in {str(v) for v in first.values()}  # 不露账号
    assert not {"user", "user_id", "account"} & set(first)


def test_search_across_boards_and_hot_terms_without_accounts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    c, _, rank = client()
    with caplog.at_level(logging.INFO, logger="ironm_agent.rank"):
        got = c.get("/iron/api/rank/search", params={"q": "哑铃"}).json()["items"]
        c.post(
            "/iron/api/rank/comments",
            json={"board": "gear", "key": "c:跳绳", "text": "秘密评论内容"},
        )
    boards = {x["board"] for x in got}
    assert {"move", "gear"} <= boards and all(x["board_name"] for x in got)
    assert c.get("/iron/api/rank/search", params={"q": "没有这种东西"}).json()["items"] == []
    assert "哑铃" not in caplog.text and "秘密评论内容" not in caplog.text
    today = date.today()
    terms = [t for t, _, _ in asyncio.run(rank.searches(today - timedelta(days=7)))]
    assert terms == ["哑铃"]  # 搜不到的不记；只记词和天，没有账号
    assert asyncio.run(record_search(rank, "加微信", 3, today)) is False


def test_hot_takes_top_8_of_last_7_days_with_flags() -> None:
    rank, today = RankBook(), date(2026, 10, 29)

    async def fill() -> None:
        for i in range(10):
            for _ in range(20 - i):
                await rank.add_search(f"词{i}", today - timedelta(days=4))
        await rank.add_search("很早的", today - timedelta(days=8))
        for _ in range(5):
            await rank.add_search("刚出现", today)
        for _ in range(10):
            await rank.add_search("词9", today)

    asyncio.run(fill())
    got = asyncio.run(hot(rank, today))
    names = [x["term"] for x in got]
    assert len(got) == 8 and "很早的" not in names and names[:2] == ["词9", "词0"]
    assert got[0]["flag"] == got[1]["flag"] == "热"


def test_rank_change_against_the_week_start_and_none_in_the_first_week() -> None:
    tiers, rank = TierBook(), RankBook()

    def votes(key: str, tier: str, users: range) -> None:
        for i in users:
            asyncio.run(tiers.vote(f"u{i}", "gear", key, tier))

    def ranks(day: date) -> dict[str, dict[str, Any]]:
        return {
            r["name"]: r for r in asyncio.run(ranked(tiers, rank, "x", "gear", day)) if r["rank"]
        }

    week1 = date(2026, 10, 19)
    votes("c:跳绳", "hang", range(3))
    votes("c:壶铃", "top", range(3))
    first = ranks(week1)
    assert first["跳绳"]["rank"] == 1 and all(
        r["trend"] == "" for r in first.values()
    )  # 第一周不显示
    votes("c:泡沫轴", "npc", range(3))
    week2 = ranks(week1 + timedelta(days=7))  # 这周第一次看：记下名次，和自己比没有变化
    assert all(r["trend"] == "" for r in week2.values()) and week2["泡沫轴"]["rank"] == 3
    votes("c:泡沫轴", "hang", range(3, 20))
    later = ranks(week1 + timedelta(days=9))
    assert later["泡沫轴"]["trend"] == "↑2" and later["跳绳"]["trend"] == "↓1"
    assert later["壶铃"]["trend"] == "↓1"
    assert week_of(date(2026, 10, 29)) == date(2026, 10, 26)


def test_move_board_filters_by_part_with_part_ranks_and_no_trend() -> None:
    c, tiers, rank = client()
    squat = next(x for x in library().exercises if x.part == "腿臀")
    votes_for(tiers, rank, "move", squat.id, ["hang"] * 3)
    votes_for(tiers, rank, "move", BENCH.id, ["top"] * 3)
    whole = board(c, "move")
    assert row(whole, squat.name)["rank"] == 1 and row(whole, BENCH.name)["rank"] == 2
    assert "胸" in whole["parts"]
    chest = board(c, "move", part="胸")
    assert {x["part"] for x in chest["items"]} == {"胸"} and row(chest, BENCH.name)["rank"] == 1
    assert all(x["trend"] == "" for x in chest["items"])
    assert c.get("/iron/api/rank/board", params={"board": "gear", "part": "胸"}).status_code == 422
    library_report = c.post("/iron/api/rank/report", json={"board": "move", "key": BENCH.id})
    assert library_report.status_code == 422  # 动作库里的不能举报


def test_old_tier_votes_are_kept() -> None:
    """§66 的票照用：动作按部位的票并进动作榜，补剂和蛋白粉类就是补剂榜；食物类不显示也不删。"""
    tiers, rank = TierBook(), RankBook()
    now = asyncio.run(_now())

    async def old() -> None:
        for i in range(3):
            await tiers.vote(f"u{i}", "move:胸", BENCH.id, "hang")
        await tiers.add(Item("supplement", "c:一水肌酸", "一水肌酸", "u0", now))
        await tiers.add(Item("food", "c:鸡胸肉", "鸡胸肉", "u0", now))
        for i in range(3):
            await tiers.vote(f"u{i}", "supplement", "c:一水肌酸", "top")

    asyncio.run(old())
    c = as_user(tiers, rank, "u0")
    assert row(board(c, "move"), BENCH.name)["rank"] == 1
    assert row(board(c, "supplement"), "一水肌酸")["votes"] == 3
    assert all(x["name"] != "鸡胸肉" for b in BOARD_NAMES for x in board(c, b)["items"])
    assert asyncio.run(tiers.items("food"))  # 原来的条目还在
    vote(c, "move", BENCH.id, "")  # 新榜撤回：旧的那一票也清掉，不会又冒出来
    assert row(board(c, "move"), BENCH.name)["votes"] == 2


async def _now() -> Any:
    from datetime import datetime

    return datetime.now().astimezone()


def test_reported_entries_are_hidden_after_three_people() -> None:
    c, tiers, rank = client()
    c.post("/iron/api/rank/items", json={"board": "gear", "name": "乱写的东西", "force": True})
    for u in ("a", "b", "c"):
        assert (
            as_user(tiers, rank, u)
            .post("/iron/api/rank/report", json={"board": "gear", "key": "c:乱写的东西"})
            .status_code
            == 200
        )
    assert "乱写的东西" not in {x["name"] for x in board(c, "gear")["items"]}


def test_typing_does_not_feed_hot_terms() -> None:
    """边打字边搜（record=false）不进热搜，按回车、点热搜才记。"""
    c, _, rank = client()
    c.get("/iron/api/rank/search", params={"q": "哑", "record": "false"})
    c.get("/iron/api/rank/search", params={"q": "哑铃"})
    terms = [t for t, _, _ in asyncio.run(rank.searches(date.today() - timedelta(days=7)))]
    assert terms == ["哑铃"]


def test_home_card_fills_with_waiting_entries_when_few_are_ranked() -> None:
    """开榜时没票：卡片用待评的补满 5 个，上榜的排在前面（§80 由前 10 改成前 5）。"""
    c, tiers, rank = client()
    key = row(board(c, "gear"), "可调哑铃")["key"]
    votes_for(tiers, rank, "gear", key, ["hang", "hang", "top"])
    gear = next(b for b in c.get("/iron/api/rank").json()["boards"] if b["board"] == "gear")
    assert [x["name"] for x in gear["top"]] == ["可调哑铃"]
    assert len(gear["fill"]) == 4 and all(x["rank"] is None for x in gear["fill"])
