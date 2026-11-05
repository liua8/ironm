"""打卡记状态、没练也能打卡、训练轨迹（spec [2026-10-23] §105）。不连数据库、不调用真实模型。"""

from __future__ import annotations

import asyncio
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from ironm_agent.day_state import lines
from ironm_agent.muscle_feel import SORE_MUSCLES
from ironm_agent.training import SORE_PARTS, LogItem, SetDone, WorkoutLog
from ironm_agent.web_more import checkin_streak
from tests.test_frontend_api import client as _client
from tests.test_live import PLAN
from tests.test_live import client as live_client


def client() -> Any:
    """日历那套接口的测试客户端，再把打卡接口用的训练记录、记忆也换成内存版。"""
    from ironm_agent import web
    from ironm_agent.memory_store import MemoryBook

    c, book, meals = _client()
    c.app.dependency_overrides[web.training_store] = lambda: book  # type: ignore[attr-defined]
    c.app.dependency_overrides[web.memory_store] = lambda: MemoryBook()  # type: ignore[attr-defined]
    return c, book, meals


JS = (Path(__file__).resolve().parents[1] / "ironm_agent" / "web" / "app.js").read_text()


def test_state_goes_into_the_record_and_the_line() -> None:
    log = WorkoutLog(
        day=date(2026, 10, 23), session="下肢", energy="poor", slept="ok", sore=["大腿前", "臀"]
    )
    assert log.state() == "精力差，昨晚睡得一般，大腿前、臀酸"
    assert log.state() in log.line()
    assert WorkoutLog(day=date(2026, 10, 23)).state() == ""
    with pytest.raises(ValidationError):
        WorkoutLog(day=date(2026, 10, 23), sore=["脚趾"])  # 只认固定的几个部位


def test_rest_record_is_not_a_workout() -> None:
    rest = WorkoutLog(day=date(2026, 10, 23), done=False, rest="travel", note="在路上")
    assert "没练（出差）" in rest.line()
    with pytest.raises(ValidationError):
        WorkoutLog(day=date(2026, 10, 23), done=True, rest="sick")  # 记了没练就不能算练了
    with pytest.raises(ValidationError):
        WorkoutLog(
            day=date(2026, 10, 23),
            done=False,
            rest="busy",
            items=[LogItem(exercise="深蹲", sets=3)],
        )


def test_checkin_with_state_records_sore_muscles() -> None:
    c, book, _ = client()
    r = c.post(
        "/iron/api/workouts",
        json={"session": "下肢", "energy": "good", "slept": "poor", "sore": ["大腿后"]},
    )
    assert r.status_code == 200
    [row] = asyncio.run(book.workouts("42", date.today() - timedelta(days=7)))
    assert (row.log.energy, row.log.slept, row.log.sore) == ("good", "poor", ["大腿后"])
    from ironm_agent import web_more

    feels = c.app.dependency_overrides[web_more.feel_store]()
    assert {m for m, f, _ in feels.rows["42"] if f == "sore"} == set(SORE_MUSCLES["大腿后"])
    assert c.post("/iron/api/workouts", json={"sore": ["脚趾"]}).status_code == 422


def test_rest_checkin_is_kept_but_not_done() -> None:
    c, book, _ = client()
    r = c.post("/iron/api/workouts", json={"done": True, "rest": "sick", "note": "感冒"})
    assert r.status_code == 200
    [row] = asyncio.run(book.workouts("42", date.today() - timedelta(days=7)))
    assert (
        row.log.rest == "sick" and row.log.done is False and row.log.items == []
    )  # 记没练一律不算练了
    cal = c.get("/iron/api/calendar").json()
    today = date.today().isoformat()
    assert cal["done_days"] == [] and cal["rest_days"] == [today] and cal["streak_days"] == 1


