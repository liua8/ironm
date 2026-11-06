"""计划与饮食的动态调整（spec [2026-10-23] §18）。不调用真实模型。"""

import asyncio
from dataclasses import replace
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.casefile import Snapshot
from ironm_agent.memory_store import MemoryBook
from ironm_agent.metrics import Profile, Readings, compute_all
from ironm_agent.protools.plan_check import changed_days, check_plan
from ironm_agent.render import plan_card
from ironm_agent.training import Plan, TrainingBook, plan_content

TODAY = date.today()


def plan_of(*sessions: tuple[int, str]) -> Plan:
    return Plan.model_validate(
        {"title": "三练", "days_per_week": len(sessions),
         "sessions": [{"day": d, "name": n, "items": [{"exercise": "高脚杯深蹲", "sets": 3, "reps": "10"}]} for d, n in sessions]}
    )  # fmt: skip


OLD = plan_of((1, "全身A"), (3, "全身B"), (5, "全身C"))


# ---- 需求 1：每周复盘直接出方案 ------------------------------------------------------------------


def test_changed_days_and_review_limit() -> None:
    two = plan_of((1, "全身A"), (3, "上肢"), (6, "下肢"))  # 周三改了、周五去掉、周六新增 = 3 天
    assert changed_days(two, OLD) == 3
    assert any(
        "最多改 2 天" in p for p in check_plan(two, current=OLD, max_changed_days=2).problems
    )
    one = plan_of((1, "全身A"), (3, "上肢"), (5, "全身C"))
    assert (
        changed_days(one, OLD) == 1
        and not check_plan(one, current=OLD, max_changed_days=2).problems
    )
    assert not any(
        "最多改" in p for p in check_plan(two, current=OLD).problems
    )  # 对话里改计划不限天数


class FakeAgent:
    """假装走了一遍改计划的链路：存一份预览，返回预览卡片。"""

    def __init__(self, training: TrainingBook, new: Plan) -> None:
        self.training, self.new, self.asked = training, new, ""

    async def generate_response(
        self, user_id: str, messages: list[dict[str, Any]], **_: Any
    ) -> Any:
        self.asked = messages[-1]["content"]
        draft = await self.training.add_draft(
            user_id, "plan", plan_content(self.new, "周三改成上肢")
        )
        yield {"type": "text", "text": "按复盘把周三改成了上肢。"}
        for b in plan_card(draft, self.new, OLD):
            yield b


def client(
    monkeypatch: pytest.MonkeyPatch, new: Plan, tips: list[str]
) -> tuple[TestClient, TrainingBook, dict[str, Any]]:
    from mirobody.server.auth import verify_token

    from ironm_agent import brief, web, web_more

    book = TrainingBook()
    asyncio.run(book.add_draft("42", "plan", plan_content(OLD)))
    d = asyncio.run(book.add_draft("42", "plan", plan_content(OLD)))
    asyncio.run(book.confirm("42", d.id))
    seen: dict[str, Any] = {}

    def fake_agent(training: TrainingBook, memory: Any) -> FakeAgent:
        seen["agent"] = FakeAgent(training, new)
        return seen["agent"]

    async def snap(user_id: str, today: date | None = None) -> Snapshot:
        p = Profile(height_cm=175, sex="male", goal="muscle", activity="moderate")
        r = Readings(weight=tuple((TODAY - timedelta(days=i), 70.0) for i in range(20)))
        return Snapshot(p, r, tuple(compute_all(r, p, TODAY)), TODAY)

    monkeypatch.setattr(web, "snapshot_for", snap)
    monkeypatch.setattr(web_more, "make_agent", fake_agent)
    monkeypatch.setattr(brief, "weekly_review", lambda *a, **k: {"tips": tips})
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web_more.training_store] = lambda: book
    app.dependency_overrides[web_more.memory_store] = MemoryBook
    app.dependency_overrides[web.training_store] = lambda: book
    return TestClient(app), book, seen


