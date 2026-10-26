"""天气是训练安排的一部分（spec [2026-10-23] §34）：按本周每天的天气改出版本、管家方案、共享档案、
本周计划接口、首页鼓励的话。不连网络、不连数据库。"""

import asyncio
from datetime import date, timedelta

import pytest

from ironm_agent.brief import CHEERS, cheer
from ironm_agent.training import Plan
from ironm_agent.weather import Day, Weather, assess
from ironm_agent.weather_plan import forecast_line, line, week_plan

MON = date(2026, 10, 26)  # 周一
PLAN = Plan.model_validate({"title": "x", "days_per_week": 3, "sessions": [
    {"day": 1, "name": "下肢", "items": [{"exercise": "杠铃深蹲", "sets": 4, "reps": "8"},
                                        {"exercise": "慢跑", "sets": 1, "reps": "20 分钟"}]},
    {"day": 3, "name": "上肢", "items": [{"exercise": "哑铃卧推", "sets": 3, "reps": "10"}]},
    {"day": 5, "name": "全身", "items": [{"exercise": "俯卧撑", "sets": 3, "reps": "10"},
                                        {"exercise": "户外慢跑", "sets": 1, "reps": "25 分钟"}]}]})  # fmt: skip


def days(**special: tuple[int, float, int]) -> tuple[Day, ...]:
    """周一起 7 天的预报；special：星期几（mon…sun）→ (天气代码, 最高气温, 降水概率)。"""
    keys = ("mon", "tue", "wed", "thu", "fri", "sat", "sun")
    out = []
    for i, k in enumerate(keys):
        code, tmax, rain = special.get(k, (0, 23.0, 0))
        out.append(Day((MON + timedelta(days=i)).isoformat(), code, tmax, 14, 13, rain, 10))
    return tuple(out)


def test_rain_moves_outdoor_cardio_indoors_and_suggests_a_better_day() -> None:
    week = week_plan(PLAN, days(fri=(65, 20.0, 90), wed=(65, 20.0, 90), sat=(0, 23.0, 0)), MON)
    fri = week[4]
    assert fri.adjusted and "户外慢跑换成" in fri.changes[0] and fri.version is not None
    assert [i.exercise for i in fri.version.items][1] != "户外慢跑" and fri.better == date(
        2026, 10, 31
    )
    assert "也可以挪到周六" in line(fri)
    assert not week[2].adjusted  # 周三下雨但只有室内动作：不调整
    assert all(not p.adjusted for p in week if p.session is None)


def test_heat_and_light_rain_and_past_days() -> None:
    week = week_plan(PLAN, days(wed=(0, 36.0, 0), fri=(61, 20.0, 30)), date(2026, 10, 28))
    assert not week[0].adjusted  # 过去的日子不调整
    assert (
        week[2].changes == ("降低强度、缩短时间，避开中午，多补水",) and "36℃" in week[2].reasons[0]
    )
    assert not week[4].adjusted  # 降水概率 30%：只提醒可能有雨，不换室内


def test_today_uses_live_weather() -> None:
    live = assess(Weather("上海", 18, 17, 90, 63, 9))  # 现在在下雨（预报里今天是晴）
    mon = week_plan(PLAN, days(), MON, live)[0]
    assert mon.adjusted and mon.advice is live and mon.better == date(2026, 10, 27)


def test_forecast_line_for_case_file() -> None:
    text = forecast_line(days(thu=(63, 20.0, 85)), MON)
    assert text.startswith("周二晴") and "周四雨 14–20℃，降水85%" in text and "周一" not in text


def test_coach_plan_has_weather_item() -> None:
    from ironm_agent.casefile import Snapshot
    from ironm_agent.coach_state import Inputs, compute

    inp = Inputs(snapshot=Snapshot(), plan=PLAN, forecast=days(fri=(65, 20.0, 90)))
    items = compute(inp, MON)
    weather = next(x for x in items if x.kind == "weather")
    assert weather.action == "auto" and "周五" in weather.title and "户外慢跑" in weather.title
    assert weather.value["days"][0]["better"] == "周六"
    assert [x.kind for x in items][:2] == ["today", "weather"]
    assert not [
        x
        for x in compute(Inputs(snapshot=Snapshot(), plan=PLAN, forecast=days()), MON)
        if x.kind == "weather"
    ]


def test_case_file_weather_includes_forecast_and_adjustments() -> None:
    from ironm_agent.plugin import _weather_case

    w = Weather("上海", 22, 21, 50, 0, 9, days=days(fri=(65, 20.0, 90)))
    text = _weather_case(w, PLAN, MON)
    assert "现在的天气" in text and "未来几天：周二晴" in text
    assert "按天气对本周训练的调整：周五雨：全身" in text and "周六" in text


def test_cheer_lines() -> None:
    session = {"training": {"kind": "session", "name": "下肢"}, "readiness": {"level": "good"}}
    assert (
        cheer({**session, "training": {**session["training"], "done": True}}, {})
        == "今天的训练完成了，干得漂亮！"
    )
    assert "赢了一半" in cheer(
        {**session, "readiness": {"level": "poor"}}, {"planned": 3, "done": 0}
    )
    assert "下雨" in cheer(session, {"planned": 3, "done": 0}, rainy=True)
    assert "已经拿下" in cheer(session, {"planned": 3, "done": 3})
    assert "休息" in cheer({"training": {"kind": "rest"}}, {"planned": 3, "done": 1})
    assert (
        cheer(session, {"planned": 3, "done": 0}, on=MON) in CHEERS
    )  # 普通的一天：按日期轮换的一句


def test_week_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import weather as wmod
    from ironm_agent.training import plan_content
    from tests.test_frontend_api import client

    c, book, _ = client()
    d = asyncio.run(book.add_draft("42", "plan", plan_content(PLAN)))
    asyncio.run(book.confirm("42", d.id))
    today = date.today()
    monday = date.fromordinal(today.toordinal() - today.isoweekday() + 1)

    async def place(_: str) -> tuple[str, wmod.Place]:
        return "上海", wmod.Place("上海", 31.0, 121.0)

    async def fetch(_: object) -> Weather:
        f = [
            Day(date.fromordinal(today.toordinal() + i).isoformat(), 65, 20, 14, 13, 90, 10)
            for i in range(7)
        ]
        return Weather("上海", 18, 17, 90, 63, 9, days=tuple(f))

    monkeypatch.setattr(wmod, "load_place", place)
    monkeypatch.setattr(wmod, "safe_fetch", fetch)
    got = c.get("/iron/api/week").json()
    assert got["weather"] == "ok" and got["place"] == "上海" and len(got["days"]) == 7
    assert got["days"][0]["date"] == monday.isoformat()
    fri = got["days"][4]
    assert fri["session"]["name"] == "全身" and fri["outdoor"] == ["户外慢跑"]
    if not fri["past"]:
        assert fri["changes"] and fri["version"] and fri["weather"]["level"] == "indoor"
