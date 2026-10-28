"""前端改版的计算与接口（spec [2026-10-23] §13）：天气判断、人体图、饮食记录与推荐、动作视频、训练日历。

不连网、不连数据库、不调用真实模型。
"""

import asyncio
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ironm_agent import weather
from ironm_agent.meals import (
    DayContext,
    Macros,
    MealBook,
    Recommendation,
    estimate,
    over_budget,
    presets,
    recommend,
)
from ironm_agent.memory_store import MemoryBook
from ironm_agent.protools.muscle_map import muscle_map
from ironm_agent.training import LogItem, Plan, TrainingBook, WorkoutLog
from tests.fakes import FakeLLM, jsonr

TODAY = date(2026, 10, 23)


def wx(**kw: Any) -> weather.Weather:
    base: dict[str, Any] = {
        "place": "杭州市",
        "temperature": 22.0,
        "feels_like": 22.0,
        "humidity": 60.0,
        "code": 0,
        "wind_kmh": 8.0,
    }
    return weather.Weather(**(base | kw))


# ---- 天气 -----------------------------------------------------------------------------------


def test_aqi_from_pm() -> None:
    assert weather.aqi(35, None) == 50 and weather.aqi(75, 40) == 100
    assert weather.aqi(120, 60) == 157  # PM2.5 120 → 中度污染
    assert weather.aqi_level(157)[0] == "中度污染"
    assert weather.aqi(None, None) is None


def test_assess_weather() -> None:
    assert weather.assess(wx()).level == "good"
    polluted = weather.assess(wx(pm25=120.0))
    assert (
        polluted.level == "indoor"
        and "中度污染" in polluted.reasons[0]
        and "减少户外运动" in polluted.reasons[0]
    )
    hot = weather.assess(wx(temperature=36.0, feels_like=40.0))
    assert hot.level == "caution" and "35℃" in hot.reasons[0]
    assert weather.assess(wx(temperature=41.0)).level == "avoid"
    assert weather.assess(wx(code=95)).level == "avoid"  # 雷暴
    assert weather.assess(wx(code=63)).level == "indoor"  # 雨
    assert weather.assess(wx(feels_like=-12.0)).level == "indoor"
    worst = weather.assess(wx(code=63, pm25=300.0))
    assert worst.level == "avoid" and len(worst.reasons) == 2  # 取最严的那档，原因都列出


def test_case_line() -> None:
    line = weather.case_line(wx(pm25=120.0))
    assert "杭州市 晴" in line and "建议在室内练" in line
    assert weather.case_line(None) == ""


def test_safe_fetch_returns_none_on_error(monkeypatch: pytest.MonkeyPatch) -> None:
    async def boom(*_: Any) -> Any:
        raise TimeoutError

    monkeypatch.setattr(weather, "fetch", boom)
    assert asyncio.run(weather.safe_fetch(weather.Place("x", 1, 2))) is None
    assert asyncio.run(weather.safe_fetch(None)) is None


# ---- 人体图 ---------------------------------------------------------------------------------


def _muscle(m: dict[str, Any], name: str) -> dict[str, Any]:
    return next(x for x in m["muscles"] if x["name"] == name)  # type: ignore[attr-defined]