def test_review_proposal_only_hands_over_what_the_coach_proposed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """§163：规则的每周复盘、按提醒生成的改法去掉了；管家没提，就是这周不用改，也不再请模型另生成一份。"""
    c, _, seen = client(
        monkeypatch,
        plan_of((1, "全身A")),
        ["这周计划 3 次只练了 1 次，不到一半：可以把每周训练减到 2 天。"],
    )
    assert c.post("/iron/api/review/proposal").json()["status"] == "no_change"
    assert c.post("/iron/api/review/proposal?trigger=pain").json()["status"] == "no_change"
    assert "agent" not in seen


def test_chain_sends_back_a_review_plan_that_changes_too_much() -> None:
    from ironm_agent.actions import NEW_PLAN
    from ironm_agent.plugin import REVIEW_ASK
    from ironm_agent.protools.registry import ToolContext
    from tests.test_protools_wiring import new_plan_desk

    too_much = plan_of((2, "a"), (4, "b"), (6, "c")).model_dump(mode="json")
    ok = plan_of((1, "全身A"), (3, "上肢"), (5, "全身C"))
    tools = ToolContext.build(
        TODAY, goal="muscle", weight_kg=70, readings=None, injured=[], equipment_said=[]
    )
    desk, run = new_plan_desk(OLD, REVIEW_ASK + "：……", tools)
    said = asyncio.run(desk.run(NEW_PLAN, {"plan": too_much, "changes": "", "kind": "rewrite"}))
    assert "最多改 2 天" in said and desk.plan is None  # 退回给它改（§120）
    said = asyncio.run(
        desk.run(NEW_PLAN, {"plan": ok.model_dump(mode="json"), "changes": "", "kind": "rewrite"})
    )
    assert "最多改 2 天" not in said and run["plan_check"] == "fixed"  # 改了再交，检查通过


# ---- 需求 2：饮食目标能真正调整 ------------------------------------------------------------------

from ironm_agent.diet_adjust import DietBook  # noqa: E402
from ironm_agent.metrics import KcalAdjust  # noqa: E402


def snap_with(
    goal: str,
    per_week: float,
    *,
    sex: str = "male",
    start: float = 80.0,
    adjust: KcalAdjust | None = None,
) -> Snapshot:
    p = Profile(height_cm=175, birth=date(1995, 1, 1), sex=sex, goal=goal, activity="moderate")  # type: ignore[arg-type]
    r = Readings(
        weight=tuple(
            (TODAY - timedelta(days=i), round(start + per_week / 7 * (27 - i), 2))
            for i in range(28)
        )
    )
    return Snapshot(p, r, tuple(compute_all(r, p, TODAY, adjust)), TODAY)


def test_kcal_limits_keep_the_safe_floor_for_a_small_woman() -> None:
    """规则的热量建议去掉了（§163 需求 6）；管家要减多少，代码照样守住基础代谢和女 1200 的下限。"""
    from ironm_agent.diet_adjust import _apply

    small = snap_with("fat_loss", 0.0, sex="female", start=45.0)
    target = next(m for m in small.metrics if m.key == "kcal_target").value or 0
    bmr = next(m for m in small.metrics if m.key == "bmr").value or 0
    p, why = _apply(-300, "x", "x", target_now=target, bmr=bmr, profile=small.profile, current=None)
    assert p is None or p.after >= max(1200, round(bmr))  # 不低于基础代谢与安全下限
    if p is None:
        assert "下限" in why


def test_no_tiny_proposals_at_the_floor() -> None:
    """两周模拟 11-05：目标已经贴着下限时，减 200 被卡成每天少几千卡，不再提。"""
    from ironm_agent.diet_adjust import MIN_STEP, _apply

    woman = snap_with("fat_loss", 0.0, sex="female", start=60.0).profile
    p, why = _apply(-200, "体重没降", "x", target_now=1354, bmr=1350, profile=woman, current=None)
    assert p is None and "下限" in why  # 只剩 4 千卡
    man = snap_with("fat_loss", 0.0).profile
    flip, _ = _apply(-200, "体重没降", "x", target_now=1354, bmr=1350, profile=man, current=None)
    assert flip is None  # 下限比现在的目标还高：要减却成了多吃，不提
    ok, _ = _apply(-200, "体重没降", "x", target_now=2200, bmr=1600, profile=snap_with("fat_loss", 0.0).profile,
                   current=None)  # fmt: skip
    assert ok is not None and abs(ok.delta) >= MIN_STEP


