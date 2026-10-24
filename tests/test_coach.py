"""管家的当前方案与调整经历（spec [2026-10-23] §23 第 1 步）。不调用真实模型、不连数据库。"""

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.casefile import Snapshot
from ironm_agent.coach_state import CoachBook, Deps, Inputs, compute, diff, evaluate
from ironm_agent.diet_adjust import DietBook
from ironm_agent.goal import Goal, GoalBook
from ironm_agent.metrics import Profile, Readings, compute_all
from ironm_agent.training import LogItem, Plan, SetDone, TrainingBook, WorkoutLog, plan_content
from ironm_agent.triggers import PainBook

TODAY = date.today()


def plan_today() -> Plan:
    return Plan.model_validate({"title": "x", "days_per_week": 3, "sessions": [
        {"day": TODAY.isoweekday(), "name": "下肢", "minutes": 60, "items": [
            {"exercise": "杠铃深蹲", "sets": 4, "reps": "6–8"},
            {"exercise": "罗马尼亚硬拉", "sets": 3, "reps": "8–10"}]},
        {"day": (TODAY.isoweekday() + 1) % 7 + 1, "name": "上肢", "items": [
            {"exercise": "哑铃卧推", "sets": 3, "reps": "8–10"}]}]})  # fmt: skip


def snap(sleep: float = 7.5, per_week: float = 0.0) -> Snapshot:
    p = Profile(
        height_cm=178, birth=date(1994, 5, 1), sex="male", goal="fat_loss", activity="moderate"
    )
    w = tuple(
        (TODAY - timedelta(days=i), round(80 + per_week / 7 * (27 - i), 2)) for i in range(28)
    )
    r = Readings(weight=w, sleep_hours=((TODAY, sleep),))
    return Snapshot(p, r, tuple(compute_all(r, p, TODAY)), TODAY)


def squat(back: int, reps: int = 9) -> WorkoutLog:
    sets = [SetDone(reps=reps, weight_kg=60)] * 4
    return WorkoutLog(day=TODAY - timedelta(days=back), session="下肢",
                      items=[LogItem(exercise="杠铃深蹲", done_sets=sets)])  # fmt: skip


def test_compute_lists_each_item_with_reason_and_basis() -> None:
    inp = Inputs(snapshot=snap(sleep=4.0), plan=plan_today(), logs=[squat(9), squat(5)],
                 pains=[("knee", TODAY), ("knee", TODAY - timedelta(days=3))],
                 goal=Goal(72, TODAY + timedelta(days=90), TODAY - timedelta(days=30), start=80))  # fmt: skip
    items = {x.key: x for x in compute(inp, TODAY)}
    today = items["today"]
    assert today.action == "auto" and "组数减半" in today.title and "4" in today.why
    assert "〔K07〕" in today.basis
    assert (
        items["target:杠铃深蹲"].title.startswith("杠铃深蹲 下次 62.5 公斤")
        and "〔K03〕" in items["target:杠铃深蹲"].basis
    )
    assert items["kcal"].title.startswith("每天约") and items["kcal"].action == "auto"
    diet = items["proposal:diet"]  # 减脂体重持平：建议少吃
    assert diet.action == "confirm" and "少吃约 200 千卡" in diet.title and "〔K37〕" in diet.basis
    assert items["alert:pain"].action == "confirm" and "〔K33〕" in items["alert:pain"].basis
    assert items["goal"].kind == "goal" and items["retest"].kind == "retest"
    kinds = [x.kind for x in compute(inp, TODAY)]
    assert kinds[0] == "today" and kinds.index("alert") < kinds.index("kcal") < kinds.index(
        "target"
    )
    rest = {x.key: x for x in compute(Inputs(snapshot=snap()), TODAY)}
    assert rest["today"].title == "还没有训练计划" and "proposal:review" not in rest


def deps(**kw: Any) -> Deps:
    book = kw.pop("training", TrainingBook())
    s = kw.pop("snapshot", snap())

    async def snapshot(_: str) -> Snapshot:
        return s

    return Deps(snapshot=snapshot, training=book, pain=kw.pop("pain", PainBook()),
                goals=kw.pop("goals", GoalBook()), diet=kw.pop("diet", DietBook()),
                store=kw.pop("store", CoachBook()))  # fmt: skip


def with_plan() -> TrainingBook:
    book = TrainingBook()
    d = asyncio.run(book.add_draft("42", "plan", plan_content(plan_today())))
    asyncio.run(book.confirm("42", d.id))
    return book