def test_muscle_map_sets_by_main_and_assist() -> None:
    """spec [2026-10-23] §30：细分肌肉；主要练到每组记 1 组，辅助练到按半组；按近 7 天组数分档。"""
    logs = [
        WorkoutLog(day=TODAY - timedelta(days=2), items=[LogItem(exercise="高脚杯深蹲", sets=3)]),
        WorkoutLog(day=TODAY - timedelta(days=5), items=[LogItem(exercise="哑铃卧推", sets=4)]),
        WorkoutLog(day=TODAY - timedelta(days=6), items=[LogItem(exercise="哑铃卧推", sets=6)]),
        WorkoutLog(
            day=TODAY - timedelta(days=12), items=[LogItem(exercise="单臂哑铃划船", sets=3)]
        ),
    ]
    m = muscle_map(logs, TODAY)
    quad = _muscle(m, "股四头肌")
    assert quad["sets_7d"] == 3 and quad["level"] == "low" and quad["last"] == "2026-10-21"
    assert "高脚杯深蹲 3 组" in quad["history"][0]
    assert _muscle(m, "胸大肌中下部")["sets_7d"] == 10 and _muscle(m, "胸大肌中下部")["level"] == "high"
    assert (
        _muscle(m, "三角肌前束")["sets_7d"] == 5
        and "（辅助）" in _muscle(m, "三角肌前束")["history"][0]
    )
    assert _muscle(m, "腹直肌")["sets_7d"] == 1.5  # 高脚杯深蹲辅助练到核心
    lat = _muscle(m, "背阔肌")
    assert lat["level"] == "none" and lat["last"] == "2026-10-11" and "背阔肌" in m["untrained"]  # type: ignore[operator]
    assert len(m["muscles"]) == 28 and all(x["code"].startswith("muscle.") and x["part"] for x in m["muscles"])  # type: ignore[union-attr]
    assert "胫骨前肌" not in m["untrained"]  # type: ignore[operator]  # 动作库里没有主要练它的动作，不列


def test_muscle_map_uses_plan_for_quick_checkin() -> None:
    plan = Plan.model_validate(
        {"title": "x", "days_per_week": 1,
         "sessions": [{"day": 3, "name": "上肢拉", "items": [{"exercise": "单臂哑铃划船", "sets": 4, "reps": "10"}]}]}
    )  # fmt: skip
    logs = [WorkoutLog(day=TODAY - timedelta(days=1), session="上肢拉")]  # 首页一键打卡，没写动作
    assert _muscle(muscle_map(logs, TODAY, plan), "背阔肌")["sets_7d"] == 4


def test_every_tagged_muscle_is_on_the_map() -> None:
    from ironm_agent.protools.movement import moves
    from ironm_agent.protools.muscle_map import MUSCLES
    from ironm_agent.protools.recovery import BASE_DAYS

    assert set(BASE_DAYS) == set(MUSCLES)
    for mv in moves():
        assert set(mv.tag.muscles) | set(mv.tag.assist) <= set(MUSCLES), mv.name


# ---- 饮食 -----------------------------------------------------------------------------------


def test_presets_are_consistent() -> None:
    ps = presets()
    assert len(ps) >= 10 and {p.scene for p in ps} == {"外卖", "食堂", "便利店", "自己做"}


def test_estimate_reconciles_kcal() -> None:
    llm = FakeLLM(lambda *_: jsonr({"name": "牛肉面", "items": ["牛肉面半碗"], "kcal": 900,
                                    "protein_g": 20, "carbs_g": 60, "fat_g": 10, "confidence": "中"}))  # fmt: skip
    meal = asyncio.run(
        estimate(
            llm,
            "一碗牛肉面，吃了一半",
            "午餐",
            {"type": "image_url", "image_url": {"url": "data:x"}},
        )
    )
    assert meal is not None and meal.macros.kcal == 410  # 20×4 + 60×4 + 10×9
    assert "重新算过" in meal.note and meal.estimated and meal.said.startswith("一碗牛肉面")
    sent = llm.seen[0][1][-1]["content"]
    assert isinstance(sent, list) and sent[1]["type"] == "image_url"  # 照片交给了模型


def _rec(kcal: float) -> dict[str, Any]:
    return {"title": "清淡午餐", "why": "胃口清淡",
            "dishes": [{"name": "清蒸鱼", "amount": "150 克", "kcal": kcal, "protein_g": 30, "carbs_g": 0, "fat_g": 5}]}  # fmt: skip


