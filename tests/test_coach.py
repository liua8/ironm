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
                 pains=[("joint.knee", TODAY), ("joint.knee", TODAY - timedelta(days=3))],
                 goal=Goal(72, TODAY + timedelta(days=90), TODAY - timedelta(days=30), start=80))  # fmt: skip
    items = {x.key: x for x in compute(inp, TODAY)}
    today = items["today"]
    assert (
        today.title == "管家正在看今天的情况" and "组数减半" not in today.title
    )  # 只睡 4 小时也不按规则减半（§163）
    target = items["target:杠铃深蹲"]  # 管家没定：照上次，不按规则加重（§163 需求 6）
    assert target.title == "杠铃深蹲 下次 60 公斤 × 9 次 × 4 组" and target.why.startswith("照上次")
    assert "照上次" in target.basis and "规则" not in target.basis + target.why and target.value["by"] == "last"
    assert items["kcal"].title.startswith("每天约") and items["kcal"].action == "auto"
    assert not any(k.startswith("proposal:") for k in items)  # 减脂体重持平也不出规则的热量建议
    assert (
        "alert:pain" not in items and "proposal:review" not in items
    )  # 规则的提醒、每周建议都交给管家（§163）
    assert items["goal"].kind == "goal" and items["retest"].kind == "retest"
    kinds = [x.kind for x in compute(inp, TODAY)]
    assert kinds[0] == "today" and "alert" not in kinds and kinds.index("kcal") < kinds.index("target")
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
    assert {c.key for c in c1} == {x.key for x in s1.items} - {"today"}  # 管家还没看：今天不算一次调整
    same, none = asyncio.run(evaluate("42", dp, reason="每天第一次打开", force=False))
    assert same.version == 1 and none == []  # 今天评估过：不重复算
    again, none2 = asyncio.run(evaluate("42", dp, reason="记饮食"))
    assert again.version == 1 and none2 == []  # 有新情况但方案没变：不出新版本
    from ironm_agent.coach_state import Done, Review

    note = Review(
        day=TODAY,
        done=[Done(key="review:note", type="note", title="这周多喝水", why="练得多", basis="F1")],
    )
    asyncio.run(
        dp.store.save("42", s1.model_copy(update={"review": note}), [])
    )  # 管家复盘提醒了一句
    s2, c2 = asyncio.run(evaluate("42", dp, reason="复盘"))
    assert s2.version == 2 and ("review:note", "added") in [(c.key, c.change) for c in c2]
    asyncio.run(dp.store.save("42", s2.model_copy(update={"review": Review(day=TODAY)}), []))
    s3, c3 = asyncio.run(evaluate("42", dp, reason="复盘"))
    assert ("review:note", "removed") in [(c.key, c.change) for c in c3] and s3.version == 3
    assert "alert:pain" not in {x.key for x in s3.items}  # 规则的"反复疼"提醒不再有（§163）


def test_next_day_today_item_counts_as_a_change() -> None:
    dp = deps(training=with_plan())
    from ironm_agent.coach_state import Review

    asyncio.run(evaluate("42", dp, reason="x", today=TODAY - timedelta(days=1)))
    s, changes = asyncio.run(evaluate("42", dp, reason="每天第一次打开", force=False))
    assert s.day == TODAY and not any(c.key == "today" for c in changes)  # 管家正在看：不算调整（复核 11-05）
    asyncio.run(dp.store.save("42", s.model_copy(update={"review": Review(day=TODAY)}), []))
    s, changes = asyncio.run(evaluate("42", dp, reason="复盘"))
    assert any(c.key == "today" and c.change == "changed" for c in changes)  # 看完了：记一次


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
    logs = [squat(5), squat(3)]  # 又记了一次：照上次的次数变了
    changed = diff(
        old, compute(Inputs(snapshot=snap(), plan=plan_today(), logs=logs), TODAY), TODAY, 2
    )
    assert [(c.key, c.change) for c in changed] == [("target:杠铃深蹲", "changed")]
    assert "× 7 次" in changed[0].before and "× 9 次" in changed[0].after


def test_coach_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more

    dp = deps(training=with_plan(), pain=PainBook())
    dp.pain.rows["42"] = [("joint.knee", TODAY), ("joint.knee", TODAY - timedelta(days=1))]
    monkeypatch.setattr(web_more, "coach_deps", lambda: dp)
    from ironm_agent import review

    woke: list[str] = []
    monkeypatch.setattr(review, "daily_later", lambda uid, deps: woke.append(uid))
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    c = TestClient(app)
    r = c.get("/iron/api/coach").json()
    assert woke == ["42"]  # 首页打开也叫醒管家跑当天的复盘（两周模拟 11-05）
    assert r["version"] == 1 and r["items"][0]["key"] == "today"
    assert "proposal:diet" not in {x["key"] for x in r["pending"]}  # 规则的热量建议去掉了（§163 需求 6）
    assert "alert:pain" not in {x["key"] for x in r["items"]}
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
    from tests.test_turn_flow import Coach, agent

    a = agent(
        Coach(said={"pain": [{"part": "膝", "side": "左"}]}),
        monkeypatch=monkeypatch,
        memory=MemoryBook(),
    )
    a._pain = PainBook()  # 管家判断他说了左膝疼（§114、§163）

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
    assert "每天第一次提问" in reasons and "说了今天的状态" in reasons
    assert a._pain.rows["42"] and a._pain.more["42"][0]["side"] == "左"