def test_calendar_trajectory_numbers() -> None:
    c, book, _ = client()
    today = date.today()
    sets = [SetDone(reps=10, weight_kg=40)] * 3
    asyncio.run(book.log("42", WorkoutLog(day=today, minutes=50, items=[
        LogItem(exercise="深蹲", done_sets=sets), LogItem(exercise="硬拉", sets=4)])))  # fmt: skip
    asyncio.run(book.log("42", WorkoutLog(day=today, done=False)))  # 没练完的不算组数和时长
    got = c.get("/iron/api/calendar").json()
    assert got["sets"] == {today.isoformat(): 7}  # 没填每组的按计划组数算
    assert got["month_minutes"] == 50 and got["streak_days"] == 1


def test_streak_counts_rest_days_and_starts_from_yesterday() -> None:
    t = date(2026, 10, 23)
    days = {t - timedelta(days=i) for i in (1, 2, 3, 5)}
    assert checkin_streak(days, t) == 3  # 今天还没打卡从昨天数，断在 10-19
    assert checkin_streak(days | {t}, t) == 4
    assert checkin_streak(set(), t) == 0


def test_today_block_shows_state_and_rest() -> None:
    class Stored:
        def __init__(self, log: WorkoutLog) -> None:
            self.log, self.created = log, datetime(2026, 10, 23, 6, 5, tzinfo=UTC)

    t = date(2026, 10, 23)
    done = Stored(WorkoutLog(day=t, session="下肢", energy="poor", sore=["臀"]))
    out = lines(None, today=t, plan_name="下肢", checkins=[done])
    assert any(x.startswith("已打卡：下肢") and "精力差，臀酸" in x for x in out)
    rest = Stored(WorkoutLog(day=t, done=False, rest="sick"))
    out = lines(None, today=t, plan_name="下肢", checkins=[rest])
    assert any(x.startswith("今天记了没练：") and "生病" in x for x in out) and "还没打卡" in out


def test_live_finish_keeps_state(monkeypatch: pytest.MonkeyPatch) -> None:
    c, book, _ = live_client(monkeypatch, plan=PLAN)
    from ironm_agent import muscle_feel, web_more

    feels = muscle_feel.FeelBook()
    c.app.dependency_overrides[web_more.feel_store] = lambda: feels  # type: ignore[attr-defined]
    live = c.post("/iron/api/live/start", json={"today_plan": True}).json()["live"]
    live["items"][0]["sets"][0] |= {"done": True, "at": datetime.now().isoformat(), "reps": 5}
    c.put("/iron/api/live", json={"id": live["id"], "items": live["items"]})
    r = c.post("/iron/api/live/finish", json={"rpe": 7, "energy": "ok", "sore": ["胸"]})
    assert r.status_code == 200
    [row] = asyncio.run(book.workouts("42", date.today() - timedelta(days=7)))
    assert row.log.energy == "ok" and row.log.sore == ["胸"] and row.log.rpe == 7
    assert {m for m, _, _ in feels.rows["42"]} == set(SORE_MUSCLES["胸"])


def test_page_has_state_picker_rest_sheet_and_trajectory() -> None:
    parts = re.search(r"const SORE_PARTS = \[(.*?)\];", JS)
    assert parts and [x.strip(' "') for x in parts.group(1).split(",")] == list(
        SORE_PARTS
    )  # 和后端一致
    assert "...st.read()" in JS and JS.count("stateBox()") >= 3  # 打卡和记录器结束都能记状态
    assert "rest: why" in JS and "今天没练？" in JS
    assert 'tile("check", "练完打卡", "没练也能记", checkin)' in JS
    log = JS[
        JS.index("async function recordPage") : JS.index("// ---- 身体")
    ]  # §137 轨迹并进战绩一页
    assert "cal.streak_days" in log and "cal.month_minutes" in log and "x.rest" in log
    assert "cal.sets?.[iso]" in JS and "rest_days" in JS  # 月历按组数分深浅、没练的日子另一种颜色