def test_recommend_retries_when_over_budget() -> None:
    ctx = DayContext(
        kind="晚餐",
        appetite="清淡",
        target=Macros(kcal=1800, protein_g=110, carbs_g=0, fat_g=0),
        eaten=Macros(kcal=1500, protein_g=80, carbs_g=0, fat_g=0),
        weather="现在的天气：杭州市 晴，30℃",
        limits=("乳糖不耐受",),
    )
    replies = iter([jsonr(_rec(900)), jsonr(_rec(300))])
    llm = FakeLLM(lambda *_: next(replies))
    rec, problem = asyncio.run(recommend(llm, ctx))
    assert rec is not None and rec.total().kcal == 300 and problem == ""
    retry = llm.seen[1][1][-1]["content"]
    assert "超出了今天剩下的约 300 千卡" in retry
    prompt = llm.seen[0][1][-1]["content"]
    assert "胃口：清淡" in prompt and "乳糖不耐受" in prompt and "杭州市" in prompt


def test_appetite_goes_into_prompt() -> None:
    a = DayContext(kind="午餐", appetite="清淡").text()
    b = DayContext(kind="午餐", appetite="很饿").text()
    assert "清淡" in a and "很饿" in b and a != b
    assert (
        over_budget(
            Recommendation.model_validate(_rec(500)), DayContext(kind="午餐", appetite="正常")
        )
        == ""
    )


# ---- 接口 -----------------------------------------------------------------------------------


def client(
    user: str = "42", monkeypatch: pytest.MonkeyPatch | None = None
) -> tuple[TestClient, TrainingBook, MealBook]:
    from mirobody.server.auth import verify_token

    from ironm_agent import web, web_more

    book, meals = TrainingBook(), MealBook()
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: user
    app.dependency_overrides[web_more.training_store] = lambda: book
    app.dependency_overrides[web_more.memory_store] = lambda: MemoryBook()
    app.dependency_overrides[web_more.meal_store] = lambda: meals
    feels = __import__("ironm_agent.muscle_feel", fromlist=["FeelBook"]).FeelBook()
    app.dependency_overrides[web_more.feel_store] = lambda: feels
    if monkeypatch is not None:

        async def no_targets(_: str) -> tuple[Any, str, Any]:
            return Macros(kcal=2000, protein_g=120, carbs_g=0, fat_g=0), "减脂", None

        monkeypatch.setattr(web_more, "_targets", no_targets)
    return TestClient(app), book, meals


def test_calendar_lights_done_days() -> None:
    c, book, _ = client()
    today = date.today()
    asyncio.run(book.log("42", WorkoutLog(day=today, session="下肢", rpe=6)))
    asyncio.run(book.log("42", WorkoutLog(day=today, done=False)))
    asyncio.run(book.log("7", WorkoutLog(day=today)))  # 别人的
    got = c.get("/iron/api/calendar").json()
    assert got["done_days"] == [today.isoformat()]
    assert (
        len(got["days"][today.isoformat()]) == 2
        and "下肢" in got["days"][today.isoformat()][0]["line"]
    )
    assert c.get("/iron/api/calendar?month=2026-13x").status_code == 422


def test_muscles_endpoint() -> None:
    c, book, _ = client()
    asyncio.run(
        book.log("42", WorkoutLog(day=date.today(), items=[LogItem(exercise="俯卧撑", sets=3)]))
    )
    got = c.get("/iron/api/muscles").json()
    chest = _muscle(got, "胸大肌中下部")
    assert chest["sets_7d"] == 3 and chest["state"] == "today" and "腘绳肌" in got["untrained"]
    fine = c.post("/iron/api/muscles/feel", json={"muscle": "muscle.pec_major_lower", "feel": "fine"}).json()
    assert fine["recovering"] == ["肱三头肌"]  # 本人说胸不酸了：以本人说的为准，只改胸大肌
    assert (
        c.post("/iron/api/muscles/feel", json={"muscle": "胸", "feel": "fine"}).status_code == 422
    )
    sore = c.post("/iron/api/muscles/feel", json={"muscle": "muscle.hamstrings", "feel": "sore"}).json()
    assert _muscle(sore, "腘绳肌")["state"] == "sore"


