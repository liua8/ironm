"""定位和查天气（spec [2026-10-23] §173）。不连网、不调用真实模型。"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from ironm_agent import weather as wx

DAYS = (
    wx.Day("2026-11-06", 3, 19.0, 14.0, 13.0, 0, 9.0),
    wx.Day("2026-11-07", 61, 20.0, 14.0, 13.0, 94, 20.0),
)
NOW = wx.Weather("浙江省上城区", 20.0, 19.0, 59.0, 0, 10.0, pm25=8.0, pm10=15.0, observed="2026-11-06T15:30",
                 days=DAYS)  # fmt: skip


def test_locate_keeps_only_about_a_kilometre_and_names_the_city(monkeypatch: pytest.MonkeyPatch) -> None:
    sent: list[dict[str, Any]] = []

    async def fake_get(url: str, params: dict[str, Any], headers: Any = None) -> dict[str, Any]:
        sent.append(params)
        return {"address": {"city": "上城区", "state": "浙江省", "country": "中国"}}

    monkeypatch.setattr(wx, "_get", fake_get)
    wx._names.clear()
    p = asyncio.run(wx.locate(30.274123, 120.155187))
    assert (p.lat, p.lon, p.name) == (30.27, 120.16, "浙江省上城区")
    assert sent == [{"lat": 30.3, "lon": 120.2, "format": "jsonv2", "zoom": 10, "accept-language": "zh"}]  # 只给粗位置


def test_unknown_place_is_called_current_location(monkeypatch: pytest.MonkeyPatch) -> None:
    async def broken(*_: Any, **__: Any) -> dict[str, Any]:
        raise OSError("down")

    monkeypatch.setattr(wx, "_get", broken)
    wx._names.clear()
    assert asyncio.run(wx.locate(10.0, 20.0)).name == "当前位置"
    assert not wx.valid_point(0, 0) and not wx.valid_point(91, 10) and wx.valid_point(30.27, 120.16)


def test_report_has_now_air_and_each_day() -> None:
    text = wx.report(NOW)
    assert "浙江省上城区 晴，20℃（体感 19℃），空气质量优" in text and "湿度 59%" in text
    assert "11月6日 周五：" in text and "降水概率 94%" in text and "建议在室内练" in text


def tool(monkeypatch: pytest.MonkeyPatch, place: Any, fetched: Any = NOW) -> tuple[Any, Any]:
    from types import SimpleNamespace

    from ironm_agent.tools import Evidence, Toolbox
    from tests.test_plugin import agent

    async def load(user_id: str) -> tuple[str, Any]:
        return ("", place)

    async def fetch(p: Any) -> Any:
        if isinstance(fetched, Exception):
            raise fetched
        return fetched

    async def geocode(city: str) -> Any:
        return wx.Place(city, 30.0, 120.0) if city != "火星" else None

    monkeypatch.setattr(wx, "load_place", load)
    monkeypatch.setattr(wx, "fetch", fetch)
    monkeypatch.setattr(wx, "geocode", geocode)
    a = agent(lambda *_: None, monkeypatch=monkeypatch)  # type: ignore[arg-type,return-value]
    [(_, run)] = a._weather_tool("42").values()
    box = SimpleNamespace(evidence=Evidence(), _outcome="ok")
    box.add_calc = lambda d: Toolbox.add_calc(box, d)  # type: ignore[arg-type]
    return run, box


def test_the_coach_can_look_up_the_weather_and_cite_it(monkeypatch: pytest.MonkeyPatch) -> None:
    from ironm_agent.checks import check_text

    run, box = tool(monkeypatch, wx.Place("浙江省上城区", 30.27, 120.16))
    said = asyncio.run(run(box, {}))
    assert said.startswith("浙江省上城区的天气（引用这些数时句末写〔C1〕）") and "11月7日" in said
    answer = "周六有雨，降水概率 94%，那天改在室内练〔C1〕。"
    assert check_text(answer, support={}, entries={}, question="", calcs=box.evidence.calcs) == []
    other = asyncio.run(run(box, {"city": "北京"}))
    assert other.startswith("北京的天气（引用这些数时句末写〔C2〕）")
    assert "没找到「火星」" in asyncio.run(run(box, {"city": "火星"}))


def test_no_place_and_errors_are_said_plainly(monkeypatch: pytest.MonkeyPatch) -> None:
    run, box = tool(monkeypatch, None)
    assert "用当前位置" in asyncio.run(run(box, {}))
    run2, box2 = tool(monkeypatch, wx.Place("x", 1.0, 1.0), fetched=OSError("down"))
    assert "没取到天气" in asyncio.run(run2(box2, {})) and box2._outcome == "error"


def test_locate_endpoint(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from mirobody.server.auth import verify_token

    from ironm_agent import web

    saved: list[Any] = []

    async def locate(lat: float, lon: float) -> wx.Place:
        return wx.Place("浙江省上城区", round(lat, 2), round(lon, 2))

    async def save(user_id: str, city: str, place: wx.Place) -> None:
        saved.append((user_id, city, place))

    monkeypatch.setattr(wx, "locate", locate)
    monkeypatch.setattr(wx, "save_place", save)
    app = FastAPI()
    app.include_router(web.router)
    app.dependency_overrides[verify_token] = lambda: "42"
    c = TestClient(app)
    r = c.post("/iron/api/place/locate", json={"lat": 30.27, "lon": 120.16})
    assert r.json() == {"city": "浙江省上城区", "label": "浙江省上城区"}
    assert saved == [("42", "浙江省上城区", wx.Place("浙江省上城区", 30.27, 120.16))]
    assert c.post("/iron/api/place/locate", json={"lat": 0, "lon": 0}).status_code == 422


def test_the_tool_is_offered_and_listed() -> None:
    from ironm_agent.agent import _PROMPT
    from ironm_agent.tool_catalog import CATALOG
    from ironm_agent.tools import STEP_NAMES

    assert any(t.agent == wx.QUERY for t in CATALOG) and STEP_NAMES[wx.QUERY] == "查天气"
    assert "query_weather" in _PROMPT


def test_the_page_locates_only_when_asked_and_rounds_first() -> None:
    from pathlib import Path

    js = (Path(__file__).resolve().parent.parent / "ironm_agent" / "web" / "app.js").read_text()
    body = js.split("const locate = (place, msg) => {")[1].split("\n  };")[0]
    assert "getCurrentPosition" in body and "toFixed(2)" in body and "/iron/api/place/locate" in body
    assert js.count("getCurrentPosition") == 1  # 只有这一处：点了"用当前位置"才取
    assert "onclick: () => locate(place, msg)" in js
