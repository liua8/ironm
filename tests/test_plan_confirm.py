"""排新计划前先确认五项、说清目标（spec [2026-10-23] §55），整轮走一遍。"""

import asyncio
from datetime import date
from typing import Any

from ironm_agent.actions import ASK_TERMS, NEW_PLAN
from ironm_agent.clarify import CONFIRM, CONFIRMED_NOTE, HEAD
from ironm_agent.goal import Goal, GoalBook
from ironm_agent.metrics import Profile
from tests.test_plan_ops import Editor, _seeded
from tests.test_plugin import agent, text_of
from tests.test_single_agent import NEW
from tests.test_turn_flow import Coach, book, run, snapshot_of


def _with_goal(a: Any) -> Any:
    goals = GoalBook()
    asyncio.run(goals.set("42", Goal(65.0, date(2027, 10, 26), date(2026, 10, 20), start=67.0)))
    a._goals = goals
    return a


def _card(blocks: list[dict[str, Any]]) -> bool:
    return any(str(b.get("id", "")).startswith("card-") for b in blocks)


# 标记要先确认条件、却没把五项列出来（§120：调用 ask_plan_terms，只说了一句）
ASK = {"answer": "好，先确认一下条件。", "act": (ASK_TERMS, {})}


def test_asking_for_a_plan_with_a_plan_confirms_first(monkeypatch: Any) -> None:
    """需求 1–3：已有计划、记忆里有时间和器械，说"给我一份计划"：先确认五项，不出预览；
    管家没把条件列好时退回系统列的五项（§86）。"""
    t = Coach(**ASK)
    a, _ = _seeded(t, monkeypatch)
    a._memory = book(("equipment", "家里一对可调哑铃"), ("schedule", "工作日晚上最多 45 分钟"))
    _with_goal(a)
    blocks, seen = run(a, "我想要更好的减重，给我一份计划吗")
    text = text_of(blocks)
    assert seen["path"] == "clarify" and seen["clarify_by"] == "fixed" and not _card(blocks)
    assert t.stages.count("expert") == 2  # 标记确认条件、作答；只问不排
    assert HEAD in text and CONFIRM in text
    for item in ("①目标", "②场景", "③器械", "④时间", "⑤伤病"):
        assert item in text
    assert "65 公斤" in text and "2027年10月26日" in text
    assert "可调哑铃（10月20日你说的）" in text and "45 分钟（10月20日你说的）" in text


def test_confirmed_conditions_build_a_new_plan_with_the_goal(monkeypatch: Any) -> None:
    """回"按这个排"：排新计划（不走改动套用），交给管家的要求里带上目标的数和日期。"""
    t = Coach(**ASK)
    a, _ = _seeded(t, monkeypatch)
    _with_goal(a)
    first, _ = run(a, "我要重新定计划")
    assert HEAD in text_of(first)

    async def asked(*_: str) -> list[str]:
        return ["用户：我要重新定计划", "教练（要点）：" + text_of(first)[:120]]

    a._history = asked
    t.act = (NEW_PLAN, {"plan": NEW, "changes": "新排", "kind": "new"})
    _, seen = run(a, "按这个排")
    assert seen["path"] == "answer" and seen["task"] == "plan" and "plan_ops" not in seen
    said = t.seen[-2]  # 这一轮交计划时收到的
    assert CONFIRMED_NOTE[:20] in said and "65 公斤" in said and "目标的数和日期照写" in said


def test_one_spot_edit_is_not_confirmed(monkeypatch: Any) -> None:
    """ "周三挪到周四"：不确认，照旧按改动套用。"""
    t = Editor([{"kind": "move", "day": 3, "to_day": 4, "why": "你要求的"}])
    a, _ = _seeded(t, monkeypatch)
    blocks, seen = run(a, "把周三挪到周四")
    assert seen["plan_ops"]["by"] == "model" and HEAD not in text_of(blocks) and _card(blocks)


def test_no_goal_table_falls_back_to_the_profile(monkeypatch: Any) -> None:
    """没有目标表：写档案里的目标类别。"""
    a = agent(Coach(**ASK), monkeypatch=monkeypatch,
              snapshot=snapshot_of(profile=Profile(goal="fat_loss")))  # fmt: skip
    blocks, _ = run(a, "给我一份训练计划")
    assert "档案里写的是" in text_of(blocks) and HEAD in text_of(blocks)


def test_edit_that_changes_nothing_asks_what_was_meant(monkeypatch: Any) -> None:
    """需求 4：改动一处都没套上：说明理解成了什么、为什么没改成，问改哪一处还是重排。"""
    t = Editor([{"kind": "edit", "day": 3, "exercise": "单臂哑铃划船", "sets": 5}])
    a, _ = _seeded(t, monkeypatch)
    blocks, _ = run(a, "周三的划船改成 5 组")
    text = text_of(blocks)
    assert "我理解成要" in text and "没改成" in text and "重新排一份" in text
    assert not _card(blocks) and not text.startswith("这次没改")
