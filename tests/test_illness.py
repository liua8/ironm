"""生病和身体不适（spec [2026-10-23] §46）：认症状和分级、每天追问、当天怎么练、生病的日子不算缺勤、记忆。"""

import asyncio
from datetime import date, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.brief import weekly_review
from ironm_agent.casefile import Snapshot
from ironm_agent.illness import (
    Check,
    Episode,
    IllnessBook,
    active,
    answer,
    detect,
    doctor,
    due,
    question,
    recovering_days,
    recurring,
    reply_of,
    sick_days,
    today_mode,
)
from ironm_agent.memory_store import MemoryBook
from ironm_agent.metrics import Profile, Readings
from ironm_agent.training import Plan, TrainingBook, WorkoutLog, plan_content, week_of
from ironm_agent.triggers import missed_trigger, plateau_triggers
from tests.test_plugin import text_of
from tests.test_turn_flow import Team, agent, book, run, snapshot_of

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


def ep(level: str = "below", started: date = YESTERDAY, **kw: Any) -> Episode:
    return Episode(symptoms=kw.pop("symptoms", ["肚子疼"]), level=level, started=started, **kw)  # type: ignore[arg-type]


def test_symptoms_and_levels() -> None:
    assert detect("我肚子疼") == (["肚子疼"], "below")
    assert detect("发烧了，38 度") == (["发烧"], "fever")
    assert detect("嗓子有点疼") == (["嗓子疼"], "above")
    assert detect("感冒了，流鼻涕") == (["流鼻涕"], "above")  # 有具体症状时按症状分级
    assert detect("我生病了") == (["身体不适"], "below")  # 没说症状：按颈部以下（保守）
    for text in ("我没发烧", "膝盖旧伤又不舒服", "没睡好", "我妈感冒了", "肚子已经不疼了"):
        assert detect(text) is None, text
    assert reply_of("好多了，就是还在拉") == "unwell" and reply_of("不疼了") == "resolved"
    assert reply_of("好一些了") == "better" and reply_of("肚子好多了，就是还有点拉") == "unwell"


def test_today_mode_follows_the_neck_rule() -> None:
    assert today_mode([ep("below")], TODAY)[0] == "rest"  # type: ignore[index]
    assert today_mode([ep("fever")], TODAY)[0] == "rest"  # type: ignore[index]
    assert today_mode([ep("above", symptoms=["流鼻涕"])], TODAY)[0] == "light"  # type: ignore[index]
    better = ep("below", status="better")
    assert today_mode([better], TODAY)[0] == "light"  # type: ignore[index]
    fever_done = ep("fever", status="resolved", ended=TODAY)
    assert today_mode([fever_done], TODAY)[0] == "rest"  # 退烧当天仍休息  # type: ignore[index]
    done = ep("below", status="resolved", ended=YESTERDAY)
    assert today_mode([done], TODAY) == ("ease", "肚子疼刚好，病后第一次训练按平时的七成")
    assert today_mode([done], TODAY, trained_since=[TODAY]) is None  # 已经练过一次：恢复原计划


def test_daily_follow_up_until_answered_or_silent() -> None:
    e = ep()
    assert due(e, TODAY) and question(e, TODAY) == "昨天说肚子疼，今天好些了吗？"
    assert not due(ep(started=TODAY), TODAY)  # 当天不问，从第二天起
    e2, say = answer(e, "unwell", TODAY)
    assert e2.status == "open" and not due(e2, TODAY) and "休息" in say
    e3, _ = answer(e, "better", TODAY)
    assert e3.status == "better" and today_mode([e3], TODAY)[0] == "light"  # type: ignore[index]
    e4, _ = answer(e, "resolved", TODAY)
    assert e4.status == "resolved" and not active([e4], TODAY)
    silent = ep(started=TODAY - timedelta(days=4))
    assert not active([silent], TODAY) and not due(silent, TODAY)  # 连续 3 天没回答：不再问


def test_doctor_after_three_bad_days_or_long_fever() -> None:
    checks = [Check(day=TODAY - timedelta(days=i), answer="unwell") for i in (2, 1, 0)]
    assert "看医生" in doctor(ep(started=TODAY - timedelta(days=3), checks=checks), TODAY)
    fever = ep("fever", started=TODAY - timedelta(days=3), checks=checks[-1:])
    assert "看医生" in doctor(fever, TODAY)
    assert doctor(ep(), TODAY) == ""


def test_resolved_but_heart_rate_not_back_means_light_today() -> None:
    e, say = answer(ep(), "resolved", TODAY, hr_poor=True)
    assert "心率还没回到平时的水平" in say and today_mode([e], TODAY)[0] == "light"  # type: ignore[index]


