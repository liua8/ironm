"""计划页直接改（spec [2026-10-23] §106）：换动作、调组次、去掉、排顺序；只改今天 / 以后都改。

不连数据库、不调用真实模型。
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from ironm_agent.coach_state import Inputs, today_version
from ironm_agent.day_state import DayBook, DayState, lines
from ironm_agent.plan_edit import alternatives, edit, today_session
from ironm_agent.training import (
    LogItem,
    Plan,
    PlanEdit,
    PlanItem,
    Session,
    SetDone,
    TrainingBook,
    WorkoutLog,
)
from tests.test_live import client as live_client
from tests.test_turn_flow import snapshot_of

TODAY = date.today()
WD = TODAY.isoweekday()
OTHER = WD % 7 + 1  # 明天那天
JS = (Path(__file__).resolve().parents[1] / "ironm_agent" / "web" / "app.js").read_text()


def plan(reps: str = "8") -> Plan:
    return Plan(title="测试计划", days_per_week=2, sessions=[
        Session(day=WD, name="下肢", items=[PlanItem(exercise="杠铃深蹲", sets=3, reps=reps),
                                           PlanItem(exercise="罗马尼亚硬拉", sets=3, reps="10")]),
        Session(day=OTHER, name="上肢", items=[PlanItem(exercise="杠铃卧推", sets=3, reps="8"),
                                              PlanItem(exercise="哑铃划船", sets=3, reps="10")]),
    ])  # fmt: skip


def client(
    monkeypatch: pytest.MonkeyPatch,
    p: Plan | None = None,
    *,
    equipment: frozenset[Any] | None = None,
    injured: tuple[str, ...] = (),
    special: frozenset[str] = frozenset(),
    logs: tuple[WorkoutLog, ...] = (),
) -> tuple[TestClient, TrainingBook, DayBook]:
    from ironm_agent import web_more, web_plan

    c, book, _ = live_client(monkeypatch, plan=p or plan(), logs=logs)
    days = DayBook()
    c.app.dependency_overrides[web_more.day_store] = lambda: days  # type: ignore[attr-defined]

    async def limits(*_: Any) -> tuple[Any, tuple[str, ...], frozenset[str]]:
        return equipment, injured, special

    monkeypatch.setattr(web_plan, "_limits", limits)
    monkeypatch.setattr(web_more, "coach_later", lambda *a: None)
    monkeypatch.setattr(web_plan, "coach_later", lambda *a: None)
    monkeypatch.setattr(web_plan, "plan_change_later", lambda *a, **k: None)
    return c, book, days


def items(book: TrainingBook, day: int) -> list[tuple[str, int, str]]:
    stored = asyncio.run(book.plan("42"))
    assert stored is not None
    s = next(x for x in stored.plan.sessions if x.day == day)
    return [(x.exercise, x.sets, x.reps) for x in s.items]


def post(c: TestClient, day: int, scope: str, **e: Any) -> Any:
    return c.post("/iron/api/plan/edit", json={"day": day, "scope": scope, "edit": e})


# ---- 套用 -----------------------------------------------------------------------------------


def test_edits_apply_in_order() -> None:
    got = edit(plan(), WD, [PlanEdit(kind="edit", exercise="杠铃深蹲", sets=4),
                            PlanEdit(kind="swap", exercise="杠铃深蹲", to="高脚杯深蹲")])  # fmt: skip
    assert (got.plan.sessions[0].items[0].exercise, got.plan.sessions[0].items[0].sets) == (
        "高脚杯深蹲",
        4,
    )
    got = edit(plan(), WD, [PlanEdit(kind="swap", exercise="杠铃深蹲", to="高脚杯深蹲"),
                            PlanEdit(kind="edit", exercise="高脚杯深蹲", reps="12")])  # fmt: skip
    assert (got.plan.sessions[0].items[0].exercise, got.plan.sessions[0].items[0].reps) == (
        "高脚杯深蹲",
        "12",
    )
    got = edit(plan(), WD, [PlanEdit(kind="order", names=["罗马尼亚硬拉", "杠铃深蹲"])])
    assert [x.exercise for x in got.plan.sessions[0].items] == ["罗马尼亚硬拉", "杠铃深蹲"]
    assert (
        edit(plan(), WD, [PlanEdit(kind="order", names=["杠铃深蹲", "别的"])]).lines == []
    )  # 不是那天的动作


def test_safety_blocks_only_new_problems() -> None:
    hyper = frozenset({"hypertension"})
    low = edit(plan(), WD, [PlanEdit(kind="edit", exercise="杠铃深蹲", reps="5")], special=hyper)
    assert low.problems and "至少 8 次" in low.problems[0]  # 特殊情况的每组最少次数
    old = edit(plan("5"), WD, [PlanEdit(kind="edit", exercise="杠铃深蹲", sets=4)], special=hyper)
    assert old.ok  # 原来就是 5 次：这次没带来新问题，不挡
    jump = edit(plan(), WD, [PlanEdit(kind="swap", exercise="杠铃深蹲", to="波比跳")],
                special=frozenset({"pregnancy"}))  # fmt: skip
    assert jump.problems and "跳跃" in jump.problems[0]
    carried = edit(
        plan("5"), WD, [PlanEdit(kind="swap", exercise="杠铃深蹲", to="高脚杯深蹲")], special=hyper
    )
    assert carried.ok  # 原来每组就 5 次：换个动作不算新问题
    assert alternatives(plan("5"), WD, "杠铃深蹲", special=hyper)
    burpee = Plan(title="t", days_per_week=1, sessions=[Session(day=WD, name="全身", items=[
        PlanItem(exercise="波比跳", sets=3, reps="10"), PlanItem(exercise="杠铃卧推", sets=3, reps="10")])])  # fmt: skip
    preg = frozenset({"pregnancy"})
    other_jump = edit(
        burpee, WD, [PlanEdit(kind="swap", exercise="波比跳", to="药球蹲起抛墙")], special=preg
    )
    assert (
        other_jump.problems and "跳跃" in other_jump.problems[0]
    )  # 原来就是跳跃类，换成另一个跳跃类也挡
    alt = {a["name"] for a in alternatives(burpee, WD, "波比跳", special=preg)}
    assert alt and not {"药球蹲起抛墙", "哑铃单臂抓举"} & alt
    gone = edit(plan(), WD, [PlanEdit(kind="remove", exercise="杠铃深蹲")])
    assert gone.ok and any("没练到" in x for x in gone.warnings)  # 去掉动作只提醒
    more = edit(plan(), WD, [PlanEdit(kind="edit", exercise="杠铃深蹲", sets=10)])
    assert more.ok and any("分钟" in x for x in more.warnings)  # 时长超了只提醒


def test_alternatives_rank_and_filter() -> None:
    logs = [WorkoutLog(day=TODAY - timedelta(days=3), items=[
        LogItem(exercise="高脚杯深蹲", done_sets=[SetDone(reps=10, weight_kg=20)] * 2)])]  # fmt: skip
    alt = alternatives(plan(), WD, "杠铃深蹲", logs=logs)
    assert alt and alt[0]["same"] and len(alt) <= 6
    assert "罗马尼亚硬拉" not in [a["name"] for a in alt]  # 那天已经有的不列
    goblet = next(a for a in alt if a["name"] == "高脚杯深蹲")
    assert goblet["last"] == "上次 20×10、20×10"
    home = alternatives(plan(), WD, "杠铃深蹲", equipment=frozenset({"自重", "哑铃"}))
    assert home and all(set(a["equipment"]) & {"自重", "哑铃"} for a in home)  # type: ignore[arg-type]
    preg = alternatives(plan(), WD, "杠铃深蹲", special=frozenset({"pregnancy"}))
    assert not {"波比跳", "药球蹲起抛墙", "哑铃单臂抓举"} & {
        a["name"] for a in preg
    }  # 会被挡下的不列


# ---- 以后都改 --------------------------------------------------------------------------------


def test_always_saves_a_new_plan_that_can_be_undone(monkeypatch: pytest.MonkeyPatch) -> None:
    c, book, _ = client(monkeypatch)
    r = post(c, OTHER, "always", kind="swap", exercise="杠铃卧推", to="哑铃卧推")
    assert r.status_code == 200 and r.json()["draft"]["state"] == "confirmed"
    assert items(book, OTHER)[0][0] == "哑铃卧推"
    assert post(c, WD, "always", kind="edit", exercise="杠铃深蹲", sets=5).status_code == 200
    assert (
        post(c, WD, "always", kind="order", names=["罗马尼亚硬拉", "杠铃深蹲"]).status_code == 200
    )
    assert [x[:2] for x in items(book, WD)] == [("罗马尼亚硬拉", 3), ("杠铃深蹲", 5)]
    last = post(c, WD, "always", kind="remove", exercise="罗马尼亚硬拉").json()
    assert [x[0] for x in items(book, WD)] == ["杠铃深蹲"]
    c.post(f"/iron/api/drafts/{last['draft']['id']}/undo")
    assert [x[0] for x in items(book, WD)] == ["罗马尼亚硬拉", "杠铃深蹲"]  # 撤销回到上一版
    assert post(c, WD, "always", kind="remove", exercise="罗马尼亚硬拉").status_code == 200
    assert (
        post(c, WD, "always", kind="remove", exercise="杠铃深蹲").status_code == 409
    )  # 一天至少留一个


def test_always_swap_respects_equipment_and_safety(monkeypatch: pytest.MonkeyPatch) -> None:
    c, book, _ = client(monkeypatch, equipment=frozenset({"自重", "哑铃"}))
    r = post(c, WD, "always", kind="swap", exercise="杠铃深蹲", to="杠铃前蹲").json()
    assert r["notes"] and "你没有" in r["notes"][0]  # 器械没有：换成替代首选并说明
    assert items(book, WD)[0][0] != "杠铃前蹲"
    c, book, _ = client(monkeypatch, special=frozenset({"hypertension"}))
    bad = post(c, WD, "always", kind="edit", exercise="杠铃深蹲", reps="5")
    assert bad.status_code == 422 and "至少 8 次" in bad.json()["detail"]
    assert items(book, WD)[0] == ("杠铃深蹲", 3, "8")  # 挡下了：计划没变
    assert (
        post(c, OTHER, "today", kind="edit", exercise="杠铃卧推", sets=4).status_code == 422
    )  # 只改今天只能改今天


# ---- 只改今天 --------------------------------------------------------------------------------


def test_today_only_changes_today(monkeypatch: pytest.MonkeyPatch) -> None:
    c, book, days = client(monkeypatch)
    assert post(c, WD, "today", kind="edit", exercise="杠铃深蹲", sets=4).status_code == 200
    r = post(c, WD, "today", kind="swap", exercise="杠铃深蹲", to="高脚杯深蹲").json()
    assert r["today"]["items"][0] == {
        "exercise": "高脚杯深蹲",
        "sets": 4,
        "reps": "8",
        "load": "",
        "note": "",
    }
    assert items(book, WD)[0] == ("杠铃深蹲", 3, "8")  # 计划本身不变
    week = c.get("/iron/api/week").json()["days"]
    today = next(d for d in week if d["today"])
    assert today["session"]["items"][0]["exercise"] == "高脚杯深蹲" and len(today["edited"]) == 2
    assert all(not d["edited"] for d in week if not d["today"])
    tomorrow = next(d for d in week if d["date"] == (TODAY + timedelta(days=1)).isoformat())
    assert tomorrow["session"] is None or tomorrow["session"]["items"][0]["exercise"] == "杠铃卧推"
    live = c.post("/iron/api/live/start", json={"today_plan": True}).json()["live"]
    assert (
        live["items"][0]["exercise"] == "高脚杯深蹲" and len(live["items"][0]["sets"]) == 4
    )  # 记录器按改过的
    c.delete("/iron/api/live")
    state = asyncio.run(days.get("42", TODAY))
    assert state is not None and len(state.edits) == 2 and "高脚杯深蹲" in state.edits[1].line
    c.delete("/iron/api/plan/today")
    today = next(d for d in c.get("/iron/api/week").json()["days"] if d["today"])
    assert today["session"]["items"][0]["exercise"] == "杠铃深蹲" and today["edited"] == []


def test_today_edits_that_no_longer_apply_are_not_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, days = client(monkeypatch)
    post(c, WD, "today", kind="edit", exercise="杠铃深蹲", sets=4)
    post(c, WD, "today", kind="edit", exercise="罗马尼亚硬拉", sets=2)
    post(c, WD, "always", kind="swap", exercise="杠铃深蹲", to="高脚杯深蹲")  # 计划本身换掉了它
    today = next(d for d in c.get("/iron/api/week").json()["days"] if d["today"])
    assert len(today["edited"]) == 1 and "罗马尼亚硬拉" in today["edited"][0]
    assert today["session"]["items"][0]["sets"] == 3 and today["session"]["items"][1]["sets"] == 2
    state = asyncio.run(days.get("42", TODAY))
    assert state is not None and [e.exercise for e in state.edits] == [
        "罗马尼亚硬拉"
    ]  # 存的也去掉了


def test_today_version_and_coach_block_use_the_edits() -> None:
    edits = [
        PlanEdit(
            kind="swap", exercise="杠铃深蹲", to="高脚杯深蹲", line="周一：杠铃深蹲 → 高脚杯深蹲"
        )
    ]
    state = DayState(day=TODAY, edits=edits)
    v = today_version(
        Inputs(snapshot=asyncio.run(snapshot_of()("42")), plan=plan(), day=state), TODAY
    )
    assert v.today is not None and v.today["items"][0]["exercise"] == "高脚杯深蹲"
    assert today_session(plan().sessions[0], []) == plan().sessions[0]
    out = lines(state, today=TODAY, plan_name="下肢")
    assert "今天在计划页改过（只改今天）：周一：杠铃深蹲 → 高脚杯深蹲" in out


def test_alternatives_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client(monkeypatch, special=frozenset({"pregnancy"}))
    alt = c.get("/iron/api/plan/alternatives", params={"day": WD, "exercise": "杠铃深蹲"}).json()[
        "alternatives"
    ]
    assert alt and "波比跳" not in [a["name"] for a in alt]
    rest = (WD + 1) % 7 + 1  # 计划里只有今天和明天，后天休息
    assert (
        c.get("/iron/api/plan/alternatives", params={"day": rest, "exercise": "x"}).status_code
        == 409
    )


def test_page_has_edit_panel() -> None:
    assert "/iron/api/plan/edit" in JS and "/iron/api/plan/alternatives" in JS
    assert "只改今天" in JS and "以后都改" in JS and "排顺序" in JS and "恢复原计划" in JS
    assert "撤销" in JS[JS.index("function planEdited") :][:800]


def test_today_swap_stores_the_substitute_that_was_used(monkeypatch: pytest.MonkeyPatch) -> None:
    """独立审查（11-03，§122 需求 9）：只改今天换动作被系统换成替代动作时，存的是原来要的那个，
    今天的版本重放时不查器械、伤处，原来要的动作又回来了。改成存实际换上的。"""
    c, _, days = client(monkeypatch, equipment=frozenset({"自重", "哑铃"}))
    r = post(c, WD, "today", kind="swap", exercise="杠铃深蹲", to="杠铃前蹲").json()
    used = r["today"]["items"][0]["exercise"]
    assert used != "杠铃前蹲" and "你没有" in r["notes"][0]  # 器械没有：换成了替代动作
    state = asyncio.run(days.get("42", TODAY))
    assert state is not None and state.edits[0].to == used  # 存的是实际换上的
    today = next(d for d in c.get("/iron/api/week").json()["days"] if d["today"])
    assert today["session"]["items"][0]["exercise"] == used  # 今天的版本也是它，不是杠铃前蹲