def test_target_includes_adjustment() -> None:
    adj = KcalAdjust(-200, TODAY, "减脂期体重这几周没有下降")
    base = next(m for m in snap_with("fat_loss", 0.0).metrics if m.key == "kcal_target")
    after = next(
        m for m in snap_with("fat_loss", 0.0, adjust=adj).metrics if m.key == "kcal_target"
    )
    assert after.value is not None and base.value is not None and after.value == base.value - 200
    assert "调整 -200" in after.how and "没有下降" in after.how


def test_diet_book_apply_and_undo() -> None:
    b = DietBook()
    asyncio.run(b.apply("42", KcalAdjust(-200, TODAY, "a")))
    asyncio.run(b.apply("42", KcalAdjust(-400, TODAY, "b")))
    assert asyncio.run(b.current("42")).kcal == -400  # type: ignore[union-attr]
    assert asyncio.run(b.undo("42")).kcal == -200  # type: ignore[union-attr]
    assert asyncio.run(b.undo("42")) is None and asyncio.run(b.current("42")) is None
    assert asyncio.run(b.current("7")) is None


def test_diet_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more

    book = DietBook()

    async def snap(user_id: str, today: date | None = None) -> Snapshot:
        return snap_with("fat_loss", 0.0, adjust=await book.current(user_id))

    monkeypatch.setattr(web, "snapshot_for", snap)
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web_more.diet_store] = lambda: book
    c = TestClient(app)
    r = c.get("/iron/api/diet/review").json()
    assert r["current"] is None and "proposal" not in r  # 体重没降也不出规则建议（§163 需求 6）
    assert r["weight_trend"]  # 只给事实：体重趋势
    before = r["target"]
    assert c.post("/iron/api/diet/adjust").status_code == 410  # 确认规则建议的接口停用
    assert asyncio.run(book.current("42")) is None
    asyncio.run(book.apply("42", KcalAdjust(-200, TODAY, "管家复盘：两周体重没降")))  # 管家复盘调的
    r2 = c.get("/iron/api/diet/review").json()
    assert r2["current"]["kcal"] == -200 and r2["target"] == before - 200
    r3 = c.post("/iron/api/diet/adjust/undo").json()  # 撤销照旧
    assert r3["current"] is None and r3["target"] == before
    assert c.post("/iron/api/diet/adjust/undo").status_code == 404


# ---- 需求 3：今天的版本 -----------------------------------------------------------------------

from ironm_agent import today as today_mod  # noqa: E402
from ironm_agent.protools.plan_check import estimate_minutes  # noqa: E402
from ironm_agent.training import Session  # noqa: E402


def leg_day(minutes: int = 60) -> Session:
    return Session.model_validate(
        {"day": TODAY.isoweekday(), "name": "下肢", "minutes": minutes, "items": [
            {"exercise": "杠铃深蹲", "sets": 4, "reps": "6–8"},
            {"exercise": "罗马尼亚硬拉", "sets": 3, "reps": "8–10"},
            {"exercise": "腿弯举", "sets": 3, "reps": "10–12"},
            {"exercise": "提踵", "sets": 3, "reps": "12–15"},
            {"exercise": "慢跑", "sets": 1, "reps": "20 分钟"}]}
    )  # fmt: skip


def test_today_tired_halves_sets_and_says_why() -> None:
    s = leg_day()
    v = today_mod.build(s, tired=True, tired_why="最近一晚只睡了 4.5 小时")
    assert [x.sets for x in v.session.items] == [2, 1, 1, 1, 1]  # 减半、至少 1 组
    assert today_mod.TIRED_NOTE in v.changes[0] and not v.session.items[0].note  # 备注只写一次
    assert v.changed and "组数减半" in v.changes[0] and v.reasons == ("最近一晚只睡了 4.5 小时",)
    assert [x.sets for x in s.items] == [4, 3, 3, 3, 1]  # 原计划不变
    assert not today_mod.build(s).changed


def test_today_indoor_swaps_outdoor_cardio() -> None:
    v = today_mod.build(leg_day(), indoor=True, indoor_why="空气质量指数 180，不宜户外运动")
    assert v.session.items[-1].exercise == today_mod.INDOOR
    assert "原来是慢跑" in v.session.items[-1].note and "慢跑" in v.changes[0]
    assert v.reasons == ("空气质量指数 180，不宜户外运动",)
    assert v.session.items[0].exercise == "杠铃深蹲"  # 力量动作不换