PLAN = Plan.model_validate(
    {"title": "三练", "days_per_week": 3, "sessions": [
        {"day": d, "name": n, "items": [{"exercise": "高脚杯深蹲", "sets": 3, "reps": "10"}]}
        for d, n in ((1, "下肢"), (3, "上肢"), (5, "全身"))]}
)  # fmt: skip


def test_sick_days_do_not_count_as_missed() -> None:
    start = TODAY - timedelta(days=27)
    e = ep(started=start, status="resolved", ended=TODAY)
    days = sick_days([e], TODAY)
    assert start in days and TODAY in days
    assert week_of(PLAN, [], TODAY, sick=days).due == 0
    assert missed_trigger(PLAN, [], None, TODAY) is not None
    assert missed_trigger(PLAN, [], None, TODAY, days) is None
    assert (TODAY + timedelta(days=2)) in recovering_days([e], TODAY)  # 好了之后两天也不触发减重量

    def log(d: date, kg: float) -> WorkoutLog:
        return WorkoutLog.model_validate(
            {
                "day": d,
                "items": [{"exercise": "高脚杯深蹲", "done_sets": [{"reps": 8, "weight_kg": kg}]}],
            }
        )

    logs = [
        log(TODAY - timedelta(days=40), 30),
        log(TODAY - timedelta(days=10), 25),
        log(TODAY - timedelta(days=3), 25),
    ]
    assert plateau_triggers(PLAN, logs, TODAY) and not plateau_triggers(PLAN, logs, TODAY, days)


def test_getting_sick_twice_in_four_weeks_suggests_lighter_week() -> None:
    eps = [ep(started=TODAY - timedelta(days=20), status="resolved", ended=TODAY - timedelta(days=18)),
           ep(started=YESTERDAY)]  # fmt: skip
    assert recurring(eps, TODAY) == 2
    snap = Snapshot(Profile(goal="muscle"), Readings(), (), TODAY)
    out = weekly_review(snap, PLAN, [], sick_times=2)
    assert (
        any("最近 4 周病了 2 次" in t for t in out["tips"])
        and {"kind": "lighter", "why": "最近 4 周病了 2 次"} in out["actions"]
    )


# ---- 对话 -----------------------------------------------------------------------------------


def _agent(team: Team, monkeypatch: Any, ill: IllnessBook, memory: MemoryBook | None = None) -> Any:
    a = agent(team, monkeypatch=monkeypatch, memory=memory, snapshot=snapshot_of())
    a._illness = ill
    return a


def test_saying_sick_in_chat_starts_an_episode(monkeypatch: Any) -> None:
    ill = IllnessBook()
    _, seen = run(_agent(Team("recovery"), monkeypatch, ill), "我今天肚子疼，还能练吗")
    eps = list(ill.rows["42"].values())
    assert (
        seen["illness"] == "noted:below"
        and eps[0].symptoms == ["肚子疼"]
        and eps[0].started == TODAY
    )


def test_chat_asks_once_a_day_and_text_replies_count(monkeypatch: Any) -> None:
    ill = IllnessBook()
    asyncio.run(ill.save("42", ep()))
    a = _agent(Team("trainer"), monkeypatch, ill)
    first, seen = run(a, "深蹲怎么做")
    assert seen.get("illness_asked") and text_of(first).rstrip().endswith(
        "昨天说肚子疼，今天好些了吗？"
    )
    again, _ = run(a, "卧推怎么做")
    assert "好些了吗" not in text_of(again)  # 每天只问一次
    _, seen = run(a, "好多了")
    e = next(iter(ill.rows["42"].values()))
    assert seen["illness"] == "answered:better" and e.status == "better"


def test_stale_illness_memory_is_not_given_to_the_experts(monkeypatch: Any) -> None:
    memory = book(
        ("event", "今天肚子疼，腿训和骑车有氧都停了"), ("advice", "肚子疼先别练，今天停腿训和骑车")
    )
    t = Team("trainer")
    run(_agent(t, monkeypatch, IllnessBook(), memory), "深蹲怎么做")
    assert "肚子疼" not in t.inputs["trainer"]  # 没有正在进行的生病：旧的事件和建议都不带
    ill = IllnessBook()
    asyncio.run(ill.save("42", ep()))
    t2 = Team("trainer")
    run(_agent(t2, monkeypatch, ill, memory), "深蹲怎么做")
    assert "开始肚子疼，现在还没好" in t2.inputs["trainer"]


