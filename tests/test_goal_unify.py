"""记忆结构第 3 步：目标三处合一（spec [2026-10-23] §151）。不连数据库、不调用真实模型。"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from typing import Any

import pytest

from ironm_agent.actions import ALWAYS, SET_GOAL, Desk, Outcome
from ironm_agent.goal import Goal, GoalBook
from ironm_agent.llm import Reply
from ironm_agent.metrics import Profile, Readings
from tests.fakes import call, jsonr
from tests.test_single_agent import single
from tests.test_turn_flow import TODAY, snapshot_of
from tests.test_turn_flow import run as run_turn

ME = Profile(
    height_cm=175, birth=date(1995, 6, 1), sex="male", goal="fat_loss", activity="moderate"
)
WEIGHTS = Readings(
    weight=tuple((TODAY - timedelta(days=i), round(72.0 - 0.02 * i, 2)) for i in range(28))
)
BY = (TODAY + timedelta(days=90)).isoformat()


def tool_then(args: dict[str, Any], answer: str = "好，下面是改目标的预览〔经验〕。") -> Any:
    def reply(system: str, user: str, results: list[str]) -> Reply:
        return call(SET_GOAL, **args) if not results else jsonr({"answer": answer})

    return reply


def turn(
    monkeypatch: Any, text: str, args: dict[str, Any], goals: GoalBook | None = None
) -> tuple[Any, Any]:
    a, s = single(tool_then(args), monkeypatch, snapshot=snapshot_of(WEIGHTS, ME))
    a._goals = goals or GoalBook()
    run_turn(a, text)
    return a, s


def drafts(a: Any) -> list[Any]:
    return [d for d in a._training._drafts.get("42", {}).values() if d.kind == "goal"]


def test_a_new_goal_becomes_a_card_with_calories_and_target(monkeypatch: Any) -> None:
    a, s = turn(monkeypatch, "我现在想增肌了，三个月增到 75 公斤", {"type": "muscle", "value": 75, "by": BY,
                                                                "why": "想增肌"})  # fmt: skip
    [d] = drafts(a)
    assert d.state == "pending" and "已出改目标预览" in s.last
    items = d.content["items"]
    assert items[0] == "目标：减脂 → 增肌" and items[1].startswith("每日热量：约 ")
    assert "目标体重：75 公斤" in items[2]
    assert d.content["goal"] == {"type": "muscle", "value": 75.0, "by": BY}
    assert d.content["before"] == {"type": "fat_loss", "goal": None}


@pytest.mark.parametrize(
    ("text", "args", "why"),
    [
        ("我想减脂", {"type": "muscle"}, "目标方向和他这句话"),
        ("我想增肌", {"type": "muscle", "value": 80, "by": BY}, "不在他这句话里"),
        (
            "我想三个月增到 75 公斤",
            {"value": 75, "by": (TODAY + timedelta(days=900)).isoformat()},
            "两年以内",
        ),
        ("我想增到 75 公斤", {"value": 75}, "配一个日期"),
        ("我还是想减脂", {"type": "fat_loss"}, "不用改"),
        ("随便", {}, "要交目标方向"),
    ],
)
def test_bad_goals_are_sent_back(
    monkeypatch: Any, text: str, args: dict[str, Any], why: str
) -> None:
    a, s = turn(monkeypatch, text, args)
    assert drafts(a) == [] and why in s.last


def test_jin_is_converted_and_a_fast_pace_is_flagged(monkeypatch: Any) -> None:
    soon = (TODAY + timedelta(days=21)).isoformat()
    a, _ = turn(monkeypatch, "三周减到 130 斤", {"value": 130, "unit": "斤", "by": soon})
    [d] = drafts(a)
    assert d.content["goal"]["value"] == 65.0 and any(
        "超过体重的 1%" in x for x in d.content["items"]
    )


def test_desk_treats_the_goal_card_like_a_preview() -> None:
    async def ok(desk: Desk, args: Any) -> Outcome:
        return Outcome(
            True, "已出", kind="goal", cards=({"id": "card-g"},), draft="g1", what="goal"
        )

    desk = Desk({SET_GOAL: ok})
    desk.unlock(ALWAYS)
    assert SET_GOAL in desk.unlocked
    asyncio.run(desk.run(SET_GOAL, {}))
    asyncio.run(desk.run(SET_GOAL, {}))
    assert desk.kinds == ["goal"] and "goal" in desk.done_kinds and desk.drafts == ["g1"]
    assert desk.cards == [{"id": "card-g"}]
    assert desk.unmet("目标已经改好了")  # 只出了卡片、还没确认：不算改好了（复核 11-03）


class Profiles:
    def __init__(self, goal: str | None) -> None:
        self.goal = goal

    async def set_goal(self, _: str, goal: str | None) -> None:
        self.goal = goal

    async def load(self, _: str) -> tuple[Profile, dict[str, str]]:
        return Profile(goal=self.goal), {}  # type: ignore[arg-type]


def web(
    monkeypatch: pytest.MonkeyPatch, goal: str | None = "fat_loss", old: Goal | None = None
) -> Any:
    from ironm_agent import profile, web_more
    from ironm_agent.casefile import Snapshot
    from tests.test_live import client as live_client

    c, book, _ = live_client(monkeypatch)
    goals = GoalBook()
    if old is not None:
        asyncio.run(goals.set("42", old))
    c.app.dependency_overrides[web_more.goal_store] = lambda: goals  # type: ignore[attr-defined]
    prof = Profiles(goal)
    monkeypatch.setattr(profile, "set_goal", prof.set_goal)
    monkeypatch.setattr(profile, "load", prof.load)

    async def snap(_: str) -> Snapshot:
        return Snapshot(ME, WEIGHTS, (), TODAY)

    monkeypatch.setattr(web_more._web(), "snapshot_for", snap)
    return c, book, goals, prof


def goal_draft(book: Any, before: dict[str, Any]) -> Any:
    content = {"title": "改目标", "headline": "想增肌", "items": ["目标：减脂 → 增肌"],
               "goal": {"type": "muscle", "value": 75.0, "by": BY}, "before": before}  # fmt: skip
    return asyncio.run(book.add_draft("42", "goal", content))


def test_confirm_writes_both_places_and_undo_restores(
    monkeypatch: pytest.MonkeyPatch, coach_in_memory: Any
) -> None:
    old = Goal(68.0, TODAY + timedelta(days=60), TODAY - timedelta(days=10), 72.0)
    c, book, goals, prof = web(monkeypatch, old=old)
    d = goal_draft(book, {"type": "fat_loss", "goal": old.json()})
    r = c.post(f"/iron/api/drafts/{d.id}/confirm")
    assert r.status_code == 200 and r.json()["draft"]["state"] == "confirmed"
    g = asyncio.run(goals.get("42"))
    assert prof.goal == "muscle" and g is not None and g.value == 75.0 and g.by.isoformat() == BY
    assert ("42", "改目标") in coach_in_memory
    u = c.post(f"/iron/api/drafts/{d.id}/undo")
    assert u.status_code == 200 and u.json()["draft"]["state"] == "undone"
    back = asyncio.run(goals.get("42"))
    assert prof.goal == "fat_loss" and back is not None and back.value == 68.0
    assert ("42", "撤销改目标") in coach_in_memory


def test_undo_is_refused_after_another_change(monkeypatch: pytest.MonkeyPatch) -> None:
    c, book, goals, prof = web(monkeypatch, goal=None)
    d = goal_draft(book, {"type": None, "goal": None})
    assert c.post(f"/iron/api/drafts/{d.id}/confirm").status_code == 200
    prof.goal = "strength"  # 之后在个人中心又改了
    r = c.post(f"/iron/api/drafts/{d.id}/undo")
    assert r.status_code == 409 and "之后又改过目标" in r.json()["detail"]
    prof.goal = "muscle"
    assert c.post(f"/iron/api/drafts/{d.id}/undo").status_code == 200
    assert prof.goal is None and asyncio.run(goals.get("42")) is None  # 原来没有：恢复成没有


def test_profile_goal_change_makes_the_coach_look_again(
    monkeypatch: pytest.MonkeyPatch, coach_in_memory: Any
) -> None:
    from ironm_agent import profile, web
    from tests.test_live import client as live_client

    c, _, _ = live_client(monkeypatch)

    async def save(*_: Any) -> None:
        return None

    async def get(user_id: str) -> dict[str, Any]:
        return {}

    prof = Profiles("fat_loss")
    monkeypatch.setattr(profile, "save", save)
    monkeypatch.setattr(profile, "load", prof.load)
    monkeypatch.setattr(web, "get_profile", get)
    assert c.put("/iron/api/profile", json={"height_cm": 175}).status_code == 200
    assert ("42", "改档案目标") not in coach_in_memory
    assert (
        c.put("/iron/api/profile", json={"height_cm": 176, "goal": "fat_loss"}).status_code == 200
    )
    assert (
        "42",
        "改档案目标",
    ) not in coach_in_memory  # 表单照旧带着目标、没改：不叫醒（复核 11-03）
    assert c.put("/iron/api/profile", json={"goal": "muscle"}).status_code == 200
    assert ("42", "改档案目标") in coach_in_memory


def test_case_file_goal_line_has_both_places() -> None:
    from ironm_agent.casefile import Snapshot, build
    from ironm_agent.memory_view import Recall

    case = build(
        Snapshot(ME, WEIGHTS, (), TODAY), Recall(), "你好", target="2027年2月1日前体重到 75 公斤"
    )
    assert "目标减脂；目标体重：2027年2月1日前体重到 75 公斤" in case.text()


def test_goal_card_survives_when_the_turn_also_asks_plan_terms(monkeypatch: Any) -> None:
    """同一轮既交了改目标、又要先确认排新计划的条件：改目标的卡片照出，计划不出（真实模型回放 11-03）。"""
    from ironm_agent.actions import ASK_TERMS
    from ironm_agent.clarify import HEAD

    steps = [call(SET_GOAL, type="muscle", value=73, by=BY), call(ASK_TERMS)]

    def reply(system: str, user: str, results: list[str]) -> Reply:
        if len(results) < len(steps):
            return steps[len(results)]
        return jsonr({"answer": f"{HEAD}：目标、场景、器械、时间、伤病，哪几项变了？"})

    a, _ = single(reply, monkeypatch, snapshot=snapshot_of(WEIGHTS, ME))
    a._goals = GoalBook()
    blocks, seen = run_turn(a, "我不减脂了，现在想增肌，半年增到 73 公斤")
    assert seen.get("path") == "clarify"
    assert any(str(b.get("id", "")).startswith("card-") for b in blocks)
    [d] = drafts(a)
    assert d.state == "pending"


def test_a_goal_said_over_several_turns(monkeypatch: Any) -> None:
    """ "想减到 65 公斤"→管家问哪天→"半年吧"：前一句里的数也算他说的（复核 11-03）。"""

    def reply(system: str, user: str, results: list[str]) -> Reply:
        if "半年吧" in user and not results:
            return call(SET_GOAL, type="fat_loss", value=65, by=BY)
        return jsonr(
            {"answer": "哪天前减到？" if not results else "好，下面是改目标的预览〔经验〕。"}
        )

    a, s = single(reply, monkeypatch, snapshot=snapshot_of(WEIGHTS, Profile(
        height_cm=175, birth=date(1995, 6, 1), sex="male", goal="muscle", activity="moderate")))  # fmt: skip
    a._goals = GoalBook()
    run_turn(a, "我想减脂，减到 65 公斤")
    assert drafts(a) == []

    async def asked(*_: str) -> list[str]:
        return ["用户：我想减脂，减到 65 公斤", "教练（要点）：哪天前减到？"]

    a._history = asked
    run_turn(a, "半年吧")
    [d] = drafts(a)
    assert d.content["goal"]["value"] == 65.0 and "已出改目标预览" in s.last


def test_no_card_when_the_profile_cannot_be_read(monkeypatch: Any) -> None:
    from ironm_agent.casefile import Snapshot

    async def broken(_: str) -> Snapshot:
        return Snapshot(Profile(), Readings(), (), TODAY, failed=True)

    a, s = single(tool_then({"type": "muscle"}), monkeypatch, snapshot=broken)
    a._goals = GoalBook()
    run_turn(a, "我想增肌")
    assert drafts(a) == [] and "读不到他的档案" in s.last


@pytest.mark.parametrize(
    "text",
    [
        "我不想减脂了",
        "我不减脂了",
        "不想再继续减脂",
        "我不是想减脂",
        "别再让我减肥了",
        "减脂我不想了",
    ],
)
def test_not_wanting_a_goal_is_not_that_goal(monkeypatch: Any, text: str) -> None:
    a, s = turn(monkeypatch, text, {"type": "fat_loss"})
    assert drafts(a) == [] and "对不上" in s.last


def test_undo_restores_what_it_was_at_confirm_and_double_confirm_writes_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    c, book, goals, prof = web(monkeypatch, goal="fat_loss")
    d = goal_draft(book, {"type": "fat_loss", "goal": None})
    prof.goal = "strength"  # 出卡片之后、确认之前，他在个人中心改成了增力
    assert c.post(f"/iron/api/drafts/{d.id}/confirm").status_code == 200
    assert prof.goal == "muscle"
    prof.goal = "muscle"
    asyncio.run(
        goals.set("42", Goal(80.0, TODAY + timedelta(days=30), TODAY))
    )  # 之后又在目标页改了
    assert c.post(f"/iron/api/drafts/{d.id}/confirm").status_code == 200  # 再点一次：不再写
    assert asyncio.run(goals.get("42")).value == 80.0  # type: ignore[union-attr]
    asyncio.run(goals.set("42", Goal(75.0, date.fromisoformat(BY), TODAY)))
    assert c.post(f"/iron/api/drafts/{d.id}/undo").status_code == 200
    assert prof.goal == "strength"  # 恢复到确认那一刻的，不是出卡片时的减脂


def test_calories_start_from_what_the_home_page_shows(monkeypatch: Any) -> None:
    """两周复盘调过热量：卡片从首页现在的数起算，只加目标类型带来的变化（复核 11-03）。"""
    from dataclasses import replace

    from ironm_agent.casefile import Snapshot
    from ironm_agent.metrics import compute_all

    shown = tuple(replace(m, value=1800) if m.key == "kcal_target" else m
                  for m in compute_all(WEIGHTS, ME, TODAY))  # fmt: skip

    async def read(_: str) -> Snapshot:
        return Snapshot(ME, WEIGHTS, shown, TODAY)

    a, _ = single(tool_then({"type": "muscle"}), monkeypatch, snapshot=read)
    a._goals = GoalBook()
    run_turn(a, "我现在想增肌了")
    [d] = drafts(a)
    assert d.content["items"][1].startswith("每日热量：约 1800 → ")


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("想半年减到 65 公斤", "fat_loss"),
        ("先保持现在这样", "health"),
        ("我不减脂了，想增肌", "muscle"),
    ],
)
def test_ways_of_saying_a_direction(monkeypatch: Any, text: str, kind: str) -> None:
    args: dict[str, Any] = {"type": kind}
    if "65" in text:
        args |= {"value": 65, "by": BY}
    a, _ = turn(monkeypatch, text, args)
    assert len(drafts(a)) == 1


def test_a_number_inside_another_number_is_not_jin(monkeypatch: Any) -> None:
    """ "170 斤"里的"70"不是他说的 70 斤（复核 11-03：卡片曾写成 35 公斤）。"""
    args = {"type": "fat_loss", "value": 70, "unit": "公斤", "by": BY}
    a, _ = turn(monkeypatch, "我现在 170 斤，想半年减到 70 公斤", args)
    [d] = drafts(a)
    assert d.content["goal"]["value"] == 70.0


def test_a_date_without_a_weight_is_sent_back(monkeypatch: Any) -> None:
    a, s = turn(monkeypatch, "我想增肌，半年内", {"type": "muscle", "by": BY})
    assert drafts(a) == [] and "一起交" in s.last


def test_a_new_card_retires_the_last_one(monkeypatch: Any) -> None:
    """上一轮的改目标卡片还没点，这一轮又出了一张：旧的作废，点不了（复核 11-03）。"""

    def reply(system: str, user: str, results: list[str]) -> Reply:
        if results:
            return jsonr({"answer": "好，下面是改目标的预览〔经验〕。"})
        return call(SET_GOAL, type="strength" if "还是想练力量" in user else "muscle")

    a, _ = single(reply, monkeypatch, snapshot=snapshot_of(WEIGHTS, ME))
    a._goals = GoalBook()
    run_turn(a, "我想增肌")
    run_turn(a, "算了，我还是想练力量")
    states = {d.content["goal"]["type"]: d.state for d in drafts(a)}
    assert states == {"muscle": "cancelled", "strength": "pending"}


def test_a_failed_write_leaves_nothing_half_done(monkeypatch: pytest.MonkeyPatch) -> None:
    """确认时目标表写不进去：档案改回原来的、卡片作废、如实说没改成（复核 11-03）。"""
    c, book, goals, prof = web(monkeypatch, goal="fat_loss")
    d = goal_draft(book, {"type": "fat_loss", "goal": None})

    async def broken(*_: Any) -> None:
        raise RuntimeError("db down")

    monkeypatch.setattr(goals, "set", broken)
    r = c.post(f"/iron/api/drafts/{d.id}/confirm")
    assert r.status_code == 503 and "没改成" in r.json()["detail"]
    assert prof.goal == "fat_loss" and asyncio.run(goals.get("42")) is None
    assert asyncio.run(book.draft("42", d.id)).state == "undone"  # type: ignore[union-attr]
    assert c.post(f"/iron/api/drafts/{d.id}/confirm").status_code == 409


def test_confirm_retires_old_direction_memories_and_undo_brings_them_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """记忆里"减到 65 公斤"和确认后的增肌冲突：确认时作废，撤销时恢复；别的目标（跑半马）不动。"""
    from ironm_agent import web as web_api
    from ironm_agent.memory_store import Change, Item, MemoryBook
    from tests.test_facts_gear import T0

    c, book, _, prof = web(monkeypatch, goal="fat_loss")
    memory = MemoryBook()
    old = Item("m1", "goal", "目标：减脂，减到 65 公斤", "减到 65 公斤", "said", "pending", T0, T0)
    race = Item("m2", "goal", "明年 4 月跑半马", "跑半马", "said", "active", T0, T0)
    asyncio.run(memory.apply("42", [Change("insert", item=old), Change("insert", item=race)]))
    c.app.dependency_overrides[web_api.memory_store] = lambda: memory  # type: ignore[attr-defined]
    d = goal_draft(book, {"type": "fat_loss", "goal": None})
    assert c.post(f"/iron/api/drafts/{d.id}/confirm").status_code == 200
    assert [x.id for x in asyncio.run(memory.items("42"))] == ["m2"] and prof.goal == "muscle"
    assert c.post(f"/iron/api/drafts/{d.id}/undo").status_code == 200
    back = {x.id: x.status for x in asyncio.run(memory.items("42"))}
    assert back == {"m1": "pending", "m2": "active"}  # 恢复成原来的状态