def test_today_trims_to_fit_minutes() -> None:
    s = leg_day()
    assert estimate_minutes(s) > 30
    v = today_mod.build(s, minutes=30)
    assert estimate_minutes(v.session) <= 30 and v.session.minutes == 30
    names = [x.exercise for x in v.session.items]
    assert "杠铃深蹲" in names  # 先删辅助动作，主项留下
    assert "去掉" in v.changes[0] and v.reasons == ("今天只有 30 分钟",)
    assert not today_mod.build(s, minutes=120).changed  # 放得下：不改


def test_today_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from mirobody.server.auth import verify_token

    from ironm_agent import weather, web, web_more
    from ironm_agent.training import Plan

    book = TrainingBook()
    real_today = date.today()
    session = leg_day().model_copy(update={"day": real_today.isoweekday()})
    plan = Plan.model_validate(
        {"title": "x", "days_per_week": 1, "sessions": [session.model_dump()]}
    )
    d = asyncio.run(book.add_draft("42", "plan", plan_content(plan)))
    asyncio.run(book.confirm("42", d.id))
    sleep = {"h": 4.0}

    async def snap(user_id: str, today: date | None = None) -> Snapshot:
        p = Profile(height_cm=175, sex="male", goal="muscle", activity="moderate")
        r = Readings(sleep_hours=((real_today, sleep["h"]),))
        return Snapshot(p, r, tuple(compute_all(r, p, real_today)), real_today)

    async def no_weather(user_id: str) -> None:
        return None

    monkeypatch.setattr(web, "snapshot_for", snap)
    monkeypatch.setattr(weather, "for_user", no_weather)
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web_more.training_store] = lambda: book
    c = TestClient(app)
    from ironm_agent import review as review_mod
    from ironm_agent.coach_state import Review

    rerun: list[str] = []
    monkeypatch.setattr(review_mod, "rerun_later", lambda uid, deps, reason: rerun.append(reason))
    woke: list[str] = []
    monkeypatch.setattr(review_mod, "daily_later", lambda uid, deps: woke.append(uid))
    seen: dict[str, Any] = {"review": None}

    async def today_review(_: str) -> Any:
        return seen["review"]

    monkeypatch.setattr(web_more, "review_today", today_review)
    r = c.get("/iron/api/today").json()
    assert (
        r["status"] == "reviewing" and r["original"]["items"][0]["sets"] == 4
    )  # 管家还没看：如实说（§163）
    assert woke == ["42"]  # 只开了首页也叫醒管家跑当天的复盘（两周模拟 11-05）
    seen["review"] = Review(day=real_today, failed=True)
    assert c.get("/iron/api/today").json()["status"] == "coach_error"  # 管家出错了：不按规则替它定
    seen["review"] = Review(day=real_today, summary="睡得少，照计划练，留点余力")
    r = c.get("/iron/api/today").json()
    assert (
        r["status"] == "ok" and not r["changed"] and r["today"]["items"][0]["sets"] == 4
    )  # 只睡 4 小时也不减半
    r2 = c.get("/iron/api/today?minutes=30").json()
    assert r2["status"] == "reviewing" and rerun == [
        "首页点了今天的状态"
    ]  # 点了：叫醒管家重看，不当场删减
    assert c.get("/iron/api/today?minutes=5").status_code == 422
    assert asyncio.run(book.plan("42")).plan.sessions[0].items[0].sets == 4  # 原计划不变
    # 按今天的版本打卡：动作和组数一起记下
    app.dependency_overrides[web.training_store] = lambda: book
    app.dependency_overrides[web.memory_store] = MemoryBook
    monkeypatch.setattr(web, "refresh_later", lambda *a: None)
    w = c.post("/iron/api/workouts", json={"session": "下肢", "items": [
        {"exercise": "杠铃深蹲", "sets": 2, "reps": "6–8"}], "minutes": 30}).json()  # fmt: skip
    assert w["workout"]["items"][0]["sets"] == 2 and w["workout"]["minutes"] == 30


# ---- 需求 4：每组的重量和次数、下次目标 ---------------------------------------------------------