def test_two_day_story_sick_then_better(monkeypatch: Any) -> None:
    """第一天说肚子疼，第二天说好了再问今天练什么：回答前的档案里不再当成还在疼。"""
    ill = IllnessBook()
    asyncio.run(ill.save("42", ep()))  # 昨天记下的
    t = Team("trainer")
    _, seen = run(_agent(t, monkeypatch, ill), "肚子已经不疼了，深蹲怎么做")
    assert seen["illness"] == "answered:resolved"
    assert "还没好" not in t.inputs["trainer"]
    assert "病后第一次训练按平时的七成" in t.inputs["trainer"]  # 刚好：告诉角色按约七成练


def test_case_file_dates_events() -> None:
    from ironm_agent.casefile import build
    from ironm_agent.memory_view import Recall

    memory = book(("event", "这周出差"))
    items = asyncio.run(memory.items("42"))
    case = build(Snapshot(Profile(), Readings(), (), TODAY), Recall.of(items), "今天练什么")
    assert any("这周出差（" in x and "日说的）" in x for x in case.limits)


# ---- 首页与接口 -----------------------------------------------------------------------------


def client(monkeypatch: Any, ill: IllnessBook) -> TestClient:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more

    async def snap(_: str, today: date | None = None) -> Snapshot:
        return Snapshot(Profile(goal="muscle"), Readings(), (), TODAY)

    store = TrainingBook()
    d = asyncio.run(store.add_draft("42", "plan", plan_content(Plan.model_validate(
        {"title": "每天", "days_per_week": 7, "sessions": [
            {"day": i, "name": "全身", "items": [{"exercise": "高脚杯深蹲", "sets": 3, "reps": "10"}]}
            for i in range(1, 8)]}))))  # fmt: skip
    asyncio.run(store.confirm("42", d.id))
    monkeypatch.setattr(web, "snapshot_for", snap)
    monkeypatch.setattr(web_more, "coach_later", lambda *a: None)
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    for mod in (web, web_more):
        app.dependency_overrides[mod.training_store] = lambda: store
    app.dependency_overrides[web.memory_store] = MemoryBook
    app.dependency_overrides[web_more.illness_store] = lambda: ill
    return TestClient(app)


def test_home_check_in_and_buttons(monkeypatch: Any) -> None:
    ill = IllnessBook()
    e = ep()
    asyncio.run(ill.save("42", e))
    c = client(monkeypatch, ill)
    checkin = c.get("/iron/api/brief").json()["checkin"]
    assert checkin["id"] == e.id and checkin["text"] == "昨天说肚子疼，今天好些了吗？"
    assert c.get("/iron/api/today").json()["status"] == "sick"
    assert c.get("/iron/api/week").json()["sick"]["mode"] == "rest"
    r = c.post(f"/iron/api/illness/{e.id}/check", json={"answer": "resolved"}).json()
    assert r["status"] == "resolved" and "七成" in r["message"]
    assert c.get("/iron/api/brief").json()["checkin"] is None  # 回答过了：不再问
    today = c.get("/iron/api/today").json()
    assert today["status"] == "ok" and any("七成" in x for x in today["reasons"])
    assert c.post("/iron/api/illness/nope/check", json={"answer": "resolved"}).status_code == 404


def test_never_answering_counts_the_rest_days_and_eases_back() -> None:
    """一直不回答：系统让休息的那几天都算生病的日子；之后第一次训练按七成（§46 补充）。"""
    start = TODAY - timedelta(days=5)
    e = ep(started=start)
    assert not active([e], TODAY)  # 第 5 天：不再问
    days = sick_days([e], TODAY)
    assert days == frozenset(start + timedelta(days=i) for i in range(4))  # 第 1 到第 4 天
    assert today_mode([e], TODAY) == ("ease", "肚子疼刚好，病后第一次训练按平时的七成")
    assert today_mode([e], TODAY, trained_since=[TODAY]) is None
    assert (start + timedelta(days=5)) in recovering_days([e], TODAY)  # 之后两天也不触发减重量


def test_training_during_illness_ends_it(monkeypatch: Any) -> None:
    ill = IllnessBook()
    e = ep()
    asyncio.run(ill.save("42", e))
    c = client(monkeypatch, ill)
    from ironm_agent import web

    monkeypatch.setattr(web, "refresh_later", lambda *a: None)
    assert c.post("/iron/api/workouts", json={"session": "全身"}).status_code == 200
    done = ill.rows["42"][e.id]
    assert done.status == "resolved" and done.ended == TODAY
    assert c.get("/iron/api/brief").json()["checkin"] is None
