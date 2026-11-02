"""排行榜改版（spec [2026-10-23] §80）：前 5、带图和说明、健身餐合并、训练计划榜、首页不再有全部榜单。"""

import asyncio
from pathlib import Path

import pytest
import yaml
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent import rank_images
from ironm_agent.exercises import library
from ironm_agent.protools.templates import templates
from ironm_agent.rank import _CLAIMS, BOARD_NAMES, CARD_TOP, _seeds, plan_cover
from ironm_agent.tier import custom_key
from tests.test_rank import as_user, board, client, row, vote


def test_home_shows_top_five_per_board() -> None:
    c, _, _ = client()
    got = c.get("/iron/api/rank").json()
    assert CARD_TOP == 5
    for b in got["boards"]:
        assert len(b["top"]) + len(b["fill"]) == 5, b["board"]


def test_every_row_has_a_description_and_no_claims_for_supplements() -> None:
    c, _, _ = client()
    for name in BOARD_NAMES:
        items = board(c, name)["items"]
        assert all(x["desc"] for x in items), name  # 起步条目、动作库、方案库都有说明
    for name in ("supplement", "protein"):
        for seed in _seeds()[name]:
            assert seed.desc and not _CLAIMS.search(seed.desc), seed.name
    added = c.post(
        "/iron/api/rank/items", json={"board": "gear", "name": "测试器材", "force": True}
    )
    assert (
        row(board(c, "gear"), "测试器材")["desc"] == "" and added.status_code == 200
    )  # 用户加的没有


def test_meal_board_merges_fat_and_gain() -> None:
    c, tiers, rank = client()
    assert "fat" not in BOARD_NAMES and "gain" not in BOARD_NAMES
    meal = board(c, "meal")
    names = {x["name"]: x["tag"] for x in meal["items"]}
    assert names["鸡胸肉藜麦沙拉"] == "减脂" and names["牛肉饭加蛋"] == "增肌"
    # 旧榜的票、用户加的条目、评论都并过来
    key = custom_key("番茄龙利鱼")
    for i in range(3):
        asyncio.run(tiers.vote(f"old{i}", "fat", key, "hang"))
    asyncio.run(tiers.vote("old0", "gain", custom_key("肉酱意面"), "top"))
    from datetime import datetime

    from ironm_agent.rank import Comment
    from ironm_agent.tier import Item

    now = datetime.now().astimezone()
    asyncio.run(tiers.add(Item("gain", custom_key("老榜加的饭"), "老榜加的饭", "old1", now)))
    asyncio.run(rank.add_comment(Comment("c1", "fat", key, "old2", "好吃不胖", now)))
    meal = board(c, "meal")
    fish = row(meal, "番茄龙利鱼")
    assert fish["votes"] == 3 and fish["rank"] == 1 and fish["comments"] == 1
    assert row(meal, "肉酱意面")["votes"] == 1 and row(meal, "老榜加的饭")["added"]
    # 在新榜改票：旧票清掉，只算一票
    vote(as_user(tiers, rank, "old0"), "meal", key, "top")
    assert row(board(c, "meal"), "番茄龙利鱼")["votes"] == 3
    assert not [v for v in asyncio.run(tiers.votes("fat")) if v.user_id == "old0" and v.tier]