from ironm_agent.progression import last_target, rep_range, target_lines, targets  # noqa: E402
from ironm_agent.training import LogItem, PlanItem, SetDone, WorkoutLog  # noqa: E402


def did(exercise: str, reps: list[int], weight: float | None, back: int) -> WorkoutLog:
    sets = [SetDone(reps=r, weight_kg=weight) for r in reps]
    return WorkoutLog(
        day=TODAY - timedelta(days=back), items=[LogItem(exercise=exercise, done_sets=sets)]
    )


SQUAT = PlanItem(exercise="杠铃深蹲", sets=3, reps="6–8")


def test_performed_from_sets_or_text() -> None:
    assert [x.reps for x in LogItem(exercise="x", sets=3, reps="8").performed()] == [8, 8, 8]
    assert LogItem(exercise="x", done_sets=[SetDone(reps=8)] * 2).sets == 2
    assert [x.reps for x in LogItem(exercise="x", sets=3, reps="8、8、7").performed()] == [8, 8, 7]
    assert LogItem(exercise="x", sets=3, reps="8–12").performed() == []  # 范围是计划，不是实际
    assert LogItem(exercise="x", sets=3, reps="30 秒").performed() == []
    assert (
        rep_range("8–12") == (8, 12) and rep_range("10") == (10, 10) and rep_range("30 秒") is None
    )


def test_without_the_coach_next_time_is_the_same_as_last_time() -> None:
    """§163 需求 6：不再按规则算进阶；管家没定时下次照上次实际做的重量和次数（组数照计划）。"""
    logs = [did("杠铃深蹲", [9, 9, 9], 60, 7), did("杠铃深蹲", [9, 10, 9], 60, 3)]
    t = last_target(SQUAT, logs)  # 连续两次都超过上限：以前规则会加重，现在照上次
    assert t is not None and t.by == "last" and t.action == "hold" and t.weight_kg == 60
    assert t.text() == "60 公斤 × 9–10 次 × 3 组" and t.why.startswith("照上次")
    down = last_target(
        SQUAT, [did("杠铃深蹲", [6, 5, 5], 70, 7), did("杠铃深蹲", [7, 6, 5], 70, 2)]
    )
    assert down is not None and down.weight_kg == 70 and down.reps == "5–7"  # 没做到也不按规则减重
    push = PlanItem(exercise="俯卧撑", sets=3, reps="10")
    logs2 = [
        WorkoutLog(
            day=TODAY - timedelta(days=2), items=[LogItem(exercise="俯卧撑", sets=3, reps="12")]
        )
    ]
    t2 = last_target(push, logs2)
    assert t2 is not None and t2.weight_kg is None and t2.reps == "12"
    assert last_target(SQUAT, []) is None  # 没做过：没有下次目标
    assert last_target(PlanItem(exercise="平板支撑", sets=3, reps="30 秒"), logs) is None


def test_targets_reach_case_file_and_api(monkeypatch: pytest.MonkeyPatch) -> None:
    from mirobody.server.auth import verify_token

    from ironm_agent import web

    real = date.today()
    session = Session.model_validate(
        {"day": real.isoweekday(), "name": "下肢", "items": [SQUAT.model_dump()]}
    )
    plan = Plan.model_validate(
        {"title": "x", "days_per_week": 1, "sessions": [session.model_dump()]}
    )
    logs = [did("杠铃深蹲", [9, 9, 9], 60, 7), did("杠铃深蹲", [9, 9, 9], 60, 3)]
    logs = [x.model_copy(update={"day": real - (TODAY - x.day)}) for x in logs]
    assert set(targets(plan, logs)) == {"杠铃深蹲"}
    lines = target_lines(plan, logs, real)
    assert lines and "杠铃深蹲 下次 60 公斤 × 9 次 × 3 组（照上次：" in lines[0]  # 管家没定：照上次
    assert "规则" not in lines[0]
    book = TrainingBook()
    d = asyncio.run(book.add_draft("42", "plan", plan_content(plan)))
    asyncio.run(book.confirm("42", d.id))
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web.training_store] = lambda: book
    app.dependency_overrides[web.memory_store] = MemoryBook
    monkeypatch.setattr(web, "refresh_later", lambda *a: None)
    c = TestClient(app)
    sets = [{"reps": 9, "weight_kg": 60}] * 3
    body = {"session": "下肢", "items": [{"exercise": "杠铃深蹲", "sets": 3, "done_sets": sets}]}
    for _ in range(2):  # 打卡时填每组的重量和次数
        w = c.post("/iron/api/workouts", json=body).json()["workout"]
        one = w["items"][0]["done_sets"][0]
        assert (one["reps"], one["weight_kg"]) == (9, 60) and "60×9" in w["line"]
    r = c.get("/iron/api/training").json()
    t = r["targets"]["杠铃深蹲"]  # 管家没定：照上次，不按规则加重
    assert t["by"] == "last" and t["action"] == "hold" and t["weight_kg"] == 60 and t["reps"] == "9"


