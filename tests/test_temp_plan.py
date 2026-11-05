"""计划分三层：临时调整要确认、到期回到原计划（spec [2026-10-23] §163 需求 2）。不连数据库、不调用真实模型。"""

from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest

from ironm_agent.actions import TEMP_CHANGE
from ironm_agent.plan_layers import Temp, active, load, plan_on
from ironm_agent.training import TrainingBook
from tests.test_actions_more import TODAY, go, harness
from tests.test_plan_ops import plan as seeded_plan

MON = TODAY + timedelta(days=3)  # 下周一（TODAY 是周五）
DROP = {"kind": "remove", "day": 1, "exercise": "提踵", "why": "酒店没器械"}


def temp(start: date, end: date, *ops: dict[str, Any]) -> Temp:
    return Temp("t1", start, end, "出差", tuple(ops))


def test_a_temp_change_applies_only_inside_its_dates() -> None:
    base = seeded_plan()
    t = temp(MON, MON + timedelta(days=2), DROP)
    names = lambda p, d: [x.exercise for x in p.session_on(d).items]  # noqa: E731
    assert "提踵" not in names(plan_on(base, [t], MON), MON)
    assert "提踵" in names(
        plan_on(base, [t], MON + timedelta(days=7)), MON + timedelta(days=7)
    )  # 过了：回到原计划
    assert active([t], MON - timedelta(days=1)) == []
    clash = temp(MON, MON, {"kind": "remove", "day": 1, "exercise": "不存在的动作"})
    assert plan_on(base, [clash], MON) == base  # 套不上的那条不算


def test_unconfirmed_temp_expires_after_its_start_and_undo_ends_it() -> None:
    book = TrainingBook()
    start = date.today() + timedelta(days=3)  # 确认按真实的今天看
    content = {
        "temp": {
            "start": start.isoformat(),
            "end": (start + timedelta(days=2)).isoformat(),
            "ops": [DROP],
        }
    }
    d = asyncio.run(book.add_draft("42", "temp", content))
    late = datetime.combine(start + timedelta(days=1), datetime.min.time()).astimezone(
        UTC
    ) + timedelta(hours=12)
    assert not d.expired() and d.expired(late)  # 过了开始日期还没确认：作废
    assert asyncio.run(book.confirm("42", d.id)) is not None
    [t] = asyncio.run(load(book, "42"))
    assert t.start == start and t.ops == (DROP,)
    asyncio.run(book.undo("42", d.id))
    assert asyncio.run(load(book, "42")) == []


def test_the_coach_proposes_a_temp_change_and_nothing_changes_until_confirmed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    a, desk, run, _ = harness(monkeypatch, "下周一到周三出差，酒店没器械", current=seeded_plan())
    said = go(a, desk, TEMP_CHANGE, start=MON.isoformat(), end=(MON + timedelta(days=2)).isoformat(),
              ops=[DROP], why="出差三天")  # fmt: skip
    assert said.startswith("已出临时调整的预览卡片") and desk.temps and run["preview"] == "temp"
    assert any((c.get("args") or {}).get("kind") == "temp" for c in desk.cards)
    d = asyncio.run(a._training.draft("42", desk.temps[0].draft))
    assert d is not None and d.state == "pending" and d.content["temp"]["start"] == MON.isoformat()
    assert asyncio.run(load(a._training, "42")) == []  # 没确认：不算数


@pytest.mark.parametrize(
    ("start", "end", "ops", "why"),
    [(TODAY - timedelta(days=1), TODAY, [DROP], "开始日期在过去"),
     (MON, MON + timedelta(days=28), [DROP], "超过 28 天"),
     (MON + timedelta(days=2), MON, [DROP], "结束早于开始"),
     (MON, MON, "删提踵", "改法不是列表"),
     (MON, MON, [{"kind": "remove", "day": 1, "exercise": "不存在的动作"}], "一条都没改成")],
)  # fmt: skip
def test_bad_temp_changes_are_sent_back(
    monkeypatch: pytest.MonkeyPatch, start: date, end: date, ops: Any, why: str
) -> None:
    a, desk, _, _ = harness(monkeypatch, "出差", current=seeded_plan())
    go(a, desk, TEMP_CHANGE, start=start.isoformat(), end=end.isoformat(), ops=ops, why="x")
    assert not desk.temps and asyncio.run(a._training.temps("42")) == [], why


def test_today_uses_the_confirmed_temp_change() -> None:
    from ironm_agent.coach_state import Inputs, Review, today_version
    from tests.test_coach import snap

    t = temp(MON, MON, DROP)
    v = today_version(
        Inputs(snapshot=snap(), plan=seeded_plan(), review=Review(day=MON), temps=[t]), MON
    )
    assert "提踵" not in [x["exercise"] for x in v.original["items"]]
    rest = temp(MON, MON, {"kind": "remove", "day": 1, "why": "出差那天不练"})
    v = today_version(
        Inputs(snapshot=snap(), plan=seeded_plan(), review=Review(day=MON), temps=[rest]), MON
    )
    assert v.status == "rest" and "临时调整" in v.why