def test_meal_log_preset_and_privacy(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent import web_more
    from ironm_agent.meals import Meal

    c, _, meals = client(monkeypatch=monkeypatch)

    async def fake_estimate(llm: Any, said: str, kind: Any, image: Any = None) -> Meal:
        return Meal(
            kind=kind,
            name="牛肉面",
            items=["半碗"],
            macros=Macros(kcal=410, protein_g=20, carbs_g=60, fat_g=10),
            said=said,
        )

    monkeypatch.setattr(web_more, "estimate", fake_estimate)
    r = c.post("/iron/api/meals", data={"said": "一碗牛肉面吃了一半", "kind": "午餐"},
               files={"photo": ("a.jpg", b"\xff\xd8fake", "image/jpeg")})  # fmt: skip
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["meal"]["estimated"] and got["meal"]["has_photo"] and got["totals"]["kcal"] == 410
    assert got["target"]["kcal"] == 2000
    meal_id = got["meal"]["id"]
    assert c.get(f"/iron/api/meals/{meal_id}/photo").content == b"\xff\xd8fake"
    pid = presets()[0].id
    after = c.post("/iron/api/meals/preset", json={"preset": pid, "kind": "晚餐"}).json()
    assert after["totals"]["kcal"] == 410 + presets()[0].kcal and len(after["meals"]) == 2
    other, _, _ = client(user="7")
    other.app.dependency_overrides[web_more.meal_store] = lambda: meals  # type: ignore[attr-defined]
    assert other.get(f"/iron/api/meals/{meal_id}/photo").status_code == 404
    assert other.get("/iron/api/meals").json()["meals"] == []
    assert other.delete(f"/iron/api/meals/{meal_id}").status_code == 404
    assert c.post("/iron/api/meals", data={"said": "", "kind": "午餐"}).status_code == 422
    assert c.post("/iron/api/meals", data={"said": "x", "kind": "下午茶"}).status_code == 422


def test_video_upload_admin_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    from ironm_agent import web_more

    monkeypatch.setenv("IRONM_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("IRONM_ADMINS", "1")
    c, _, _ = client(user="42")
    files = {"file": ("v.mp4", b"\x00\x00video", "video/mp4")}
    assert c.post("/iron/api/exercises/goblet-squat/video", files=files).status_code == 403
    admin, _, _ = client(user="1")
    assert admin.post("/iron/api/exercises/no-such/video", files=files).status_code == 404
    bad = {"file": ("v.txt", b"x", "text/plain")}
    assert admin.post("/iron/api/exercises/goblet-squat/video", files=bad).status_code == 415
    assert admin.post("/iron/api/exercises/goblet-squat/video", files=files).status_code == 200
    assert (tmp_path / "videos" / "goblet-squat.mp4").exists()
    assert c.get("/iron/api/videos").json()["videos"] == ["goblet-squat"]
    assert c.get("/iron/api/exercises/goblet-squat/video").content == b"\x00\x00video"
    assert c.get("/iron/api/me").json() == {"admin": False}
    assert admin.get("/iron/api/me").json() == {"admin": True}
    assert c.delete("/iron/api/exercises/goblet-squat/video").status_code == 403
    assert admin.delete("/iron/api/exercises/goblet-squat/video").status_code == 200
    assert web_more._video_path("goblet-squat") is None


def test_weather_endpoint_states(monkeypatch: pytest.MonkeyPatch) -> None:
    c, _, _ = client()

    async def none_place(_: str) -> tuple[str, Any]:
        return "", None

    monkeypatch.setattr(weather, "load_place", none_place)
    assert c.get("/iron/api/weather").json() == {"status": "no_city"}

    async def a_place(_: str) -> tuple[str, Any]:
        return "杭州", weather.Place("杭州市", 30.3, 120.2)

    async def down(_: Any) -> None:
        return None

    monkeypatch.setattr(weather, "load_place", a_place)
    monkeypatch.setattr(weather, "safe_fetch", down)
    assert c.get("/iron/api/weather").json()["status"] == "unavailable"

    async def up(_: Any) -> weather.Weather:
        return wx(pm25=120.0)

    monkeypatch.setattr(weather, "safe_fetch", up)
    got = c.get("/iron/api/weather").json()
    assert (
        got["status"] == "ok"
        and got["aqi_level"] == "中度污染"
        and got["advice"]["level"] == "indoor"
    )


def test_weather_goes_into_case_file() -> None:
    from dataclasses import replace

    from ironm_agent.casefile import Snapshot, build
    from ironm_agent.memory_view import Recall

    case = build(Snapshot(), Recall(), "今天去跑步吗")
    case = replace(case, weather=weather.case_line(wx(pm25=120.0)))
    assert "建议在室内练" in case.text()


def test_recommend_clips_long_output() -> None:
    long = {"title": "很饿时的高蛋白大餐" * 5, "why": "饱腹" * 200,
            "dishes": [{"name": f"菜{i}" * 20, "amount": "一大份" * 20, "kcal": 50, "protein_g": 5, "carbs_g": 5, "fat_g": 1} for i in range(12)]}  # fmt: skip
    llm = FakeLLM(lambda *_: jsonr(long))
    rec, problem = asyncio.run(recommend(llm, DayContext(kind="晚餐", appetite="很饿")))
    assert rec is not None and len(rec.dishes) == 8 and len(rec.title) <= 30 and problem == ""


# ---- 首页日历的天气预报（spec [2026-10-23] §33）------------------------------------------------


def test_forecast_days_parsed_and_assessed(monkeypatch: pytest.MonkeyPatch) -> None:
    daily = {
        "time": ["2026-10-26", "2026-10-27", "2026-10-28", "2026-10-29"],
        "weather_code": [0, 61, 61, 95],
        "temperature_2m_max": [24.0, 20.0, 38.0, None],  # 最后一天缺数：跳过
        "temperature_2m_min": [15.0, 14.0, 26.0, 12.0],
        "apparent_temperature_min": [14.0, 13.0, 27.0, 11.0],
        "precipitation_probability_max": [0, 30, 80, 90],
        "wind_speed_10m_max": [10.0, 12.0, 8.0, 15.0],
    }

    async def fake_get(url: str, params: dict[str, Any]) -> dict[str, Any]:
        if url == weather.AIR_URL:
            return {"current": {"pm2_5": 10, "pm10": 20}}
        assert params["forecast_days"] == 7 and "precipitation_probability_max" in params["daily"]
        cur = {"temperature_2m": 22.0, "apparent_temperature": 21.0, "weather_code": 0}
        return {"current": cur, "daily": daily}

    from ironm_agent import web_more

    monkeypatch.setattr(weather, "_get", fake_get)
    weather._cache.clear()
    w = asyncio.run(weather.fetch(weather.Place("上海", 31.0, 121.0)))
    assert [d.day for d in w.days] == ["2026-10-26", "2026-10-27", "2026-10-28"]
    sunny, maybe, wet_hot = (weather.assess_day(d) for d in w.days)
    assert sunny.level == "good"
    assert (
        maybe.level == "caution" and "可能有雨" in maybe.reasons[-1] and "30%" in maybe.reasons[-1]
    )
    assert wet_hot.level == "indoor"  # 38℃ 到高温橙色档、雨的概率 80%：取最严的一档
    assert any("室内" in r for r in wet_hot.reasons) and any("38℃" in r for r in wet_hot.reasons)
    out = web_more.weather_json(w, True)
    assert [f["date"] for f in out["forecast"]] == ["2026-10-26", "2026-10-27", "2026-10-28"]
    assert out["forecast"][1] == {"date": "2026-10-27", "text": "雨", "tmax": 20, "tmin": 14, "rain": 30,
                                  "level": "caution", "name": "户外要注意", "reasons": list(maybe.reasons)}  # fmt: skip