def test_plan_board_lists_the_plan_library_and_cannot_take_additions() -> None:
    c, _, _ = client()
    plans = board(c, "plan")
    assert {x["key"] for x in plans["items"]} == {t.id for t in templates()}
    assert not plans["can_add"] and board(c, "gear")["can_add"]
    std = row(plans, "凯圣王×谭成义三分化")
    assert std["tag"] == "标准方案" and "每周 3或6 天" in std["desc"]
    r = c.post("/iron/api/rank/items", json={"board": "plan", "name": "我的计划", "force": True})
    assert r.status_code == 422
    rep = c.post("/iron/api/rank/report", json={"board": "plan", "key": "ppl-6"})
    assert rep.status_code == 422  # 方案库里的不能举报
    vote(c, "plan", "kai-tan-ppl", "top")
    item = c.get("/iron/api/rank/item", params={"board": "plan", "key": "kai-tan-ppl"}).json()
    p = item["plan"]
    assert p["days"] == [3, 6] and [s["name"] for s in p["sessions"]] == ["推", "拉", "腿"]
    assert p["why"] and p["progress"] and p["differs"] and "〔" not in p["why"]  # 不展示依据编号
    assert p["source"]["authors"] == ["凯圣王", "谭成义"] and p["source"]["secondhand"]
    assert "凯圣王×谭成义三分化" in p["ask"]
    gear = c.get("/iron/api/rank/item", params={"board": "gear", "key": custom_key("壶铃")}).json()
    assert gear["plan"] is None


def test_plan_cover_is_a_library_exercise() -> None:
    ids = {x.id for x in library().exercises}
    for t in templates():
        assert plan_cover(t.id) in ids, t.id


# ---- 配图 ----


def test_manifest_has_credit_and_only_reusable_licenses() -> None:
    got = rank_images.manifest()
    seeds = {
        custom_key(s.name) for b in ("meal", "supplement", "protein", "gear") for s in _seeds()[b]
    }
    assert got and set(got) <= seeds
    for key, im in got.items():
        assert im["author"] and im["page"].startswith("https://commons.wikimedia.org/"), key
        assert rank_images.LICENSES.match(im["license"]), (key, im["license"])
        assert rank_images.FILE_NAME.match(im["file"]), key


@pytest.fixture
def pics(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    key = custom_key("壶铃")
    manifest = {"images": {
        key: {"file": "gear-04.jpg", "license": "CC BY-SA 4.0", "author": "某人",
              "page": "https://commons.wikimedia.org/wiki/File:K.jpg"},
        custom_key("跳绳"): {"file": "gear-06.jpg", "license": "All rights reserved", "author": "x",
                           "page": "https://commons.wikimedia.org/wiki/File:J.jpg"},
    }}  # fmt: skip
    path = tmp_path / "rank_images.yaml"
    path.write_text(yaml.safe_dump(manifest, allow_unicode=True), encoding="utf-8")
    folder = tmp_path / "data" / "rank-images"
    folder.mkdir(parents=True)
    for name in ("gear-04.jpg", "gear-06.jpg"):
        (folder / name).write_bytes(b"\xff\xd8 fake jpeg")
    monkeypatch.setenv("IRONM_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(rank_images, "MANIFEST", path)
    return folder


def test_rows_get_downloaded_images_with_credit(pics: Path) -> None:
    c, _, _ = client()
    gear = board(c, "gear")
    bell = row(gear, "壶铃")
    assert (
        bell["image"] == "/iron/api/rank-images/gear-04.jpg" and bell["credit"]["author"] == "某人"
    )
    assert row(gear, "跳绳")["image"] is None  # 许可不合格：不给
    assert row(gear, "可调哑铃")["image"] is None  # 清单里没有


def test_image_endpoint_serves_only_files_in_the_folder(pics: Path) -> None:
    from ironm_agent import web

    app = FastAPI()
    app.include_router(web.router)
    c = TestClient(app)
    assert c.get("/iron/api/rank-images/gear-04.jpg").status_code == 200
    assert c.get("/iron/api/rank-images/gear-09.jpg").status_code == 404
    assert c.get("/iron/api/rank-images/..%2F..%2Fsecret.jpg").status_code == 404
    assert c.get("/iron/api/rank-images/notes.txt").status_code == 404


def test_home_page_has_no_all_boards_grid() -> None:
    js = (Path(__file__).parents[1] / "ironm_agent" / "web" / "app.js").read_text(encoding="utf-8")
    assert 'section("全部榜单"' not in js and "rk-tile" not in js
    assert "按我的情况用这个计划" in js and "askCoach(p.ask)" in js
