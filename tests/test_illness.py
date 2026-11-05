"""生病和身体不适（spec [2026-10-23] §46）：认症状和分级、每天追问、当天怎么练、生病的日子不算缺勤、记忆。"""

import asyncio
from datetime import date, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.actions import RECORD_STATE
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
from tests.fakes import call, jsonr
from tests.test_turn_flow import Coach, agent, book, run, snapshot_of

TODAY = date.today()
YESTERDAY = TODAY - timedelta(days=1)


def ep(level: str = "below", started: date = YESTERDAY, **kw: Any) -> Episode:
    return Episode(symptoms=kw.pop("symptoms", ["肚子疼"]), level=level, started=started, **kw)  # type: ignore[arg-type]


def test_symptoms_and_levels() -> None:
    assert detect("我肚子疼") == (["肚子疼"], "below")
    assert detect("发烧了，38 度") == (["发烧"], "fever")
    assert detect("嗓子有点疼") == (["嗓子疼"], "above")
    assert detect("感冒了，流鼻涕") == (["流鼻涕"], "above")  # 有具体症状时按症状分级
    assert detect("我生病了") == (["身体不适"], "vague")  # 没说症状：没说哪里，按轻松版（§82）
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


def _agent(
    team: Coach, monkeypatch: Any, ill: IllnessBook, memory: MemoryBook | None = None
) -> Any:
    a = agent(team, monkeypatch=monkeypatch, memory=memory, snapshot=snapshot_of())
    a._illness = ill
    return a


def test_saying_sick_in_chat_starts_an_episode(monkeypatch: Any) -> None:
    ill = IllnessBook()
    run(
        _agent(Coach(said={"sick": "肚子疼", "sick_level": "颈部以下"}), monkeypatch, ill),
        "我今天肚子疼，还能练吗",
    )
    eps = list(ill.rows["42"].values())
    assert eps[0].symptoms == ["肚子疼"] and eps[0].level == "below" and eps[0].started == TODAY
    vague = IllnessBook()  # 轻重由管家交；没交就是说不清，代码不按词表猜（§163）
    run(_agent(Coach(said={"sick": "发烧 38 度"}), monkeypatch, vague), "我发烧了")
    assert [e.level for e in vague.rows["42"].values()] == ["vague"]


def test_model_judgment_first_keywords_only_as_fallback(monkeypatch: Any) -> None:
    """§114：管家作答了就按它的判断——没写 said 就是没说，"我的生病记录""如果发烧了能练吗"不开记录；
    管家这一轮失败了也不按关键词兜底（§163 规则不要）。"""
    ill = IllnessBook()
    for asked in ("如果发烧了能练吗", "生病期间吃什么"):
        run(_agent(Coach(), monkeypatch, ill), asked)
    assert "42" not in ill.rows or not ill.rows["42"]
    down = IllnessBook()
    run(_agent(Coach(down=True), monkeypatch, down), "我今天发烧了")
    assert not down.rows.get("42")  # 管家失败：不写，不再按关键词猜


def test_chat_asks_once_a_day_and_text_replies_count(monkeypatch: Any) -> None:
    ill = IllnessBook()
    asyncio.run(ill.save("42", ep()))
    t = Coach()
    a = _agent(t, monkeypatch, ill)
    _, seen = run(a, "深蹲怎么做")
    # 追问交给管家在回答末尾自然地问一句（§86），不再拼在末尾
    assert seen.get("illness_asked") and "今天还没问过他：昨天说肚子疼，今天好些了吗？" in t.input
    _, seen = run(a, "卧推怎么做")
    assert "好些了吗" not in t.input and not seen.get("illness_asked")  # 每天只问一次
    t.extra = {"said": {"better": "好些"}}  # 管家判断他在回答好些了（§114）
    run(a, "好多了")
    e = next(iter(ill.rows["42"].values()))
    assert e.status == "better"


STALE = (
    ("event", "今天肚子疼，腿训和骑车有氧都停了"),
    ("advice", "肚子疼先别练，今天停腿训和骑车"),
)


def test_stale_illness_memory_is_not_given_to_the_agent(monkeypatch: Any) -> None:
    t = Coach()
    run(_agent(t, monkeypatch, IllnessBook(), book(*STALE)), "深蹲怎么做")
    assert "肚子疼" not in t.input  # 没有正在进行的生病：旧的事件和建议都不带


def test_ongoing_illness_is_given_in_relative_words(monkeypatch: Any) -> None:
    ill = IllnessBook()
    asyncio.run(ill.save("42", ep()))
    t = Coach()
    run(_agent(t, monkeypatch, ill, book(*STALE)), "深蹲怎么做")
    assert "说肚子疼" in t.input and "还没好" not in t.input  # §82：相对说法