def test_evaluate_versions_and_changes() -> None:
    pain = PainBook()
    dp = deps(training=with_plan(), pain=pain, snapshot=snap(per_week=-0.4))
    s1, c1 = asyncio.run(evaluate("42", dp, reason="打卡"))
    assert s1.version == 1 and c1 and all(c.change == "added" for c in c1)
    assert {c.key for c in c1} == {x.key for x in s1.items}
    same, none = asyncio.run(evaluate("42", dp, reason="每天第一次打开", force=False))
    assert same.version == 1 and none == []  # 今天评估过：不重复算
    again, none2 = asyncio.run(evaluate("42", dp, reason="记饮食"))
    assert again.version == 1 and none2 == []  # 有新情况但方案没变：不出新版本
    pain.rows["42"] = [("knee", TODAY), ("knee", TODAY - timedelta(days=2))]
    s2, c2 = asyncio.run(evaluate("42", dp, reason="说疼"))
    assert s2.version == 2 and [(c.key, c.change) for c in c2] == [("alert:pain", "added")]
    assert c2[0].why and c2[0].basis and c2[0].status == "confirm"
    pain.rows["42"] = []
    s3, c3 = asyncio.run(evaluate("42", dp, reason="说疼"))
    assert [(c.key, c.change) for c in c3] == [("alert:pain", "removed")] and s3.version == 3
    history = asyncio.run(dp.store.history("42"))
    assert history[0].key == "alert:pain" and len(history) == len(c1) + 2


def test_next_day_today_item_counts_as_a_change() -> None:
    dp = deps(training=with_plan())
    asyncio.run(evaluate("42", dp, reason="x", today=TODAY - timedelta(days=1)))
    s, changes = asyncio.run(evaluate("42", dp, reason="每天第一次打开", force=False))
    assert s.day == TODAY and any(c.key == "today" and c.change == "changed" for c in changes)


def test_log_has_counts_not_content(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO, logger="ironm_agent.coach_state")
    asyncio.run(evaluate("42", deps(training=with_plan()), reason="打卡"))
    text = caplog.text
    assert "coach evaluated" in text and "下肢" not in text and "深蹲" not in text


def test_diff_detects_title_changes() -> None:
    from datetime import datetime

    from ironm_agent.coach_state import State

    first = compute(Inputs(snapshot=snap(), plan=plan_today(), logs=[squat(3, reps=7)]), TODAY)
    old = State(version=1, day=TODAY, at=datetime.now(), reason="x", items=first)
    logs = [squat(5), squat(3)]  # 连续两次都超过次数上限：下次加重
    changed = diff(
        old, compute(Inputs(snapshot=snap(), plan=plan_today(), logs=logs), TODAY), TODAY, 2
    )
    assert [(c.key, c.change) for c in changed] == [("target:杠铃深蹲", "changed")]
    assert "60 公斤" in changed[0].before and "62.5 公斤" in changed[0].after


def test_coach_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more

    dp = deps(training=with_plan(), pain=PainBook())
    dp.pain.rows["42"] = [("knee", TODAY), ("knee", TODAY - timedelta(days=1))]
    monkeypatch.setattr(web_more, "coach_deps", lambda: dp)
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    c = TestClient(app)
    r = c.get("/iron/api/coach").json()
    assert r["version"] == 1 and r["items"][0]["key"] == "today"
    assert {x["key"] for x in r["pending"]} >= {"alert:pain"}
    assert r["changes"] and all(x["day"] == TODAY.isoformat() for x in r["changes"])
    assert c.get("/iron/api/coach").json()["version"] == 1  # 同一天再打开不重复算
    assert c.get("/iron/api/coach/history").json()["changes"]


def test_events_trigger_reevaluation(
    coach_in_memory: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more
    from ironm_agent.meals import MealBook
    from ironm_agent.memory_store import MemoryBook

    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web.training_store] = TrainingBook
    app.dependency_overrides[web.memory_store] = MemoryBook
    app.dependency_overrides[web_more.meal_store] = MealBook
    app.dependency_overrides[web_more.goal_store] = GoalBook
    app.dependency_overrides[web_more.pain_store] = PainBook
    monkeypatch.setattr(web, "refresh_later", lambda *a: None)

    async def s(user_id: str, today: date | None = None) -> Snapshot:
        return snap()

    monkeypatch.setattr(web, "snapshot_for", s)
    c = TestClient(app)
    assert c.post("/iron/api/workouts", json={"session": "下肢"}).status_code == 200
    c.post("/iron/api/meals", data={"kind": "lunch", "text": "牛肉面一碗"})
    c.put("/iron/api/goal", json={"value": 72, "by": (TODAY + timedelta(days=60)).isoformat()})
    reasons = [r for _, r in coach_in_memory]
    assert reasons[:1] == ["打卡"] and "改目标" in reasons


def test_chat_triggers_daily_and_pain_reevaluation(
    coach_in_memory: list[tuple[str, str]], monkeypatch: pytest.MonkeyPatch
) -> None:
    from ironm_agent.memory_store import MemoryBook
    from tests.test_turn_flow import Team, agent

    a = agent(Team("recovery"), monkeypatch=monkeypatch, memory=MemoryBook())
    a._pain = PainBook()

    async def go(text: str) -> None:
        [
            b
            async for b in a.generate_response(
                "42", [{"role": "user", "content": text}], session_id="42:s1"
            )
        ]
        await a.settle()

    asyncio.run(go("我左膝最近又疼了，深蹲要注意什么"))
    reasons = [r for _, r in coach_in_memory]
    assert "每天第一次提问" in reasons and "说疼" in reasons