def test_chat_log_keeps_only_said_set_numbers() -> None:
    from ironm_agent.training import trusted_log

    log = WorkoutLog(day=TODAY, items=[LogItem(exercise="杠铃深蹲", done_sets=[
        SetDone(reps=8, weight_kg=60), SetDone(reps=7, weight_kg=60)])])  # fmt: skip
    kept = trusted_log(log, "深蹲 60 公斤做了 8 次和 7 次", None)
    assert len(kept.items[0].done_sets) == 2
    made_up = trusted_log(log, "深蹲做了 8 次和 7 次", None)  # 没说重量：整组不记，不编
    assert made_up.items[0].done_sets == []


# ---- 需求 5：触发型调整 -----------------------------------------------------------------------

from ironm_agent import triggers as trig  # noqa: E402

THREE = Plan.model_validate(
    {"title": "x", "days_per_week": 3, "sessions": [
        {"day": 1, "name": "下肢", "items": [{"exercise": "杠铃深蹲", "sets": 3, "reps": "6–8"}]},
        {"day": 3, "name": "上肢", "items": [{"exercise": "卧推", "sets": 3, "reps": "6–8"}]},
        {"day": 5, "name": "全身", "items": [{"exercise": "俯卧撑", "sets": 3, "reps": "10"}]}]}
)  # fmt: skip


def test_pain_parts_and_pain_trigger() -> None:
    assert trig.pain_parts("我膝盖又疼了") == ["joint.knee"]
    assert trig.pain_parts("深蹲会影响膝盖吗") == [] and trig.pain_parts("我妈膝盖疼") == []
    same_day = [("joint.knee", TODAY), ("joint.knee", TODAY)]
    assert trig.pain_triggers(same_day, THREE, TODAY) == []  # 同一天说两次算一次
    two = [("joint.knee", TODAY - timedelta(days=10)), ("joint.knee", TODAY - timedelta(days=1))]
    [t] = trig.pain_triggers(two, THREE, TODAY)
    assert (
        t.kind == "pain" and t.action == "proposal" and "杠铃深蹲" in t.tip and "医生" in t.detail
    )
    old = [("joint.knee", TODAY - timedelta(days=20)), ("joint.knee", TODAY - timedelta(days=1))]
    assert trig.pain_triggers(old, THREE, TODAY) == []  # 超过 14 天的不算
    [w] = trig.pain_triggers(
        [("joint.wrist", TODAY), ("joint.wrist", TODAY - timedelta(days=3))], None, TODAY
    )
    assert w.action == "info"  # 没有计划：只提醒


def test_missed_and_gap() -> None:
    sat = date(2026, 10, 24)  # 固定在周六，结果不随运行日期变

    def done(back: int) -> WorkoutLog:
        return WorkoutLog(day=sat - timedelta(days=back), session="下肢")

    # sat 是周六；上次练是 9 天前（周四），之后的周五、周一、周三、周五都没练
    m = trig.missed_trigger(THREE, [done(9)], sat - timedelta(days=60), sat)
    assert m is not None and "连着 4 次" in m.detail and m.action == "proposal"
    assert trig.missed_trigger(THREE, [done(2)], None, sat) is None  # 上次练后只空了 1 次
    assert trig.missed_trigger(THREE, [done(9), done(0)], None, sat) is None  # 今天练了
    assert trig.gap_scale([done(9)], sat) == (0.7, "上次训练是 9 天前，先按原量的约 7 成恢复")
    assert trig.gap_scale([done(20)], sat) is not None and trig.gap_scale([done(20)], sat)[0] == 0.5  # type: ignore[index]
    assert trig.gap_scale([done(3)], sat) is None and trig.gap_scale([], sat) is None
    v = today_mod.build(leg_day(), scale=0.7, scale_why="上次训练是 9 天前")
    assert [x.sets for x in v.session.items] == [3, 2, 2, 2, 1] and "约 7 成" in v.changes[0]