def test_two_day_story_sick_then_better(monkeypatch: Any) -> None:
    """第一天说肚子疼，第二天说好了再问今天练什么：回答前的档案里不再当成还在疼。"""
    ill = IllnessBook()
    asyncio.run(ill.save("42", ep()))  # 昨天记下的
    t = Coach(said={"better": "好了"})  # 管家判断他说好了（§114）：作答后写
    a = _agent(t, monkeypatch, ill)
    run(a, "肚子已经不疼了，深蹲怎么做")
    assert "他这一句刚说的更新，冲突时按他这一句" in t.input  # 这一轮档案还没改：以他刚说的为准
    t.extra = {}
    run(a, "深蹲怎么做")  # 下一轮：档案里已经是好了
    assert "还没好" not in t.input
    assert "病后第一次训练按平时的七成" in t.input  # 刚好：告诉角色按约七成练


def test_case_file_dates_events() -> None:
    from ironm_agent.casefile import build
    from ironm_agent.memory_view import Recall

    memory = book(("event", "这周出差"))
    items = asyncio.run(memory.items("42"))
    at = items[0].created + timedelta(days=1)  # 说了之后第二天（不随真实日期过期）
    case = build(Snapshot(Profile(), Readings(), (), TODAY), Recall.of(items, at), "今天练什么")
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


def test_training_during_illness_no_longer_ends_it(monkeypatch: Any) -> None:
    """§163：练了一次不等于病好了，好没好由他说（管家记）或首页按钮。"""
    ill = IllnessBook()
    e = ep()
    asyncio.run(ill.save("42", e))
    c = client(monkeypatch, ill)
    from ironm_agent import web

    monkeypatch.setattr(web, "refresh_later", lambda *a: None)
    assert c.post("/iron/api/workouts", json={"session": "全身"}).status_code == 200
    still = ill.rows["42"][e.id]
    assert still.status == "open" and still.ended is None


def test_asking_about_it_is_not_being_sick() -> None:
    """问到病情、转述以前说的不算又病了；"不疼啊"算好了（spec [2026-10-23] §50）。"""
    from ironm_agent.illness import detect, reply_of

    for text in ("我肚子疼不疼", "我多久说了肚子疼", "是不是发烧了", "肚子疼吗", "上次说的头疼"):
        assert detect(text) is None, text
    for text in ("肚子疼，今天能练吗", "肚子疼能练吗", "我肚子疼"):
        assert detect(text) == (["肚子疼"], "below"), text
    assert reply_of("今天肚子不疼啊") == "resolved"
    assert reply_of("不疼了") == "resolved"
    assert reply_of("我肚子疼不疼") is None
    assert reply_of("还不舒服") == "unwell"


# ---- §82：只说不舒服时先接住请求 ----


def test_vague_unwell_is_light_not_rest_and_upgrades_when_symptoms_come() -> None:
    from ironm_agent.illness import merge

    assert detect("今天有点不舒服，给我安排一个轻松的锻炼") == (["身体不适"], "vague")
    mode = today_mode([ep("vague", started=TODAY)], TODAY)
    assert mode is not None and mode[0] == "light" and "问哪里不舒服" in mode[1]
    assert "不主动安排" in mode[1]  # 他没问练什么就不给（§82 修改）
    assert "月" not in mode[1] and "还没好" not in mode[1]  # 不给日期、不给"还没好"
    vague = ep("vague", started=TODAY, symptoms=["身体不适"])
    fever = merge([vague], ["发烧"], "fever", TODAY)
    assert fever.level == "fever" and fever.symptoms == ["发烧"]
    assert today_mode([fever], TODAY)[0] == "rest"  # type: ignore[index]
    assert detect("我拉肚子了")[1] == "below"  # type: ignore[index]  # 说了具体症状照旧


def test_vague_unwell_reaches_the_model_as_a_light_day_without_dates(monkeypatch: Any) -> None:
    from tests.test_single_agent import single

    def answer(system: str, user: str, results: list[str]) -> Any:
        if "今天有点不舒服" in user.split("\n", 1)[0] and not results:  # 记今天的状态（§122）
            return call(RECORD_STATE, sick="不舒服")
        return jsonr({"answer": "可以，今天慢走 20 分钟。"})

    a, s = single(answer, monkeypatch, old=True)
    a._illness = IllnessBook()
    run(a, "今天有点不舒服，给我安排一个轻松的锻炼")
    run(a, "给我安排一个轻松的锻炼")
    assert "没说哪里" in s.user and "还没好" not in s.user
    assert "不报日期" in s.system  # 提起记忆和状态像人说话（§82）


def test_sick_skill_takes_the_request_first_when_unwell_is_vague() -> None:
    from ironm_agent.skills import skills

    body = next(
        x for x in skills() if x.id == "readiness-adjust"
    ).body  # 生病期间并进今天练不练（§101）
    assert '只说"有点不舒服、难受"、没说哪里' in body and "再问一句哪里不舒服" in body
    assert "没问怎么办：关心一句，问哪里不舒服，不主动给做法和安排" in body
