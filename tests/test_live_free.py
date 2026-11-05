"""训练里去掉加动作和问 IronM，去掉悬浮按钮（spec [2026-10-23] §133）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.test_live import PLAN, client

WEB = Path(__file__).resolve().parents[1] / "ironm_agent" / "web"
JS = (WEB / "app.js").read_text()


def test_free_training_starts_empty_without_the_plan(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch, plan=PLAN)
    got = c.post("/iron/api/live/start", json={"free": True}).json()["live"]
    assert got["items"] == [] and got["session"] == ""
    again = c.post("/iron/api/live/start", json={"free": True}).json()["live"]
    assert again["id"] == got["id"] and again["items"] == []  # 进行中的自由训练接着练，不补计划


def test_plan_training_has_no_add_button_and_nobody_to_ask() -> None:
    live = JS[JS.index("async function livePage(view)") : JS.index("// ---- 路由")]
    assert (
        '!L.session ? h("button", { class: "btn ghost", type: "button", onclick: addMove }' in live
    )  # 只有自由训练能加动作
    assert (
        "跟 IronM 说" not in live and "问问教练" not in live and "/iron/api/live/adjust" not in live
    )
    assert 'liveEntry({ free: true }, "自由训练")' in JS
    assert "askfab" not in JS and 'id="askfab"' not in (WEB / "index.html").read_text()
    assert ".ask-fab" not in (WEB / "style.css").read_text()


def test_page_header_scrolls_away() -> None:
    """§134：页头不粘在顶上，跟着内容一起滚走。"""
    css = (WEB / "style.css").read_text()
    assert css.rindex(".bar { position: static; }") > css.rindex(
        "position: sticky; top: 0; z-index: 5"
    )  # 最后生效的是 static


def test_atlas_is_three_sections_without_a_separate_tier() -> None:
    """§136 起图鉴是 动作 / 饮食 / 方案；§161 起只放资料，榜单都在排行榜（首页"今日热搜"进去）。"""
    assert 'const ATLAS_SEGS = [["moves", "动作"], ["food", "饮食"], ["plans", "方案"]];' in JS
    chips = JS[JS.index("const ATLAS_CHIPS") : JS.index("function pageSeg(")]
    for name in ("动作库", "器械", "食材", "食谱"):
        assert f'"{name}"' in chips, name
    for gone in ("大家推荐", "器材", "健身餐", "补剂", "蛋白粉"):
        assert f'"{gone}"' not in chips, gone
    atlas = JS[JS.index("async function atlas(") : JS.index("async function record(")]
    assert (
        "rankBoard(" not in atlas[: atlas.index("async function plansAtlas(")]
        and "plansAtlas(view)" in atlas
    )
    moved = JS[JS.index("function moved(") : JS.index("let renderSeq")]
    assert 'sub === "recipes") return "#atlas/food/recipes"' in moved and "#rank/gear" in moved
    moves = JS[JS.index("async function moves(") : JS.index("function moveCard(")]
    assert (
        "tier-link" not in moves and "不知道练哪个" not in moves
    )  # §161：部位旁的链接和问 IronM 卡片去掉


def test_record_is_one_page_without_repeats() -> None:
    """§137：战绩一页到底；这周练了几次只说一次；没有小柱、圆环、单列的照片格。"""
    page = JS[JS.index("async function recordPage(view)") : JS.index("// ---- 身体")]
    for part in ('"这周"', "calendarCard(cal)", 'section("成就"', '"训练时间线"'):
        assert part in page, part
    assert "ws-bars" not in page and "ring(" not in page and "ws-photos" not in page
    assert "reportCard" not in JS and "trainLog" not in JS
    moved = JS[JS.index("function moved(") : JS.index("let renderSeq")]
    assert 'name === "record" && sub === "log") return "#record/timeline"' in moved


def test_timeline_is_its_own_page_with_a_picture_per_workout() -> None:
    """§139：战绩页上只留入口；时间线页每次训练配图（打卡照片，没有就用部位训练照片）。"""
    page = JS[
        JS.index("async function recordPage(view)") : JS.index("async function timelinePage(view)")
    ]
    assert 'href: "#record/timeline"' in page and "log-list" not in page
    tl = JS[JS.index("async function timelinePage(view)") : JS.index("function calendarCard(")]
    assert (
        "/iron/api/workouts/${x.id}/photo" in tl
        and "/iron/api/train-images" in tl
        and "imgs[mainPart(x)]" in tl
    )
    assert 'href: "#record"' in tl and "tl-item rest" in tl
    assert 'sub === "timeline" ? timelinePage(view)' in JS


def test_me_page_is_a_character_sheet_without_memory_notes() -> None:
    """§140、§141：我 = 角色卡、我的目标、设置一列；记忆不上页面，设置里一行能看能删。"""
    me = JS[JS.index("async function me(view)") : JS.index("// 头部：头像、账号")]
    assert "meHead(mine), goalBlock()," in me and "memoryBoard" not in JS
    for name in (
        "身体数据",
        "IronM 记得的事",
        "器材和场所",
        "导入健康数据和化验单",
        "我的文件",
        "城市和天气",
        "说明",
    ):
        assert f'row("{name}"' in me, name
    assert 'row("IronM 记得的事", "记错了可以删", memorySheet)' in me
    assert (
        'openSheet("器材和场所", gearSection())' in me
        and 'openSheet("城市和天气", citySection())' in me
    )


def test_rank_moves_to_its_own_page_with_a_home_entry() -> None:
    """§161：首页最上面"今日热搜"一条是排行榜唯一入口；排行榜页有返回首页；没人评时不写空话。"""
    assert 'rank: { title: "排行榜", tab: "home", render: rankPage' in JS
    home = JS[JS.index("async function homePage(") : JS.index("async function home(")]
    assert "await hotStrip()" in home
    strip = JS[JS.index("async function hotStrip(") : JS.index("async function hotStrip(") + 1600]
    assert 'href: "#rank"' in strip and "排行榜刚开，去评第一个" in strip
    assert 'rankBar("#home", "首页", null)' in JS
    board = JS[JS.index("async function rankBoard(") : JS.index("function rankLine(")]
    assert ': "没人评"' not in board and "还没人评过，点进去打第一个分。" in board
    assert (
        JS.count("tier-link") == 0
        or "tier-link" not in JS[JS.index("async function moves(") : JS.index("function moveCard(")]
    )


def test_plan_library_endpoint_hides_reference_codes() -> None:
    import asyncio

    from ironm_agent.web_atlas import plan_library

    plans = asyncio.run(plan_library("42"))["plans"]
    assert len(plans) >= 10 and all(p["sessions"] and p["blurb"] for p in plans)
    text = str(plans)
    assert "〔" not in text  # 出处编号不给用户看
