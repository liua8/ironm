"""首页和个人中心的完成反馈（spec [2026-10-23] §93）：本周应练次数不被改计划重置；目标进度百分比、达到目标只庆祝一次。"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.casefile import Snapshot
from ironm_agent.goal import Goal, GoalBook, progress
from ironm_agent.metrics import Profile, Readings, compute_all, weight_trend
from ironm_agent.training import StoredPlan, TrainingBook, lineage, plan_content, week_of
from tests.test_adjust import weights
from tests.test_coach import plan_today

TODAY = date.today()


def at(days_ago: int) -> datetime:
    return datetime.now().astimezone() - timedelta(days=days_ago)


def test_edits_keep_the_plan_start_and_new_plans_restart_it() -> None:
    p = plan_today()
    first = StoredPlan("a", p, at(20))
    edit1 = StoredPlan("b", p, at(5), edit=True)
    edit2 = StoredPlan("c", p, at(0), edit=True)
    assert lineage([first, edit1, edit2], edit2).since == (TODAY - timedelta(days=20))
    fresh = StoredPlan("d", p, at(2))  # 新排的计划
    edit3 = StoredPlan("e", p, at(0), edit=True)
    assert lineage([first, edit1, fresh, edit3], edit3).since == TODAY - timedelta(days=2)
    assert lineage([first], first).since == TODAY - timedelta(days=20)


def test_week_target_is_not_reset_by_an_edit() -> None:
    """项目负责人 10-30 首页"本周练了 5 / 1 次"：管家今天改了一下计划，开始日期被重置成今天。"""
    book = TrainingBook()

    async def go() -> Any:
        d = await book.add_draft("42", "plan", plan_content(plan_today()))
        await book.confirm("42", d.id)
        book._plans["42"] = [(replace(p, created=at(30)), a) for p, a in book._plans["42"]]
        e = await book.add_draft("42", "plan", plan_content(plan_today(), "管家复盘",
                                                            ops=[{"kind": "reduce", "ratio": 0.8}]))  # fmt: skip
        await book.confirm("42", e.id)
        return await book.plan("42")

    stored = asyncio.run(go())
    assert stored.edit and stored.since == TODAY - timedelta(days=30)
    week = week_of(stored.plan, [], TODAY, stored.since)
    assert week.planned == len(plan_today().sessions)  # 整周照常算，不只剩今天以后的


def test_plan_changed_mid_week_counts_each_day_by_the_plan_used_that_day() -> None:
    """项目负责人的账号：这周每天都新排了一份计划，今天又排了一份，本周只剩新计划的 1 次可练，前面练的 5 次全算"多练"。"""
    from ironm_agent.training import Plan, WorkoutLog, week_start

    monday = week_start(TODAY)
    if monday == TODAY:  # 周一换计划：这周前面没有别的日子，不用测
        return
    old = Plan.model_validate({"title": "旧", "days_per_week": 7, "sessions": [
        {"day": d, "name": f"练{d}", "items": [{"exercise": "高脚杯深蹲", "sets": 3, "reps": "10"}]} for d in range(1, 8)]})  # fmt: skip
    new = Plan.model_validate({"title": "新", "days_per_week": 1, "sessions": [
        {"day": 7, "name": "周日", "items": [{"exercise": "高脚杯深蹲", "sets": 3, "reps": "10"}]}]})  # fmt: skip
    before = datetime.combine(monday - timedelta(days=3), datetime.min.time()).astimezone()
    versions = [StoredPlan("old", old, before), StoredPlan("new", new, at(0))]
    stored = lineage(versions, versions[1])
    assert stored.since == TODAY and not versions[1].plan._earlier  # 存的那份不被改
    logs = [WorkoutLog(day=monday + timedelta(days=i)) for i in range((TODAY - monday).days)]
    week = week_of(stored.plan, logs, TODAY, stored.since)
    days_before = (TODAY - monday).days
    assert week.planned == days_before + (
        1 if TODAY.isoweekday() <= 7 else 0
    )  # 前几天按旧计划、之后按新计划
    assert week.done == days_before and week.done <= week.planned


def test_goal_progress_percent_and_celebrate_once(monkeypatch: pytest.MonkeyPatch) -> None:
    w = weights(-0.5)  # 从 80 掉到约 78.07
    g = Goal(75, TODAY + timedelta(days=60), TODAY - timedelta(days=27), start=80)
    p = progress(g, w, weight_trend(w, TODAY), TODAY)
    assert p["changed"] == round(w[0][1] - 80, 1) and p["percent"] == round(
        (w[0][1] - 80) / -5 * 100
    )
    assert not p["celebrate"]
    won = progress(replace(g, value=78), w, weight_trend(w, TODAY), TODAY)
    assert won["status"] == "reached" and won["percent"] == 100 and won["celebrate"]
    seen = progress(replace(g, value=78, celebrated=TODAY), w, weight_trend(w, TODAY), TODAY)
    assert not seen["celebrate"]
    assert Goal.of(replace(g, celebrated=TODAY).json()).celebrated == TODAY  # 存得下

    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more

    goals = GoalBook()
    asyncio.run(goals.set("42", replace(g, value=78)))

    async def snap(user_id: str, today: date | None = None) -> Snapshot:
        prof = Profile(height_cm=175, sex="male", goal="fat_loss", activity="moderate")
        r = Readings(weight=w)
        return Snapshot(prof, r, tuple(compute_all(r, prof, TODAY)), TODAY)

    monkeypatch.setattr(web, "snapshot_for", snap)
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web_more.goal_store] = lambda: goals
    c = TestClient(app)
    assert c.get("/iron/api/goal").json()["progress"]["celebrate"]
    assert not c.post("/iron/api/goal/celebrated").json()["progress"]["celebrate"]
    assert not c.get("/iron/api/goal").json()["progress"]["celebrate"]  # 只庆祝一次
    by = (TODAY + timedelta(days=90)).isoformat()
    c.put("/iron/api/goal", json={"value": 72, "by": by})
    assert asyncio.run(goals.get("42")).celebrated is None  # type: ignore[union-attr]  # 新目标重新计