def test_plateau() -> None:
    def squat(back: int, w: float, reps: int = 5) -> WorkoutLog:
        return did("杠铃深蹲", [reps] * 3, w, back)

    flat = [squat(40, 100), squat(30, 100), squat(14, 100), squat(5, 97.5)]
    [t] = trig.plateau_triggers(THREE, flat, TODAY)
    assert t.kind == "plateau" and "杠铃深蹲" in t.detail
    rising = [squat(40, 100), squat(30, 100), squat(14, 102.5), squat(5, 105)]
    assert trig.plateau_triggers(THREE, rising, TODAY) == []
    assert (
        trig.plateau_triggers(THREE, [squat(14, 100), squat(5, 100)], TODAY) == []
    )  # 没有更早的记录


def test_trigger_endpoints_and_pain_records(monkeypatch: pytest.MonkeyPatch) -> None:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more

    real = date.today()
    pain = trig.PainBook()
    book = TrainingBook()
    d = asyncio.run(book.add_draft("42", "plan", plan_content(THREE)))
    asyncio.run(book.confirm("42", d.id))
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web_more.training_store] = lambda: book
    app.dependency_overrides[web.training_store] = lambda: book
    app.dependency_overrides[web.memory_store] = MemoryBook
    app.dependency_overrides[web_more.memory_store] = MemoryBook
    app.dependency_overrides[web_more.pain_store] = lambda: pain
    monkeypatch.setattr(web, "refresh_later", lambda *a: None)
    c = TestClient(app)
    read: list[tuple[str, str]] = []
    monkeypatch.setattr(
        web_more, "body_later", lambda uid, text, day, where: read.append((text, where))
    )
    c.post("/iron/api/workouts", json={"session": "下肢", "note": "膝盖有点疼"})
    assert read == [("膝盖有点疼", "打卡备注")] and not pain.rows.get(
        "42"
    )  # 备注由管家读，不按关键词记（§163）
    pain.rows["42"] = [
        ("joint.knee", real),
        ("joint.knee", real - timedelta(days=4)),
    ]  # 管家读出来记下的
    assert (
        c.get("/iron/api/triggers").json()["triggers"] == []
    )  # 规则的"反复疼"提醒去掉了，交给管家复盘（§163）


def test_chat_pain_is_recorded(monkeypatch: pytest.MonkeyPatch) -> None:
    from tests.test_turn_flow import Coach, agent

    a = agent(Coach(said={"pain": ["左膝"]}), monkeypatch=monkeypatch, memory=MemoryBook())
    a._pain = book = trig.PainBook()  # 管家判断他说了左膝疼（§114），按它记

    async def go() -> None:
        msgs = [{"role": "user", "content": "我左膝最近又疼了，深蹲要注意什么"}]
        [b async for b in a.generate_response("42", msgs, session_id="42:s1")]
        await a.settle()

    asyncio.run(go())
    assert book.rows["42"] == [("joint.knee", date.today())]


# ---- 需求 6：目标进度与阶段复测 -----------------------------------------------------------------

from ironm_agent.goal import Goal, GoalBook, progress, retest  # noqa: E402
from ironm_agent.metrics import weight_trend  # noqa: E402


def weights(per_week: float, start: float = 80.0, days: int = 28) -> tuple[tuple[date, float], ...]:
    return tuple(
        (TODAY - timedelta(days=i), round(start + per_week / 7 * (days - 1 - i), 2))
        for i in range(days)
    )