# ---- 对话里的管家消息（spec [2026-10-23] §26）--------------------------------------------------


def coach_proposed(dp: Deps) -> None:
    """管家今天的复盘提了一条改计划（要他确认）：规则的热量建议去掉后，用它测待确认的流程。"""
    from ironm_agent.coach_state import Done, Review

    s, _ = asyncio.run(evaluate("42", dp, reason="打卡"))
    done = [Done(key="review:propose", type="propose", title="建议这样改计划：深蹲换高脚杯深蹲",
                 why="膝盖不舒服", basis="F1")]  # fmt: skip
    asyncio.run(dp.store.save("42", s.model_copy(update={"review": Review(day=TODAY, done=done)}), []))


def test_inbox_pending_unseen_and_choices() -> None:
    from ironm_agent.coach_state import decide, mark_seen, pending, unseen

    pain = PainBook()
    pain.rows["42"] = [("joint.knee", TODAY), ("joint.knee", TODAY - timedelta(days=2))]
    dp = deps(training=with_plan(), pain=pain)
    coach_proposed(dp)
    s1, _ = asyncio.run(evaluate("42", dp, reason="打卡"))
    history = asyncio.run(dp.store.history("42"))
    news = unseen(s1, history)
    assert news and all(c.status != "confirm" for c in news)  # 要确认的不在"改了什么"里重复
    assert "review:propose" in {x.key for x in pending(s1, TODAY)}
    asyncio.run(mark_seen(dp.store, "42", s1.version))
    s1b = asyncio.run(dp.store.get("42"))
    assert s1b is not None and s1b.seen == s1.version and unseen(s1b, history) == []
    item = asyncio.run(decide(dp.store, "42", "review:propose", "later"))
    assert item is not None and item.key == "review:propose"
    s2 = asyncio.run(dp.store.get("42"))
    assert s2 is not None and "review:propose" not in {
        x.key for x in pending(s2, TODAY)
    }  # 暂不：今天不再问
    assert "review:propose" in {x.key for x in pending(s2, TODAY + timedelta(days=1))}  # 明天再问
    asyncio.run(decide(dp.store, "42", "review:propose", "accept"))
    s3 = asyncio.run(dp.store.get("42"))
    assert s3 is not None and "review:propose" not in {
        x.key for x in pending(s3, TODAY + timedelta(days=3))
    }
    kinds = [c.change for c in asyncio.run(dp.store.history("42"))[:2]]
    assert kinds == ["accepted", "declined"]  # 选择写进调整经历
    assert asyncio.run(decide(dp.store, "42", "kcal", "accept")) is None  # 不用确认的不接受选择
    s4, _ = asyncio.run(evaluate("42", dp, reason="说疼"))  # 重新评估时保留看过的版本和选择
    assert s4.seen == s1.version and "review:propose" in s4.choices


def test_inbox_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more

    pain = PainBook()
    pain.rows["42"] = [("joint.knee", TODAY), ("joint.knee", TODAY - timedelta(days=1))]
    dp = deps(training=with_plan(), pain=pain)
    coach_proposed(dp)
    asyncio.run(evaluate("42", dp, reason="打卡"))
    monkeypatch.setattr(web_more, "coach_deps", lambda: dp)
    from ironm_agent import review as review_mod

    monkeypatch.setattr(review_mod, "daily_later", lambda *a: None)  # 不在测试里叫真实模型
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    c = TestClient(app)
    r = c.get("/iron/api/coach/inbox").json()
    assert r["changes"] and {x["key"] for x in r["pending"]} >= {"review:propose"}
    assert c.post("/iron/api/coach/seen", json={"version": r["version"]}).status_code == 200
    assert c.get("/iron/api/coach/inbox").json()["changes"] == []  # 看过的不再出现
    d = c.post("/iron/api/coach/decide", json={"key": "review:propose", "decision": "later"})
    assert d.status_code == 200 and d.json()["item"]["key"] == "review:propose"
    assert "review:propose" not in {
        x["key"] for x in c.get("/iron/api/coach/inbox").json()["pending"]
    }
    assert (
        c.post("/iron/api/coach/decide", json={"key": "nope", "decision": "accept"}).status_code
        == 404
    )
