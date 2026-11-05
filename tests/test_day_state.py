"""今日状态（spec [2026-10-23] §54 需求 1）：说到今天的状态先写进表，每轮从表里读，首页和对话用同一份。"""

import asyncio
from datetime import UTC, date, datetime
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent.casefile import Snapshot
from ironm_agent.day_state import DayBook, DayState, Entry, detect, lines, signals
from ironm_agent.illness import Episode, IllnessBook
from ironm_agent.memory_store import MemoryBook
from ironm_agent.metrics import Profile, Readings
from ironm_agent.training import Plan, TrainingBook, WorkoutLog, plan_content
from tests.test_turn_flow import TODAY, Coach, agent, run, snapshot_of

AT = datetime(2026, 10, 23, 5, 40, tzinfo=UTC)  # 13:40（东八区）


def kinds(text: str) -> list[tuple[str, Any]]:
    return [(e.kind, e.minutes or e.hours) for e in detect(text, AT)]


def test_rules_pick_up_todays_state() -> None:
    assert kinds("今天有点累") == [("tired", None)]
    assert kinds("今天只有30分钟") == [("minutes", 30)]
    assert kinds("就半小时，练什么") == [("minutes", 30)]
    assert kinds("我只有一个小时") == [("minutes", 60)]
    assert kinds("昨晚只睡了4个小时") == [("sleep", 4)]
    assert kinds("昨晚没睡好") == [("sleep", None)]
    assert kinds("今天状态不错") == [("good", None)]
    for text in ("我不累", "我妈很累", "深蹲怎么做", "睡了8个小时"):
        assert kinds(text) == [], text


def test_tired_until_said_good_and_signals_skip_this_turn() -> None:
    state = DayState(day=TODAY, entries=[Entry(kind="tired", at=AT)])
    assert state.tired() is not None and signals(state) == [("fair", "今天有点累（13:40 你说）")]
    assert signals(state, before=AT) == []  # 这一轮刚说的由这句话本身判断，不重复算
    later = state.model_copy(
        update={"entries": [*state.entries, Entry(kind="good", at=AT.replace(hour=7))]}
    )
    assert later.tired() is None


def test_today_block_has_time_or_source_on_every_line() -> None:
    class Stored:
        def __init__(self, log: WorkoutLog, at: datetime) -> None:
            self.log, self.created = log, at

    done = Stored(WorkoutLog(day=TODAY, session="骑车有氧", rpe=10), AT.replace(hour=6, minute=5))
    state = DayState(day=TODAY, entries=[Entry(kind="minutes", at=AT, minutes=30)])
    out = lines(state, today=TODAY, plan_name="骑车有氧", checkins=[done],
                illness="生病：肚子疼 10 月 23 日已经好了", pains=[("左膝", TODAY)])  # fmt: skip
    assert out[0] == "按计划：骑车有氧"
    assert "已打卡：骑车有氧（14:05，感受 10 分）" in out
    assert "今天只有 30 分钟（13:40 你说）" in out and "还没打卡" not in out
    assert out[-1] == "最近说疼的部位：左膝（10-23）"


def test_said_state_is_kept_for_the_next_turn(monkeypatch: Any) -> None:
    t = Coach(said={"tired": True})  # 管家判断他说了累（§114）
    a = agent(t, monkeypatch=monkeypatch, memory=MemoryBook(), snapshot=snapshot_of())
    book = DayBook()
    a._day = book
    run(a, "今天有点累，深蹲怎么做")
    assert len(book.rows[("42", date.today())].entries) == 1
    t2 = Coach()
    a2 = agent(t2, monkeypatch=monkeypatch, memory=MemoryBook(), snapshot=snapshot_of())
    a2._day = book
    run(a2, "深蹲还能加重吗")  # 没再说累
    shared = t2.input
    assert "今天的状态以这里为准" in shared and "今天有点累（" in shared
    assert "今天的身体状态：一般" in shared


def test_home_and_chat_use_the_same_state(monkeypatch: Any) -> None:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more

    today = date.today()

    async def snap(_: str, day: date | None = None) -> Snapshot:
        return Snapshot(Profile(goal="muscle"), Readings(), (), today)

    store = TrainingBook()
    plan = Plan.model_validate({"title": "每天", "days_per_week": 7, "sessions": [
        {"day": i, "name": "全身", "items": [{"exercise": "高脚杯深蹲", "sets": 4, "reps": "10"},
                                            {"exercise": "臀桥", "sets": 4, "reps": "12"}]}
        for i in range(1, 8)]})  # fmt: skip
    d = asyncio.run(store.add_draft("42", "plan", plan_content(plan)))
    asyncio.run(store.confirm("42", d.id))
    book = DayBook()
    monkeypatch.setattr(web, "snapshot_for", snap)

    async def no_weather(_: str) -> None:
        return None

    monkeypatch.setattr(web_more.weather, "for_user", no_weather)
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    app.dependency_overrides[web_more.training_store] = lambda: store
    app.dependency_overrides[web_more.illness_store] = IllnessBook
    app.dependency_overrides[web_more.day_store] = lambda: book
    c = TestClient(app)
    from ironm_agent import review as review_mod
    from ironm_agent.coach_state import Review

    async def reviewed(_: str) -> Any:
        return Review(day=today, summary="照计划练")

    monkeypatch.setattr(web_more, "review_today", reviewed)
    rerun: list[str] = []
    monkeypatch.setattr(review_mod, "rerun_later", lambda uid, deps, reason: rerun.append(reason))
    assert c.get("/iron/api/today").json()["changed"] is False
    asyncio.run(book.add("42", today, detect("今天只有30分钟，还有点累", datetime.now(UTC))))
    r = c.get(
        "/iron/api/today"
    ).json()  # 对话里说的累和 30 分钟：代码不再自己删减，由管家重看（§163）
    assert r["status"] == "ok" and not r["changed"] and r["today"]["items"][0]["sets"] == 4
    assert (
        c.get("/iron/api/today?tired=true").json()["status"] == "reviewing"
    )  # 首页点的：写进同一份、叫醒管家
    assert book.rows[("42", today)].entries[-1].source == "home" and rerun == ["首页点了今天的状态"]


def test_illness_line_in_today_block() -> None:
    from ironm_agent.illness import summary_line

    ill = Episode(symptoms=["肚子疼"], level="below", started=TODAY)
    assert summary_line([ill], TODAY) == "生病：今天说肚子疼"  # 相对说法，不写日期和"还没好"（§82）
    done = ill.model_copy(update={"status": "resolved", "ended": TODAY})
    assert summary_line([done], TODAY) == "生病：肚子疼今天好了"
    assert summary_line([], TODAY) == ""