def test_goal_progress_predicts_date() -> None:
    w = weights(-0.5)  # 每周掉 0.5 公斤，现在 78.07
    g = Goal(75, TODAY + timedelta(days=60), TODAY - timedelta(days=27), start=80)
    p = progress(g, w, weight_trend(w, TODAY), TODAY)
    assert p["start"] == 80 and p["current"] == w[0][1] and p["target"] == 75
    pred = date.fromisoformat(p["predicted"])
    assert abs((pred - TODAY).days - round((w[0][1] - 75) / 0.5 * 7)) <= 1
    assert p["status"] == "on_track" and "预计" in p["message"]
    late = progress(replace(g, by=TODAY + timedelta(days=14)), w, weight_trend(w, TODAY), TODAY)
    assert late["status"] == "behind" and "晚约" in late["message"] and "1%" in late["pace"]
    early = progress(replace(g, by=TODAY + timedelta(days=200)), w, weight_trend(w, TODAY), TODAY)
    assert early["status"] == "ahead" and "由你决定" in early["message"]
    wrong = progress(g, weights(0.5), weight_trend(weights(0.5), TODAY), TODAY)
    assert wrong["status"] == "wrong_way" and wrong["predicted"] is None
    done = progress(replace(g, value=79), w, weight_trend(w, TODAY), TODAY)
    assert done["status"] == "reached"


def test_goal_progress_says_what_is_missing() -> None:
    few = weights(-0.5, days=5)
    g = Goal(75, TODAY + timedelta(days=60), TODAY - timedelta(days=4))
    p = progress(g, few, weight_trend(few, TODAY), TODAY)
    assert p["predicted"] is None and "不够两周" in p["missing"] and "还缺" in p["missing"]
    assert p["start"] == few[-1][1]  # 设目标时没有起点：用设目标之后的第一次
    none = progress(g, (), weight_trend((), TODAY), TODAY)
    assert none["current"] is None and "称一次体重" in none["missing"]


def test_retest_reminder() -> None:
    g = Goal(75, TODAY + timedelta(days=90), TODAY - timedelta(days=27))
    assert not retest(g, TODAY)["due"]
    r = retest(g, TODAY + timedelta(days=1))
    assert r["due"] and "体重、腰围和关键动作" in r["text"] and "超过 6 周" not in r["text"]
    assert "超过 6 周" in retest(g, TODAY + timedelta(days=15))["text"]
    assert not retest(replace(g, retest_day=TODAY), TODAY + timedelta(days=1))["due"]


def test_goal_endpoints(monkeypatch: pytest.MonkeyPatch) -> None:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more

    real = date.today()
    goals = GoalBook()
    w = tuple((real - (TODAY - d), v) for d, v in weights(-0.5))

    async def snap(user_id: str, today: date | None = None) -> Snapshot:
        p = Profile(height_cm=175, sex="male", goal="fat_loss", activity="moderate")
        r = Readings(weight=w)
        return Snapshot(p, r, tuple(compute_all(r, p, real)), real)

    monkeypatch.setattr(web, "snapshot_for", snap)
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web_more.goal_store] = lambda: goals
    c = TestClient(app)
    assert c.get("/iron/api/goal").json() == {"goal": None, "progress": None}
    by = (real + timedelta(days=60)).isoformat()
    r = c.put("/iron/api/goal", json={"value": 75, "by": by}).json()
    assert r["goal"]["start"] == w[0][1] and r["progress"]["predicted"]
    assert c.put("/iron/api/goal", json={"value": 75, "by": real.isoformat()}).status_code == 422
    assert c.put("/iron/api/goal", json={"value": 10, "by": by}).status_code == 422
    goals.rows["42"] = replace(goals.rows["42"], set_day=real - timedelta(days=30))
    assert c.get("/iron/api/goal").json()["progress"]["retest"]["due"]
    assert not c.post("/iron/api/goal/retest").json()["progress"]["retest"]["due"]
    assert c.delete("/iron/api/goal").json()["goal"] is None
    assert c.post("/iron/api/goal/retest").status_code == 404


def test_today_tired_and_gap_do_not_stack() -> None:
    v = today_mod.build(
        leg_day(), tired=True, tired_why="没睡好", scale=0.7, scale_why="上次训练是 9 天前"
    )
    assert [x.sets for x in v.session.items] == [2, 1, 1, 1, 1]  # 只减半，不再乘七成
    assert "已包含中断后的降量" in v.changes[0] and v.reasons == ("没睡好", "上次训练是 9 天前")
